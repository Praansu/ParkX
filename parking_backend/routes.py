import json
import random
import re
import secrets
import base64
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import parking_backend.database as db
import parking_backend.blynk as blynk
from parking_backend.auth import require_attendant, require_owner
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
async def simulate(body: SimulateRequest, role: str = Depends(require_owner)):
    """Override sensor state for demos without ESP32 hardware. Owner only —
    flipping live sensor state is an operator action."""
    blynk.set_simulation(body.action)
    return {"status": "ok", "action": body.action}


@router.get("/status")
async def get_status():
    return {
        **blynk_state,
        "free_slots": blynk_state["slot1"]
        + blynk_state["slot2"]
        + blynk_state["slot3"],
    }


# --- Bookings ---


@router.get("/bookings")
async def get_bookings(role: str = Depends(require_attendant)):
    return db.get_bookings()


@router.post("/bookings")
async def create_booking(req: BookingRequest):
    if req.slot not in (1, 2, 3):
        raise HTTPException(400, "Slot must be 1, 2, or 3.")
    if req.dur not in (1, 2, 3, 4, 8):
        raise HTTPException(400, "Duration must be 1, 2, 3, 4, or 8 hours.")

    if not check_slot_availability(req.slot, req.date, req.time, req.dur):
        raise HTTPException(
            400,
            f"Slot {req.slot} not available on {req.date} at {req.time} for {req.dur}h.",
        )

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
        "status": "UPCOMING",
        "payment_status": "UNPAID",
    }

    try:
        db.add_booking(booking)
        blynk.trigger_blynk_resync()
        return {"status": "success", "booking": booking}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(booking_id: str, role: str = Depends(require_attendant)):
    bid = booking_id.strip().upper()
    if not db.get_booking_by_id(bid):
        raise HTTPException(404, f"Booking {bid} not found.")
    try:
        db.update_booking_status(bid, "CANCELLED")
        blynk.trigger_blynk_resync()
        return {"status": "success", "message": f"Booking {bid} cancelled."}
    except Exception as e:
        raise HTTPException(500, str(e))


# --- Payments ---


class PaymentInit(BaseModel):
    booking_id: str
    gateway: str = ""
    return_url: str = ""
    success_url: str = ""
    failure_url: str = ""


def _gateway_or_400(name: str = ""):
    from parking_backend import payments as paymod

    return paymod.get_gateway(name)


@router.post("/payments/initiate")
async def payments_initiate(body: PaymentInit):
    """Start a payment for a booking. Moves payment_status UNPAID -> PENDING.
    In test mode (no gateway keys) this uses the simulator — no real money."""
    from parking_backend import payments as paymod

    bid = body.booking_id.strip().upper()
    booking = db.get_booking_by_id(bid)
    if not booking:
        raise HTTPException(404, f"Booking {bid} not found.")
    gw = _gateway_or_400(body.gateway)
    try:
        if gw.name == "khalti":
            res = gw.initiate(bid, int(booking["amount"]), return_url=body.return_url)
        elif gw.name == "esewa":
            res = gw.initiate(
                bid,
                int(booking["amount"]),
                success_url=body.success_url,
                failure_url=body.failure_url,
            )
        else:
            res = gw.initiate(bid, int(booking["amount"]))
    except Exception as e:
        raise HTTPException(502, f"Gateway error: {e}")
    db.record_payment(
        bid, gw.name, res["txn_id"], int(booking["amount"]), "PENDING", ""
    )
    try:
        paymod.set_payment_status(bid, "PENDING", res["txn_id"])
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": "pending", "gateway": gw.name, **res}


@router.get("/payments/status/{txn_id}")
async def payments_status(txn_id: str):
    """Server-side verification poll. The ONLY path that flips a booking to
    PAID — client redirects are never trusted."""
    from parking_backend import payments as paymod

    rec = db.get_payment_by_txn(txn_id)
    if not rec:
        raise HTTPException(404, f"Unknown transaction {txn_id}.")
    gw = _gateway_or_400(rec["gateway"])
    try:
        res = gw.verify(txn_id)
    except Exception as e:
        raise HTTPException(502, f"Gateway error: {e}")
    if res["status"] != rec["status"]:
        db.update_payment_txn(txn_id, res["status"], json.dumps(res["raw"])[:4000])
        try:
            paymod.set_payment_status(rec["booking_id"], res["status"], txn_id)
        except ValueError:
            pass  # terminal states are sticky; gateway truth stays in payments table
    return {"txn_id": txn_id, "status": res["status"], "gateway": rec["gateway"]}


@router.post("/payments/esewa/callback")
async def esewa_callback(body: dict):
    """eSewa redirects here (Base64 payload in `data`). PAID is granted only
    on a valid HMAC signature + COMPLETE status."""
    from parking_backend import config as cfg
    from parking_backend import payments as paymod

    data = body
    if isinstance(body.get("data"), str):
        import base64 as b64mod

        try:
            data = json.loads(b64mod.b64decode(body["data"]).decode())
        except Exception:
            raise HTTPException(400, "Undecodable callback payload.")
    try:
        gw = paymod.EsewaGateway(
            cfg.ESEWA_MERCHANT_CODE, cfg.ESEWA_SECRET_KEY, sandbox=cfg.ESEWA_SANDBOX
        )
    except ValueError:
        raise HTTPException(400, "eSewa is not configured on this server.")
    res = gw.verify_callback(data if isinstance(data, dict) else {})
    txn_uuid = str((data if isinstance(data, dict) else {}).get("transaction_uuid", ""))
    rec = db.get_payment_by_txn(txn_uuid) if txn_uuid else None
    if not rec:
        raise HTTPException(404, "No matching payment for this callback.")
    db.update_payment_txn(txn_uuid, res["status"], json.dumps(res["raw"])[:4000])
    if res["status"] == "PAID":
        try:
            paymod.set_payment_status(rec["booking_id"], "PAID", txn_uuid)
        except ValueError:
            pass
    return {"txn_id": txn_uuid, "status": res["status"]}


@router.post("/payments/test/settle/{txn_id}")
async def payments_test_settle(txn_id: str, role: str = Depends(require_owner)):
    """Test-mode only: flip a simulated payment to PAID. 404s in live mode."""
    from parking_backend.config import PAYMENTS_MODE
    from parking_backend import payments as paymod

    if PAYMENTS_MODE == "live":
        raise HTTPException(404, "Not available in live mode.")
    try:
        res = paymod.TestGateway.settle(txn_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    db.update_payment_txn(txn_id, "PAID", "")
    rec = db.get_payment_by_txn(txn_id)
    if rec:
        try:
            paymod.set_payment_status(rec["booking_id"], "PAID", txn_id)
        except ValueError:
            pass
    return res


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
        hourly_rows = conn.execute(
            """
            SELECT strftime('%H', ts) AS hr,
                   AVG(3.0-(slot1+slot2+slot3)) * 100.0 / 3.0 AS occ_pct
            FROM events WHERE date(ts) = ?
            GROUP BY hr ORDER BY hr
        """,
            (today,),
        ).fetchall()

        daily_rows = conn.execute("""
            SELECT date(ts) AS day, COUNT(*) AS cnt
            FROM events WHERE event_type = 'entry'
              AND date(ts) >= date('now', '-6 days')
            GROUP BY day ORDER BY day
        """).fetchall()

        ut = conn.execute(
            """
            SELECT AVG(CASE WHEN slot1=0 THEN 100.0 ELSE 0.0 END) AS s1,
                   AVG(CASE WHEN slot2=0 THEN 100.0 ELSE 0.0 END) AS s2,
                   AVG(CASE WHEN slot3=0 THEN 100.0 ELSE 0.0 END) AS s3
            FROM events WHERE date(ts) = ?
        """,
            (today,),
        ).fetchone()

        entries_today = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type='entry' AND date(ts)=?",
            (today,),
        ).fetchone()["n"]

        total = conn.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]

    hourly_map = {r["hr"]: round(r["occ_pct"], 1) for r in hourly_rows}
    hourly = [
        {"hour": f"{h:02d}", "pct": hourly_map.get(f"{h:02d}", 0)} for h in range(24)
    ]

    daily_map = {r["day"]: r["cnt"] for r in daily_rows}
    labels = ["M", "T", "W", "T", "F", "S", "S"]
    daily = []
    for i in range(6, -1, -1):
        d = (datetime.now().date() - timedelta(days=i)).isoformat()
        daily.append(
            {
                "date": d,
                "day": labels[(datetime.now().weekday() - i) % 7],
                "cnt": daily_map.get(d, 0),
            }
        )

    return {
        "hourly": hourly,
        "daily": daily,
        "utilisation": {
            "slot1": round(float(ut["s1"] or 0), 1),
            "slot2": round(float(ut["s2"] or 0), 1),
            "slot3": round(float(ut["s3"] or 0), 1),
        },
        "entries_today": entries_today,
        "total_events": total,
        "data_source": "sqlite",
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
        preds.append(
            {
                "time": f"{h:02d}:00",
                "predicted_occupancy_percent": pct,
                "confidence": "high" if hh in avg_map else "low",
                "note": f"Collecting data ({total} events)"
                if total < 50
                else "Based on historical averages",
            }
        )

    return {"predictions": preds, "data_points": total}


# --- Alerts ---


@router.get("/alerts")
async def get_alerts(limit: int = 20, role: str = Depends(require_attendant)):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, ts, alert_type, severity, message, emailed FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
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
        "BA 1 PA 2345",
        "BA 2 JA 5678",
        "BA 3 CHA 9012",
        "PA 1 KA 3456",
        "BA 1 JA 1122",
        "BA 2 KA 8801",
        "BA 1 NA 7890",
        "PA 2 CHA 3344",
    ]
    return {
        "plate": random.choice(plates),
        "confidence": round(random.uniform(0.72, 0.95), 2),
        "note": "Simulated plate (Nepal format)",
        "source": "simulation",
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
        for text, confidence in [
            (t.upper().strip(), float(c)) for (_, t, c) in results
        ]:
            if re.search(r"[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{4}", text):
                cleaned = re.sub(r"\s+", " ", text)
                return {
                    "plate": cleaned,
                    "confidence": round(confidence, 2),
                    "note": "EasyOCR scan",
                    "source": "ocr",
                }

        if results:
            best = max(results, key=lambda r: r[2])
            return {
                "plate": best[1].upper(),
                "confidence": round(float(best[2]), 2),
                "note": "No plate pattern found",
                "source": "ocr_raw",
            }

        return {
            "plate": "--",
            "confidence": 0.0,
            "note": "No text detected",
            "source": "ocr_empty",
        }

    except ImportError:
        return {
            "plate": "--",
            "confidence": 0.0,
            "note": "EasyOCR/Pillow not installed.",
            "source": "error",
        }
    except Exception as e:
        return {
            "plate": "--",
            "confidence": 0.0,
            "note": f"OCR Error: {e}",
            "source": "error",
        }
