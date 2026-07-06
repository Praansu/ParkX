import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

import httpx

from parking_backend.config import (
    OLLAMA_ACTIVE, OLLAMA_BASE, OLLAMA_MODEL,
    GROQ_ACTIVE, GROQ_API_BASE, GROQ_API_KEY, GROQ_MODEL,
    OLLAMA_TIMEOUT, get_price
)
import parking_backend.database as pdb
import parking_backend.blynk as blynk
from parking_backend.database import get_connection, get_active_bookings_for_slots
from parking_backend.blynk import state as blynk_state

_ollama_available: Optional[bool] = None


def _today():
    return datetime.now().date().isoformat()

def _tomorrow():
    return (datetime.now().date() + timedelta(days=1)).isoformat()

def _now():
    return datetime.now().strftime("%H:%M")


def replace_fuzzy_dates(text: str) -> str:
    """Convert 'tomorrow', 'next monday' etc. to YYYY-MM-DD."""
    now = datetime.now()
    text = re.sub(r"\btoday\b", _today(), text, flags=re.IGNORECASE)
    text = re.sub(r"\btomorrow\b", _tomorrow(), text, flags=re.IGNORECASE)
    text = re.sub(r"\bday after tomorrow\b",
                  (now + timedelta(days=2)).date().isoformat(),
                  text, flags=re.IGNORECASE)

    days = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,
            "friday":4,"saturday":5,"sunday":6}
    def _next(m):
        t = days[m.group(1).lower()]
        a = (t - now.weekday() - 1) % 7 + 1
        return (now + timedelta(days=a)).date().isoformat()
    text = re.sub(r"\bnext\s+(mon|tue|wed|thu|fri|sat|sun)[^\s]*", _next, text, flags=re.IGNORECASE)
    return text


def check_slot_availability(slot: int, date_str: str, time_str: str, dur: int) -> bool:
    try:
        start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        end = start + timedelta(hours=dur)
    except ValueError:
        return False
    with get_connection() as conn:
        cnt = conn.execute("""
            SELECT COUNT(*) n FROM bookings
            WHERE slot = ? AND status = 'UPCOMING'
              AND datetime(date || ' ' || time) < datetime(?, ?, '+' || dur || ' hours')
              AND datetime(?, ?, '+' || ? || ' hours') > datetime(date || ' ' || time)
        """, (slot, date_str, time_str, date_str, time_str, dur)).fetchone()
    return cnt["n"] == 0


def find_available_slots(date_str: str, time_str: str, dur: int) -> list[int]:
    free = []
    for s in (1, 2, 3):
        if check_slot_availability(s, date_str, time_str, dur):
            free.append(s)
    return free


SYSTEM_PROMPT = """You are the chatbot for ParkX, a smart parking system (3 slots).
Help users check availability, book spots, cancel, or see history.

Current status: {status_summary}

Rules:
- Be friendly and conversational.
- Always check availability before confirming.
- Collect: slot, date, time, duration, name, plate.
- Dates are YYYY-MM-DD. Times are HH:MM 24h.
- Duration: 1, 2, 3, 4, or 8 hours.

To fulfill requests, use exactly:
  CALL: function_name(param1, param2, ...)

Available: check_availability(slot, date, time, duration)
           find_available(date, time, duration)
           book_slot(slot, date, time, duration, name, plate)
           cancel_booking(booking_id)
           get_bookings()
           current_status()"""


def run_ai_command(call: str) -> str:
    m = re.match(r"CALL:\s*(\w+)\((.+)\)", call.strip())
    if not m:
        return "Error: could not parse."
    fn = m.group(1)
    args = [a.strip().strip("'\"") for a in m.group(2).split(",")]

    try:
        if fn == "check_availability":
            s, d, t, dur = int(args[0]), args[1], args[2], int(args[3])
            return f"Slot {s} available: {check_slot_availability(s, d, t, dur)}"

        elif fn == "find_available":
            d, t, dur = args[0], args[1], int(args[2])
            return f"Available slots: {find_available_slots(d, t, dur)}"

        elif fn == "book_slot":
            s, d, t, dur = int(args[0]), args[1], args[2], int(args[3])
            name, plate = args[4], args[5]
            if not check_slot_availability(s, d, t, dur):
                return f"Slot {s} not available on {d} at {t} for {dur}h."
            bid = f"BK-{secrets.token_hex(4).upper()}"
            pdb.add_booking({
                "id": bid, "slot": s, "date": d, "time": t, "dur": dur,
                "name": name, "plate": plate.upper(), "amount": get_price(dur), "status": "UPCOMING"
            })
            blynk.trigger_blynk_resync()
            return f"Booked {bid}: Slot {s} on {d} at {t} ({dur}h). Rs {get_price(dur)}."

        elif fn == "cancel_booking":
            bid = args[0].strip().upper()
            if not pdb.get_booking_by_id(bid):
                return f"Booking {bid} not found."
            pdb.update_booking_status(bid, "CANCELLED")
            blynk.trigger_blynk_resync()
            return f"Cancelled {bid}."

        elif fn == "get_bookings":
            bks = pdb.get_bookings()
            return json.dumps(bks, indent=2) if bks else "No bookings."

        elif fn == "current_status":
            s = blynk_state
            f = s["slot1"] + s["slot2"] + s["slot3"]
            return f"Slots: {s['slot1']}/{s['slot2']}/{s['slot3']} (1=empty) | Free: {f}/3 | Online: {s['online']}"

        return f"Unknown: {fn}"

    except Exception as e:
        return f"Error in {fn}: {e}"


def is_ollama_ready() -> bool:
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2.0)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            _ollama_available = any(OLLAMA_MODEL in m for m in models)
        else:
            _ollama_available = False
    except Exception:
        _ollama_available = False
    return _ollama_available


async def _ask_ollama(messages):
    if not OLLAMA_ACTIVE:
        return None
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as c:
            r = await c.post(f"{OLLAMA_BASE}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": messages, "stream": False})
            if r.status_code == 200:
                return r.json().get("message", {}).get("content", "")
            print(f"[OLLAMA] HTTP {r.status_code}")
    except Exception as e:
        print(f"[OLLAMA ERROR] {e}")
    return None


async def _ask_groq(messages):
    if not GROQ_ACTIVE:
        return None
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{GROQ_API_BASE}/chat/completions",
                json={"model": GROQ_MODEL, "messages": messages, "max_tokens": 500},
                headers=headers)
            if r.status_code == 200:
                return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"[GROQ] HTTP {r.status_code}")
    except Exception as e:
        print(f"[GROQ ERROR] {e}")
    return None


def summarize() -> str:
    s = blynk_state
    free = s["slot1"] + s["slot2"] + s["slot3"]
    parts = [f"slot{i}={ 'Empty' if s[f'slot{i}'] == 1 else 'Occupied' }" for i in range(1, 4)]
    return f"{' | '.join(parts)} | Free: {free}/3 | Online: {s['online']} | Gate: {'Open' if s['gate'] else 'Closed'}"


async def agent_chat(msg: str, history: list[dict]) -> dict:
    msg = replace_fuzzy_dates(msg)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(status_summary=summarize())}]
    for h in history[-6:]:
        msgs.append({"role": "user" if h.get("role") == "user" else "assistant", "content": h.get("content", "")})
    msgs.append({"role": "user", "content": msg})

    reply, source = None, "none"

    if is_ollama_ready():
        reply = await _ask_ollama(msgs)
        if reply: source = "ollama"

    if not reply:
        reply = await _ask_groq(msgs)
        if reply: source = "groq"

    if not reply:
        source = "rule"
        reply = _fallback(msg)

    if "CALL:" in reply:
        try:
            calls = re.findall(r"CALL:\s*\w+\([^)]+\)", reply)
            results = [run_ai_command(c) for c in calls]
            joined = "\n".join(results)
            msgs.append({"role": "assistant", "content": reply})
            msgs.append({"role": "user", "content": f"Function results:\n{joined}\nRespond nicely."})

            if source == "ollama":
                reply = await _ask_ollama(msgs) or joined
            elif source == "groq":
                reply = await _ask_groq(msgs) or joined
            else:
                reply = joined
        except Exception as e:
            reply = f"Error: {e}"

    reply = re.sub(r"CALL:\s*\w+\([^)]+\)", "", reply or "").strip()
    return {"reply": reply or "I didn't understand that. Try asking about booking or availability.", "source": source}


def _fallback(msg: str) -> str:
    m = msg.lower()
    if re.search(r"\b(hi|hello|hey|namaste)\b", m):
        free = blynk_state["slot1"] + blynk_state["slot2"] + blynk_state["slot3"]
        if free > 0:
            return f"Namaste! {free}/3 spots free right now. Want to book?"
        return "Namaste! All full right now, but I can book ahead."

    if re.search(r"\b(how many|free|available|status|open|empty)\b", m):
        parts = [f"Slot {i}: {'Empty' if blynk_state[f'slot{i}'] == 1 else 'Occupied'}" for i in range(1, 4)]
        free = blynk_state["slot1"] + blynk_state["slot2"] + blynk_state["slot3"]
        return f"{' | '.join(parts)} — {free}/3 free."

    slot = re.search(r"(?:slot|spot|space)\s*(\d)", m)
    if slot:
        n = int(slot.group(1))
        if 1 <= n <= 3:
            state = "Empty" if blynk_state[f"slot{n}"] == 1 else "Occupied"
            return f"Slot {n} is {state} right now."

    if re.search(r"\b(book|reserve|park)\b", m):
        free = find_available_slots(_today(), _now(), 1)
        if free:
            return f"Slots {free} free now. Tell me date, time, duration, name, and plate!"
        return "Tell me date, time, duration, name, and plate."

    if re.search(r"\b(cancel)\b", m):
        bid = re.search(r"(BK[-]?\w+)", m.upper())
        if bid:
            b = pdb.get_booking_by_id(bid.group(1))
            if b:
                pdb.update_booking_status(bid.group(1), "CANCELLED")
                blynk.trigger_blynk_resync()
                return f"Cancelled {bid.group(1)}."
            return "Not found."
        return "Need the booking ID (e.g. BK-1001)."

    if re.search(r"\b(my bookings|history)\b", m):
        bks = pdb.get_bookings()
        if not bks:
            return "No reservations yet."
        return "\n".join(f"  {b['id']}: Slot {b['slot']} {b['date']} {b['time']} {b['dur']}h — {b['status']}" for b in bks)

    return "I can help with: availability, booking, cancel, history. What do you need?"
