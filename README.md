# ParkX

Smart parking across three layers: ESP32 sensor firmware, a FastAPI backend, and a dashboard served by the same backend. I got tired of circling parking lots, and I wanted to feel what an IoT project with real moving parts is like.

[![CI](https://img.shields.io/github/actions/workflow/status/Praansu/ParkX/ci.yml?style=flat-square)](https://github.com/Praansu/ParkX/actions)

## How it works

```
[IR slot sensors + ultrasonic entry/exit]   ESP32 firmware (non-blocking loop)
        │  Blynk cloud, virtual pins V0–V8, pushed every 2s
        ▼
[FastAPI backend]   polls Blynk, stores events/bookings/alerts in SQLite,
                    runs anomaly checks, serves the dashboard + JSON API
        │
        ▼
[Dashboard]   one page, polls /status every 2s. Green means free, red means taken.
```

No WebSockets — plain polling. The dashboard refreshes bay state, bookings, analytics and alerts on a 2-second tick, which is plenty for parked cars.

## Hardware (ESP32 firmware, `smart_parking_v2/`)

- 3 IR sensors for bay occupancy, one ultrasonic sensor at entry, one IR at exit
- Servo gate (tuned open/close angles in the sketch), traffic LEDs, 20x4 I2C LCD
- Publishes to Blynk: V0–V2 slot states, V3 free count, V4 distance, V5 gate, V6–V8 booking flags
- Non-blocking state machine — sensor reads every 400ms, cloud push every 2s

To flash it: copy `config.h.example` to `config.h`, put in your WiFi credentials and Blynk token, open the `.ino` in Arduino IDE with the ESP32 core installed.

## Backend (`parking_backend/`)

FastAPI app (`main.py`, lifespan-managed). Two background loops start with the server: a Blynk poll loop and an anomaly loop (flags a bay stuck occupied 6+ hours, a lot full 60+ minutes, or a sensor offline 5+ minutes). SQLite tables: `events`, `alerts`, `bookings`.

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/status` | GET | Live bay state, free count, gate |
| `/simulate` | POST | Fake a sensor reading — demo without hardware |
| `/bookings` | GET / POST | List / create bookings (NPR pricing: 1h 50, 2h 90, 3h 130, 4h 160, 8h 280) |
| `/bookings/{id}/cancel` | POST | Cancel a booking |
| `/chat` | POST | Parking chatbot (see below) |
| `/analytics` | GET | Occupancy aggregates for the dashboard charts |
| `/predict` | GET | Demand outlook served to the dashboard |
| `/alerts` | GET | Anomaly alerts, latest first (operator key) |
| `/anpr` | GET / POST | Number-plate endpoint — disabled stub unless an ESP32-CAM is attached |

Operator endpoints (`/bookings` list, cancel, `/simulate`, `/alerts`) need an
`X-API-Key` header. Roles: owner (everything) vs attendant (bookings + alerts).
Set `ADMIN_API_KEY` once, restart, then remove it — the key hash lives in the DB.

The chatbot (`ai.py`) tries local Ollama first (`llama3.2:3b`), falls back to Groq (`llama-3.1-8b-instant`). It parses fuzzy dates ("tomorrow", "next Monday") into real dates, checks live bay state and existing bookings before answering, and quotes prices. It works well for booking questions; anything outside parking, it will happily make up — that's on the TODO list to constrain.

## Payments (Khalti / eSewa / test mode)

Bookings carry a `payment_status` driven by a strict state machine
(`UNPAID → PENDING → PAID | FAILED`, `PAID → REFUNDED`). A booking is never
marked PAID from a client callback — only server-side verification flips it.

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/payments/initiate` | POST | Start a payment for a booking → returns gateway pay URL |
| `/payments/status/{txn}` | GET | Server-side verification poll (the only path to PAID) |
| `/payments/esewa/callback` | POST | eSewa signed redirect handler (HMAC-verified) |
| `/payments/test/settle/{txn}` | POST | Test-mode only, owner key: flip a simulated payment to PAID |

Without gateway keys everything runs on the built-in simulator: create a
booking, initiate payment, settle it, watch the status flip — no real money,
no secrets. Khalti (REST: initiate → `pidx` → lookup) and eSewa (HMAC-signed
form + signed callback) plug in via the same gateway interface once you hold
merchant credentials (registered company + PAN). See `parking_backend/payments.py`
and `STARTUP.md` for the full picture. Tests live in `tests/` (`pytest -q`).

## Run it

```bash
# 1. Backend
cp .env.example .env        # fill in BLYNK_TOKEN at minimum
pip install -r requirements.txt
python backend.py           # dashboard at http://localhost:8000

# 2. No hardware? Use the simulator
# open the dashboard and hit "Simulate", or:
curl -X POST http://localhost:8000/simulate -H "Content-Type: application/json" -d '{"slot": 1}'
```

Optional extras in `.env`: `OLLAMA_*` / `GROQ_*` for the chatbot, Gmail app-password settings for email alerts, `DB_PATH`, `PORT`.

## Limitations

- ANPR is a stub (`ANPR_ENABLED = False`, OCR deps commented out of requirements). Real plate recognition needs an ESP32-CAM plus `easyocr`/`pillow` on the server.
- Email alerts need a Gmail app password; without one they're silently skipped.
- The chatbot has no guardrails outside the parking domain.
- One lot, three bays. Multi-lot support would mean a `lots` table and scoped queries — the schema isn't there yet.

## Layout

```
backend.py              — launcher (loads .env, starts uvicorn)
parking_backend/
  main.py               — FastAPI app, lifespan loops, serves frontend/
  routes.py             — all API endpoints
  blynk.py              — Blynk polling + anomaly detection
  ai.py                 — chatbot (Ollama → Groq fallback)
  payments.py           — gateway interface (Khalti / eSewa / test) + state machine
  auth.py               — operator API keys (owner / attendant roles)
  database.py           — SQLite: events, alerts, bookings, payments, operators
  config.py             — env-driven settings
tests/                  — pytest: payments state machine, gateways, auth
frontend/               — dashboard (index.html, app.js, style.css)
smart_parking_v2/       — ESP32 firmware (.ino + config.h.example)
```

## What I learned

ESP32 firmware is finicky — one wrong pin is an hour of debugging. Polling beats WebSockets when the data changes this slowly; I started wanting sockets and dropped them once I did the math (2-second car-park state doesn't need a persistent connection). IoT + web is far more moving parts than a pure software project, and far more satisfying when the gate actually opens.
