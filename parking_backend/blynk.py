import asyncio
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import httpx

from parking_backend.config import (
    BLYNK_TOKEN, BLYNK_BASE, POLL_INTERVAL,
    ALERT_EMAIL_FROM, ALERT_EMAIL_PASS, ALERT_EMAIL_TO,
    ANOMALY_SLOT_HOURS, ANOMALY_FULL_MINUTES, ANOMALY_OFFLINE_MINS,
    ANOMALY_CHECK_INTERVAL
)
from parking_backend.database import (
    log_event, log_alert, get_active_bookings_for_slots
)


# Holds the latest sensor snapshot — the dashboard reads this via /api/status
state = {
    "slot1": 1, "slot2": 1, "slot3": 1,
    "gate": 0,
    "distance": 0.0,
    "online": False,
    "last_update": None
}

_prev = {"slot1": -1, "slot2": -1, "slot3": -1, "gate": -1}

# Anomaly tracking
_slot_since = {"slot1": None, "slot2": None, "slot3": None}
_full_since = None
_offline_since = None

_alert_cooldown = {}
_last_synced = [-1, -1, -1]  # V6, V7, V8

# Overrides real Blynk data when simulating hardware events
sim_override = {}


def set_simulation(action: str):
    global sim_override, _prev
    if action == "entry":
        sim_override = {"distance": 8, "gate": 1}
    elif action == "exit":
        sim_override = {"gate": 1}
    elif action == "gate_off":
        sim_override = {}
    elif action == "fill":
        sim_override = {"slot1": 0, "slot2": 0, "slot3": 0, "distance": 150}
    elif action == "reset":
        sim_override = {}
        _prev = {"slot1": -1, "slot2": -1, "slot3": -1, "gate": -1}


def trigger_blynk_resync():
    global _last_synced
    _last_synced = [-1, -1, -1]


def _can_alert(key: str, cooldown_min: int = 120) -> bool:
    now = datetime.now()
    last = _alert_cooldown.get(key)
    if last and (now - last).total_seconds() < cooldown_min * 60:
        return False
    _alert_cooldown[key] = now
    return True


def send_alert_email(subject: str, body: str) -> bool:
    if not all([ALERT_EMAIL_FROM, ALERT_EMAIL_PASS, ALERT_EMAIL_TO]):
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[ParkX Alert] {subject}"
        msg["From"] = ALERT_EMAIL_FROM
        msg["To"] = ALERT_EMAIL_TO
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASS)
            smtp.send_message(msg)
        print(f"[EMAIL] {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


async def sync_bookings(client: httpx.AsyncClient):
    global _last_synced
    try:
        active = get_active_bookings_for_slots()
        for i, a in enumerate(active):
            val = 1 if a else 0
            if _last_synced[i] != val:
                pin = f"v{i+6}"
                print(f"[BLYNK] Syncing {pin} = {val}")
                await client.get(f"{BLYNK_BASE}/update?token={BLYNK_TOKEN}&{pin}={val}")
                _last_synced[i] = val
    except Exception as e:
        print(f"[BLYNK SYNC ERROR] {e}")


def _detect_event(s1, s2, s3, gate, free):
    if _prev["slot1"] == -1:
        return "startup"

    changed = any([
        s1 != _prev["slot1"], s2 != _prev["slot2"],
        s3 != _prev["slot3"], gate != _prev["gate"]
    ])
    if not changed:
        return None

    prev_free = _prev["slot1"] + _prev["slot2"] + _prev["slot3"]

    if gate == 1 and _prev["gate"] == 0:
        return "gate_open"
    if gate == 0 and _prev["gate"] == 1:
        return "gate_close"
    if free < prev_free:
        return "entry"
    if free > prev_free:
        return "exit"
    if free == 0:
        return "full"
    return "state_change"


async def poll_loop():
    global state, _prev
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            try:
                await sync_bookings(client)

                resp = await client.get(f"{BLYNK_BASE}/isHardwareConnected?token={BLYNK_TOKEN}")
                if resp.text.strip() != "true":
                    state["online"] = False
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                data = (await client.get(f"{BLYNK_BASE}/getAll?token={BLYNK_TOKEN}")).json()

                s1 = int(data.get("v0", 1))
                s2 = int(data.get("v1", 1))
                s3 = int(data.get("v2", 1))
                gate = int(data.get("v5", 0))
                dist = float(data.get("v4") or 0)

                if sim_override:
                    s1 = sim_override.get("slot1", s1)
                    s2 = sim_override.get("slot2", s2)
                    s3 = sim_override.get("slot3", s3)
                    gate = sim_override.get("gate", gate)
                    dist = sim_override.get("distance", dist)

                state.update(
                    slot1=s1, slot2=s2, slot3=s3,
                    gate=gate, distance=dist, online=True,
                    last_update=datetime.now().isoformat(timespec="seconds")
                )

                free = s1 + s2 + s3
                ev = _detect_event(s1, s2, s3, gate, free)
                if ev:
                    log_event(s1, s2, s3, gate, ev, f"free={free}/3 dist={dist:.0f}cm")
                    _prev.update(slot1=s1, slot2=s2, slot3=s3, gate=gate)

            except Exception as e:
                state["online"] = False
                print(f"[POLLER ERROR] {e}")

            await asyncio.sleep(POLL_INTERVAL)


async def anomaly_loop():
    global _slot_since, _full_since, _offline_since

    await asyncio.sleep(10)
    while True:
        try:
            now = datetime.now()
            s = state

            for slot in ["slot1", "slot2", "slot3"]:
                if s[slot] == 0:
                    if _slot_since[slot] is None:
                        _slot_since[slot] = now
                else:
                    _slot_since[slot] = None

            for key, since in _slot_since.items():
                num = key[-1]
                if since is not None:
                    hrs = (now - since).total_seconds() / 3600
                    if hrs >= ANOMALY_SLOT_HOURS and _can_alert(f"long_{key}", 180):
                        msg = f"Slot {num} occupied for {hrs:.1f}h — possible unpaid or stuck sensor."
                        emailed = send_alert_email(f"Slot {num} occupied {hrs:.1f}h", msg)
                        log_alert("long_occupied", "warning", msg, emailed)

            free = s["slot1"] + s["slot2"] + s["slot3"]
            if free == 0:
                if _full_since is None:
                    _full_since = now
                else:
                    mins = (now - _full_since).total_seconds() / 60
                    if mins >= ANOMALY_FULL_MINUTES and _can_alert("facility_full", 120):
                        msg = f"All slots full for {mins:.0f}min — consider redirecting traffic."
                        emailed = send_alert_email("Parking full", msg)
                        log_alert("facility_full", "warning", msg, emailed)
            else:
                _full_since = None

            if not s["online"]:
                if _offline_since is None:
                    _offline_since = now
                else:
                    mins = (now - _offline_since).total_seconds() / 60
                    if mins >= ANOMALY_OFFLINE_MINS and _can_alert("esp32_offline", 60):
                        msg = f"ESP32 offline for {mins:.0f}min — check power and WiFi."
                        emailed = send_alert_email("ESP32 offline", msg)
                        log_alert("hardware_offline", "critical", msg, emailed)
            else:
                _offline_since = None

        except Exception as e:
            print(f"[ANOMALY ERROR] {e}")

        await asyncio.sleep(ANOMALY_CHECK_INTERVAL)
