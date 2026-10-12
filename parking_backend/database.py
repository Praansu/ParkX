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
    print(f"[DB] Tables ready at {DB_PATH}")


def log_event(slot1_state, slot2_state, slot3_state, gate_state, event_type, detail=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events(ts,slot1,slot2,slot3,gate,event_type,detail) VALUES(?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                slot1_state,
                slot2_state,
                slot3_state,
                gate_state,
                event_type,
                detail,
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
            """INSERT INTO bookings(id, slot, date, time, dur, name, phone, plate, amount, status, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"],
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


def get_bookings(limit=100):
    with get_connection() as conn:
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


def get_active_bookings_for_slots():
    """
    Returns [slot1_active, slot2_active, slot3_active] based on
    current time falling within any UPCOMING/ACTIVE booking window.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        active_today = conn.execute(
            "SELECT slot, date, time, dur FROM bookings WHERE date = ? AND status IN ('UPCOMING', 'ACTIVE')",
            (today,),
        ).fetchall()

    active = [False, False, False]
    for b in active_today:
        try:
            start = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
            end = start + timedelta(hours=int(b["dur"]))
            if start <= now < end and 1 <= b["slot"] <= 3:
                active[b["slot"] - 1] = True
        except Exception as e:
            print(f"[DB] Skipping bad row: {e}")
    return active
