# ParkX — Smart Parking Dashboard

I built this because I got tired of circling parking lots looking for a spot. Then I thought — wait, I'm a CS student, I should be able to fix this. So I wired up an ESP32 with ultrasonic sensors, hooked it to a dashboard, and ParkX was born.

**Notable late-night debugging sessions:** 3 (and counting).

## What it does

- Ultrasonic sensors (connected to ESP32) detect if a parking slot is occupied
- Data flows through Blynk IoT cloud to a FastAPI backend
- A web dashboard shows real-time slot status — green = free, red = taken
- Has a basic booking system and an experimental chatbot (still working on making it useful)

## Tech stuff

| Layer | What I used |
|-------|-------------|
| Backend | FastAPI (Python) |
| Hardware | ESP32 + ultrasonic sensors |
| IoT | Blynk Cloud |
| Frontend | HTML, CSS, JavaScript, Chart.js |
| Database | SQLite |

## What I learned (the hard way)

- ESP32 firmware is finicky. One wrong pin assignment and you spend an hour debugging.
- Real-time data with WebSockets is not as straightforward as tutorials make it seem.
- Chart.js is great until you try to do something slightly unusual.
- IoT + web == way more moving parts than I expected. But also way more satisfying when it works.

## How to run it yourself

```bash
pip install -r requirements.txt
# Set your Blynk token in backend.py
python backend.py
# Open the dashboard URL in your browser
```

## Project layout

```
backend.py              — Main FastAPI server
parking_backend/        — Backend modules (AI, Blynk, database, routes)
frontend/               — Dashboard HTML/CSS/JS
smart_parking_v2/       — ESP32 Arduino firmware
```

## License

MIT — go ahead, fork it, break it, fix it.
