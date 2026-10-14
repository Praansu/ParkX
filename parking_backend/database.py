import sqlite3
from datetime import datetime, timedelta
from parking_backend.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT    NOT NULL,
                slot1      INTEGER,
                slot2      INTEGER,
                slot3      INTEGER,
                gate       INTEGER,
                event_type TEXT,
                detail     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT    NOT NULL,
                alert_type TEXT    NOT NULL,
                severity   TEXT    NOT NULL,
                message    TEXT    NOT NULL,
                emailed    INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id         TEXT    PRIMARY KEY,
                slot       INTEGER NOT NULL,
                date       TEXT    NOT NULL,
                time       TEXT    NOT NULL,
                dur        INTEGER NOT NULL,
                name       TEXT    NOT NULL,
                phone      TEXT,
                plate      TEXT    NOT NULL,
                amount     INTEGER NOT NULL,
                status     TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date);

            CREATE TABLE IF NOT EXISTS payments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT    NOT NULL,
                gateway    TEXT    NOT NULL,
                txn_id     TEXT    NOT NULL UNIQUE,
                amount_npr INTEGER NOT NULL,
                status     TEXT    NOT NULL,
                raw        TEXT    DEFAULT '',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_payments_booking ON payments(booking_id);

            CREATE TABLE IF NOT EXISTS operators (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL UNIQUE,
                role       TEXT    NOT NULL,
                key_hash   TEXT    NOT NULL,
                active     INTEGER DEFAULT 1,
                created_at TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS lots (
                id          TEXT    PRIMARY KEY,
                name        TEXT    NOT NULL,
                slot_count  INTEGER NOT NULL DEFAULT 3,
                pricing_json TEXT   DEFAULT '',
                blynk_token TEXT    DEFAULT '',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS slots (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id     TEXT    NOT NULL,
                label      TEXT    NOT NULL,
                kind       TEXT    NOT NULL DEFAULT 'standard',
                UNIQUE(lot_id, label)
            );
        """)
    # Migration for databases created before payments existed.
    with get_connection() as conn:
        cols = [
            r["name"] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()
        ]
        if "payment_status" not in cols:
            conn.execute(
                "ALTER TABLE bookings ADD COLUMN payment_status TEXT DEFAULT 'UNPAID'"
            )
    # Migration for databases created before multi-lot support existed.
    # Existing rows belong to the default lot, so the default keeps them visible.
    with get_connection() as conn:
        booking_cols = [
            r["name"] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()
        ]
        if "lot_id" not in booking_cols:
            conn.execute("ALTER TABLE bookings ADD COLUMN lot_id TEXT DEFAULT 'main'")
        event_cols = [
            r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()
        ]
        if "lot_id" not in event_cols:
            conn.execute("ALTER TABLE events ADD COLUMN lot_id TEXT DEFAULT 'main'")
    seed_default_lot()
    print(f"[DB] Tables ready at {DB_PATH}")


def seed_default_lot():
    """Ensure the legacy single lot exists so old installs keep working."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lots(id, name, slot_count) VALUES('main', 'Main Lot', 3)"
        )
        for n in (1, 2, 3):
            conn.execute(
                "INSERT OR IGNORE INTO slots(lot_id, label, kind) VALUES('main', ?, 'standard')",
                (str(n),),
            )


def get_lot(lot_id: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
        return dict(row) if row else None


def list_lots():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM lots ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def create_lot(
    lot_id: str,
    name: str,
    slot_count: int,
    pricing_json: str = "",
    blynk_token: str = "",
):
    if slot_count < 1 or slot_count > 200:
        raise ValueError("slot_count must be between 1 and 200")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO lots(id, name, slot_count, pricing_json, blynk_token) VALUES(?,?,?,?,?)",
            (lot_id, name, slot_count, pricing_json, blynk_token),
        )
        for n in range(1, slot_count + 1):
            conn.execute(
                "INSERT OR IGNORE INTO slots(lot_id, label, kind) VALUES(?, ?, 'standard')",
                (lot_id, str(n)),
            )


def get_lot_slots(lot_id: str):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT label, kind FROM slots WHERE lot_id = ? ORDER BY id", (lot_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_lot_price(lot_id: str, hours: int) -> int:
    """Per-lot pricing from lots.pricing_json, falling back to global PRICES."""
    import json as _json

    from parking_backend.config import PRICES

    lot = get_lot(lot_id)
    if lot and lot.get("pricing_json"):
        try:
            table = {
                int(k): int(v) for k, v in _json.loads(lot["pricing_json"]).items()
            }
            if hours in table:
                return table[hours]
        except (ValueError, TypeError, AttributeError):
            pass
    return PRICES.get(hours, 50)


def log_event(slot1_state, slot2_state, slot3_state, gate_state, event_type, detail="", lot_id="main"):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events(ts,slot1,slot2,slot3,gate,event_type,detail,lot_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                slot1_state,
                slot2_state,
                slot3_state,
                gate_state,
                event_type,
                detail,
                lot_id,
            ),
        )


def log_alert(alert_type, severity, message, emailed=False):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts(ts,alert_type,severity,message,emailed) VALUES(?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                alert_type,
                severity,
                message,
                int(emailed),
            ),
        )
    print(f"[ALERT/{severity.upper()}] {alert_type}: {message}")


# --- Bookings CRUD ---


def add_booking(data: dict):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO bookings(id, lot_id, slot, date, time, dur, name, phone, plate, amount, status, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
                data.get("lot_id", "main"),
                data["slot"],
                data["date"],
                data["time"],
                data["dur"],
                data["name"],
                data["phone"],
                data["plate"],
                data["amount"],
                data["status"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def get_bookings(limit=100, lot_id=None):
    with get_connection() as conn:
        if lot_id:
            rows = conn.execute(
                "SELECT * FROM bookings WHERE lot_id = ? ORDER BY created_at DESC LIMIT ?",
                (lot_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bookings ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_booking_by_id(booking_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        return dict(row) if row else None


def update_booking_status(booking_id: str, status: str) -> bool:
    with get_connection() as conn:
        c = conn.execute(
            "UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id)
        )
        return c.rowcount > 0


def delete_booking(booking_id: str) -> bool:
    with get_connection() as conn:
        c = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        return c.rowcount > 0


# --- Payments ---


def record_payment(
    booking_id: str,
    gateway: str,
    txn_id: str,
    amount_npr: int,
    status: str,
    raw: str = "",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO payments(booking_id, gateway, txn_id, amount_npr, status, raw,
                                    created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (booking_id, gateway, txn_id, amount_npr, status, raw, now, now),
        )


def update_payment_txn(txn_id: str, status: str, raw: str = "") -> bool:
    with get_connection() as conn:
        c = conn.execute(
            "UPDATE payments SET status = ?, raw = ?, updated_at = ? WHERE txn_id = ?",
            (status, raw, datetime.now().isoformat(timespec="seconds"), txn_id),
        )
        return c.rowcount > 0


def get_payment_by_txn(txn_id: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE txn_id = ?", (txn_id,)
        ).fetchone()
        return dict(row) if row else None


def update_payment_status(booking_id: str, status: str, txn_id: str = "") -> bool:
    with get_connection() as conn:
        c = conn.execute(
            "UPDATE bookings SET payment_status = ? WHERE id = ?", (status, booking_id)
        )
        return c.rowcount > 0


def get_active_bookings_for_slots(lot_id="main"):
    """
    Returns a list of per-slot booleans for the lot, based on
    current time falling within any UPCOMING/ACTIVE booking window.
    Defaults to the legacy 'main' lot so old callers keep working.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    lot = get_lot(lot_id) or {"slot_count": 3}
    slot_count = max(1, int(lot.get("slot_count") or 3))

    with get_connection() as conn:
        active_today = conn.execute(
            "SELECT slot, date, time, dur FROM bookings WHERE lot_id = ? AND date = ? AND status IN ('UPCOMING', 'ACTIVE')",
            (
                lot_id,
                today,
            ),
        ).fetchall()

    active = [False] * slot_count
    for b in active_today:
        try:
            start = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
            end = start + timedelta(hours=int(b["dur"]))
            if start <= now < end and 1 <= b["slot"] <= slot_count:
                active[b["slot"] - 1] = True
        except Exception as e:
            print(f"[DB] Skipping bad row: {e}")
    return active
