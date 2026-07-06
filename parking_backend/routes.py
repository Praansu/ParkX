import random
import re
import secrets
import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import parking_backend.database as db
import parking_backend.blynk as blynk
from parking_backend.blynk import state as blynk_state
from parking_backend.config import ANPR_ENABLED, get_price
from parking_backend.ai import agent_chat, check_slot_availability

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []

class BookingRequest(BaseModel):
    slot: int
    date: str
    time: str
    dur: int
    name: str
    phone: str = ""
    plate: str

class SimulateRequest(BaseModel):
    action: str


@router.post("/simulate")
async def simulate(body: SimulateRequest):
    """Override sensor state for demos without ESP32 hardware."""
    blynk.set_simulation(body.action)
    return {"status": "ok", "action": body.action}


@router.get("/status")
async def get_status():
    return {
        **blynk_state,
        "free_slots": blynk_state["slot1"] + blynk_state["slot2"] + blynk_state["slot3"]
    }


# --- Bookings ---

@router.get("/bookings")
async def get_bookings():
    return db.get_bookings()


@router.post("/bookings")
async def create_booking(req: BookingRequest):
    if req.slot not in (1, 2, 3):
        raise HTTPException(400, "Slot must be 1, 2, or 3.")
    if req.dur not in (1, 2, 3, 4, 8):
        raise HTTPException(400, "Duration must be 1, 2, 3, 4, or 8 hours.")

    if not check_slot_availability(req.slot, req.date, req.time, req.dur):
        raise HTTPException(400, f"Slot {req.slot} not available on {req.date} at {req.time} for {req.dur}h.")

    booking = {
        "id": f"BK-{secrets.token_hex(4).upper()}",
        "slot": req.slot,
        "date": req.date,
        "time": req.time,
        "dur": req.dur,
        "name": req.name,
        "phone": req.phone,
        "plate": req.plate.upper(),
        "amount": get_price(req.dur),
        "status": "UPCOMING"
    }

    try:
        db.add_booking(booking)
        blynk.trigger_blynk_resync()
        return {"status": "success", "booking": booking}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str):
    bid = booking_id.strip().upper()
    if not db.get_booking_by_id(bid):
        raise HTTPException(404, f"Booking {bid} not found.")
    try:
        db.update_booking_status(bid, "CANCELLED")
        blynk.trigger_blynk_resync()
        return {"status": "success", "message": f"Booking {bid} cancelled."}
    except Exception as e:
        raise HTTPException(500, str(e))


# --- AI Chat ---

@router.post("/chat")
async def chat(body: ChatMessage):
    if not body.message.strip():
        return {"reply": "Please type a message.", "source": "validation"}
    try:
        return await agent_chat(body.message.strip(), body.history)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"AI error: {e}")


# --- Analytics ---

@router.get("/analytics")
async def analytics():
    today = datetime.now().date().isoformat()

    with db.get_connection() as conn:
        hourly_rows = conn.execute("""
            SELECT strftime('%H', ts) AS hr,
                   AVG(3.0-(slot1+slot2+slot3)) * 100.0 / 3.0 AS occ_pct
            FROM events WHERE date(ts) = ?
            GROUP BY hr ORDER BY hr
        """, (today,)).fetchall()

        daily_rows = conn.execute("""
            SELECT date(ts) AS day, COUNT(*) AS cnt
            FROM events WHERE event_type = 'entry'
              AND date(ts) >= date('now', '-6 days')
            GROUP BY day ORDER BY day
        """).fetchall()

        ut = conn.execute("""
            SELECT AVG(CASE WHEN slot1=0 THEN 100.0 ELSE 0.0 END) AS s1,
                   AVG(CASE WHEN slot2=0 THEN 100.0 ELSE 0.0 END) AS s2,
                   AVG(CASE WHEN slot3=0 THEN 100.0 ELSE 0.0 END) AS s3
            FROM events WHERE date(ts) = ?
        """, (today,)).fetchone()

        entries_today = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type='entry' AND date(ts)=?", (today,)
        ).fetchone()["n"]

        total = conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]

    hourly_map = {r["hr"]: round(r["occ_pct"], 1) for r in hourly_rows}
    hourly = [{"hour": f"{h:02d}", "pct": hourly_map.get(f"{h:02d}", 0)} for h in range(24)]

    daily_map = {r["day"]: r["cnt"] for r in daily_rows}
    labels = ["M", "T", "W", "T", "F", "S", "S"]
    daily = []
    for i in range(6, -1, -1):
        d = (datetime.now().date() - timedelta(days=i)).isoformat()
        daily.append({"date": d, "day": labels[(datetime.now().weekday() - i) % 7], "cnt": daily_map.get(d, 0)})

    return {
        "hourly": hourly,
        "daily": daily,
        "utilisation": {
            "slot1": round(float(ut["s1"] or 0), 1),
            "slot2": round(float(ut["s2"] or 0), 1),
            "slot3": round(float(ut["s3"] or 0), 1)
        },
        "entries_today": entries_today,
        "total_events": total,
        "data_source": "sqlite"
    }


# --- Prediction ---

@router.get("/predict")
async def predict():
    with db.get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
        avgs = conn.execute("""
            SELECT strftime('%H', ts) AS hr,
                   AVG(3.0-(slot1+slot2+slot3)) * 100.0 / 3.0 AS occ_pct
            FROM events GROUP BY hr
        """).fetchall()

    avg_map = {r["hr"]: round(float(r["occ_pct"]), 1) for r in avgs}
    now = datetime.now()
    preds = []
    for i in range(1, 6):
        h = (now.hour + i) % 24
        hh = f"{h:02d}"
        pct = avg_map.get(hh, 0)
        preds.append({
            "time": f"{h:02d}:00",
            "predicted_occupancy_percent": pct,
            "confidence": "high" if hh in avg_map else "low",
            "note": f"Collecting data ({total} events)" if total < 50 else "Based on historical averages"
        })

    return {"predictions": preds, "data_points": total}


# --- Alerts ---

@router.get("/alerts")
async def get_alerts(limit: int = 20):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, ts, alert_type, severity, message, emailed FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
    return {"alerts": [dict(r) for r in rows], "total": total}


# --- ANPR ---

@router.post("/anpr")
@router.get("/anpr")
async def anpr(body: dict = None):
    if ANPR_ENABLED and body and body.get("image"):
        return _scan_plate(body["image"])

    plates = [
        "BA 1 PA 2345", "BA 2 JA 5678", "BA 3 CHA 9012",
        "PA 1 KA 3456", "BA 1 JA 1122", "BA 2 KA 8801",
        "BA 1 NA 7890", "PA 2 CHA 3344",
    ]
    return {
        "plate": random.choice(plates),
        "confidence": round(random.uniform(0.72, 0.95), 2),
        "note": "Simulated plate (Nepal format)",
        "source": "simulation"
    }


# Cache the OCR reader so we don't reload it every time
_ocr_reader = None

def _scan_plate(img_b64):
    global _ocr_reader
    try:
        import io
        import easyocr
        from PIL import Image

        img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")

        if _ocr_reader is None:
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)

        results = _ocr_reader.readtext(img)
        
        # Look for Nepal plate pattern (e.g. BA 1 PA 1234)
        for text, confidence in [(t.upper().strip(), float(c)) for (_, t, c) in results]:
            if re.search(r"[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{4}", text):
                cleaned = re.sub(r"\s+", " ", text)
                return {"plate": cleaned, "confidence": round(confidence, 2),
                        "note": "EasyOCR scan", "source": "ocr"}

        if results:
            best = max(results, key=lambda r: r[2])
            return {"plate": best[1].upper(), "confidence": round(float(best[2]), 2),
                    "note": "No plate pattern found", "source": "ocr_raw"}

        return {"plate": "--", "confidence": 0.0, "note": "No text detected", "source": "ocr_empty"}

    except ImportError:
        return {"plate": "--", "confidence": 0.0, "note": "EasyOCR/Pillow not installed.", "source": "error"}
    except Exception as e:
        return {"plate": "--", "confidence": 0.0, "note": f"OCR Error: {e}", "source": "error"}
