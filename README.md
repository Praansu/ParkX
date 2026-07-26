# ParkX

I got tired of circling parking lots. So I built this — ESP32 + ultrasonic sensors → Blynk IoT → FastAPI backend → real-time dashboard. Green means free, red means taken.

Has a booking system and a chatbot. The chatbot works _most_ of the time.

[![CI](https://img.shields.io/github/actions/workflow/status/Praansu/ParkX/ci.yml?style=flat-square)](https://github.com/Praansu/ParkX/actions)

### tech

FastAPI (Python), ESP32, ultrasonic sensors, Blynk, Chart.js, SQLite

### run it

```bash
pip install -r requirements.txt
# set your Blynk token in backend.py
python backend.py
```

### what I learned

ESP32 firmware is finicky. One wrong pin = hour of debugging. Real-time WebSockets are harder than they look. IoT + web is way more moving parts than expected but way more satisfying when it works.

### layout

```
backend.py              — FastAPI server
parking_backend/        — AI, Blynk, database, routes
frontend/               — dashboard files
smart_parking_v2/       — ESP32 firmware
```
