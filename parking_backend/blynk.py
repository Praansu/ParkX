import asyncio
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import httpx

from parking_backend.config import (
    BLYNK_TOKEN, BLYNK_BASE, POLL_INTERVAL, LOT_ID,
    ALERT_EMAIL_FROM, ALERT_EMAIL_PASS, ALERT_EMAIL_TO,
    ANOMALY_SLOT_HOURS, ANOMALY_FULL_MINUTES, ANOMALY_OFFLINE_MINS,
    ANOMALY_CHECK_INTERVAL
)
from parking_backend.database import (
    log_event, log_alert, get_active_bookings_for_slots,
    list_lots, get_lot,
)

DEFAULT_LOT_ID = "main"


def _default_lot_id() -> str:
    """Lot the legacy single-lot callers (frontend, ai.py) keep seeing."""
    return LOT_ID or DEFAULT_LOT_ID


# Latest sensor snapshot of the DEFAULT lot — the dashboard and ai.py read
# this via /api/status. Kept as a plain global so old imports keep working.
state = {
    "slot1": 1, "slot2": 1, "slot3": 1,
    "gate": 0,
    "distance": 0.0,
    "online": False,
    "last_update": None
}

# Per-lot snapshots: lot_id -> {slots, slot_count, gate, distance,
# online, last_update}. The default lot's snapshot mirrors `state` above.
lot_states: dict = {}

# Per-lot anomaly/sync trackers, created lazily by _trackers_for().
_trackers: dict = {}


def _new_trackers(slot_count: int) -> dict:
    return {
        "prev": {f"slot{i + 1}": -1 for i in range(slot_count)} | {"gate": -1},
        "slot_since": {f"slot{i + 1}": None for i in range(slot_count)},
        "full_since": None,
        "offline_since": None,
        "last_synced": [-1] * slot_count,
        "alert_cooldown": {},
    }


def _trackers_for(lot_id: str, slot_count: int) -> dict:
    tr = _trackers.get(lot_id)
    if tr is None or len(tr["last_synced"]) != slot_count:
        tr = _new_trackers(slot_count)
        _trackers[lot_id] = tr
    return tr


def _lot_token(lot_id: str):
    """Blynk token for a lot: its own token, else the legacy env token
    when this is the legacy lot, else None (lot is skipped by the poller)."""
    lot = get_lot(lot_id)
    if lot and lot.get("blynk_token"):
        return lot["blynk_token"]
    if lot_id == (LOT_ID or DEFAULT_LOT_ID) and BLYNK_TOKEN != "your_blynk_token_here":
        return BLYNK_TOKEN
    return None


def _lot_slot_count(lot_id: str) -> int:
    lot = get_lot(lot_id)
    try:
        return max(1, int((lot or {}).get("slot_count") or 3))
    except (TypeError, ValueError):
        return 3

# Overrides real Blynk data when simulating hardware events
sim_override = {}


def set_simulation(action: str):
    global sim_override
    tr = _trackers_for(_default_lot_id(), 3)
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
        tr["prev"] = {"slot1": -1, "slot2": -1, "slot3": -1, "gate": -1}


def trigger_blynk_resync():
    for tr in _trackers.values():
        tr["last_synced"] = [-1] * len(tr["last_synced"])


def _can_alert(tr: dict, key: str, cooldown_min: int = 120) -> bool:
    now = datetime.now()
    last = tr["alert_cooldown"].get(key)
    if last and (now - last).total_seconds() < cooldown_min * 60:
        return False
    tr["alert_cooldown"][key] = now
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


async def sync_bookings(client: httpx.AsyncClient, lot_id: str = "main", token: str = BLYNK_TOKEN):
    tr = _trackers_for(lot_id, _lot_slot_count(lot_id))
    try:
        active = get_active_bookings_for_slots(lot_id)
        for i, a in enumerate(active):
            val = 1 if a else 0
            if tr["last_synced"][i] != val:
                pin = f"v{i+6}"
                print(f"[BLYNK:{lot_id}] Syncing {pin} = {val}")
                await client.get(f"{BLYNK_BASE}/update?token={token}&{pin}={val}")
                tr["last_synced"][i] = val
    except Exception as e:
        print(f"[BLYNK SYNC ERROR] {e}")


def _detect_event(tr: dict, slots: list, gate: int, free: int):
    prev = tr["prev"]
    if all(v == -1 for v in prev.values() if isinstance(v, int)):
        return "startup"

    keys = [f"slot{i + 1}" for i in range(len(slots))]
    changed = any(slots[i] != prev.get(keys[i]) for i in range(len(slots)))
    changed = changed or (gate != prev.get("gate"))

    if not changed:
        return None

    prev_free = sum(v for k, v in prev.items() if k.startswith("slot") and v != -1)

    if gate == 1 and prev.get("gate") == 0:
        return "gate_open"
    if gate == 0 and prev.get("gate") == 1:
        return "gate_close"
    if free < prev_free:
        return "entry"
    if free > prev_free:
        return "exit"
    if free == 0:
        return "full"
    return "state_change"




def _snapshot(slots: list, gate: int, dist: float, online: bool) -> dict:
    return {
        "slots": list(slots),
        "slot_count": len(slots),
        "gate": gate,
        "distance": dist,
        "online": online,
        "last_update": datetime.now().isoformat(timespec="seconds"),
    }


def _publish_default_snapshot(lot_id: str):
    """Mirror the default lot into the legacy global `state` dict."""
    snap = lot_states.get(lot_id)
    if not snap:
        return
    slots = snap["slots"][:3] + [1] * max(0, 3 - len(snap["slots"]))
    state.update(
        slot1=slots[0], slot2=slots[1], slot3=slots[2],
        gate=snap["gate"], distance=snap["distance"], online=snap["online"],
        last_update=snap["last_update"],
    )


async def _poll_once(client: httpx.AsyncClient, lot_id: str, token: str):
    n = _lot_slot_count(lot_id)
    tr = _trackers_for(lot_id, n)
    try:
        await sync_bookings(client, lot_id, token)

        resp = await client.get(f"{BLYNK_BASE}/isHardwareConnected?token={token}")
        if resp.text.strip() != "true":
            lot_states[lot_id] = _snapshot([1] * n, 0, 0.0, False)
            if lot_id == _default_lot_id():
                _publish_default_snapshot(lot_id)
            return

        data = (await client.get(f"{BLYNK_BASE}/getAll?token={token}")).json()

        slots = [int(data.get(f"v{i}", 1)) for i in range(n)]
        gate = int(data.get("v5", 0))
        dist = float(data.get("v4") or 0)

        if lot_id == _default_lot_id() and sim_override:
            for i in range(n):
                slots[i] = sim_override.get(f"slot{i + 1}", slots[i])
            gate = sim_override.get("gate", gate)
            dist = sim_override.get("distance", dist)

        lot_states[lot_id] = _snapshot(slots, gate, dist, True)
        if lot_id == _default_lot_id():
            _publish_default_snapshot(lot_id)

        free = sum(slots)
        ev = _detect_event(tr, slots, gate, free)
        if ev:
            cols = (slots[:3] + [1, 1, 1])[:3]
            log_event(
                cols[0], cols[1], cols[2], gate, ev,
                f"lot={lot_id} free={free}/{n} dist={dist:.0f}cm",
                lot_id=lot_id,
            )
            for i in range(n):
                tr["prev"][f"slot{i + 1}"] = slots[i]
            tr["prev"]["gate"] = gate

    except Exception as e:
        snap = _snapshot([1] * n, 0, 0.0, False)
        snap["last_update"] = lot_states.get(lot_id, {}).get("last_update")
        lot_states[lot_id] = snap
        if lot_id == _default_lot_id():
            _publish_default_snapshot(lot_id)
        print(f"[POLLER ERROR:{lot_id}] {e}")


async def poll_loop():
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            try:
                lots = list_lots() if _has_lots_table() else []
                if not lots:
                    lots = [{"id": _default_lot_id()}]
                for lot in lots:
                    lot_id = lot["id"]
                    token = _lot_token(lot_id)
                    if not token:
                        continue
                    await _poll_once(client, lot_id, token)
            except Exception as e:
                print(f"[POLLER ERROR] {e}")
            await asyncio.sleep(POLL_INTERVAL)


def _has_lots_table() -> bool:
    try:
        list_lots()
        return True
    except Exception:
        return False
async def anomaly_loop():
    await asyncio.sleep(10)
    while True:
        try:
            now = datetime.now()
            for lot_id, snap in list(lot_states.items()):
                n = snap.get("slot_count", 3)
                tr = _trackers_for(lot_id, n)
                slots = snap.get("slots", [1] * n)

                for i in range(n):
                    key = f"slot{i + 1}"
                    if slots[i] == 0:
                        if tr["slot_since"][key] is None:
                            tr["slot_since"][key] = now
                    else:
                        tr["slot_since"][key] = None

                for key, since in tr["slot_since"].items():
                    num = key.replace("slot", "")
                    if since is not None:
                        hrs = (now - since).total_seconds() / 3600
                        if hrs >= ANOMALY_SLOT_HOURS and _can_alert(tr, f"{lot_id}:long_{key}", 180):
                            msg = (f"[{lot_id}] Slot {num} occupied for {hrs:.1f}h -- "
                                   f"possible unpaid or stuck sensor.")
                            emailed = send_alert_email(f"Slot {num} occupied {hrs:.1f}h", msg)
                            log_alert("long_occupied", "warning", msg, emailed)

                free = sum(slots)
                if free == 0:
                    if tr["full_since"] is None:
                        tr["full_since"] = now
                    else:
                        mins = (now - tr["full_since"]).total_seconds() / 60
                        if mins >= ANOMALY_FULL_MINUTES and _can_alert(tr, f"{lot_id}:facility_full", 120):
                            msg = (f"[{lot_id}] All slots full for {mins:.0f}min -- "
                                   f"consider redirecting traffic.")
                            emailed = send_alert_email("Parking full", msg)
                            log_alert("facility_full", "warning", msg, emailed)
                else:
                    tr["full_since"] = None

                if not snap.get("online"):
                    if tr["offline_since"] is None:
                        tr["offline_since"] = now
                    else:
                        mins = (now - tr["offline_since"]).total_seconds() / 60
                        if mins >= ANOMALY_OFFLINE_MINS and _can_alert(tr, f"{lot_id}:esp32_offline", 60):
                            msg = f"[{lot_id}] ESP32 offline for {mins:.0f}min -- check power and WiFi."
                            emailed = send_alert_email("ESP32 offline", msg)
                            log_alert("hardware_offline", "critical", msg, emailed)
                else:
                    tr["offline_since"] = None

        except Exception as e:
            print(f"[ANOMALY ERROR] {e}")

        await asyncio.sleep(ANOMALY_CHECK_INTERVAL)