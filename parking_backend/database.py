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
        """)
    print(f"[DB] Tables ready at {DB_PATH}")


def log_event(slot1_state, slot2_state, slot3_state, gate_state, event_type, detail=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events(ts,slot1,slot2,slot3,gate,event_type,detail) VALUES(?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), slot1_state, slot2_state, slot3_state, gate_state, event_type, detail)
        )


def log_alert(alert_type, severity, message, emailed=False):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts(ts,alert_type,severity,message,emailed) VALUES(?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), alert_type, severity, message, int(emailed))
        )
    print(f"[ALERT/{severity.upper()}] {alert_type}: {message}")


# --- Bookings CRUD ---

def add_booking(data: dict):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO bookings(id, slot, date, time, dur, name, phone, plate, amount, status, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (data["id"], data["slot"], data["date"], data["time"], data["dur"],
             data["name"], data["phone"], data["plate"], data["amount"],
             data["status"], datetime.now().isoformat(timespec="seconds"))
        )


def get_bookings(limit=100):
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_booking_by_id(booking_id: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else None


def update_booking_status(booking_id: str, status: str) -> bool:
    with get_connection() as conn:
        c = conn.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
        return c.rowcount > 0


def delete_booking(booking_id: str) -> bool:
    with get_connection() as conn:
        c = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
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
            (today,)
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
