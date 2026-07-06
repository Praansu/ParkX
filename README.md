# ParkX — Smart Parking System

> IoT-based parking management system with real-time monitoring, AI chatbot, booking system, and anomaly detection. Built with ESP32, FastAPI, and vanilla JS.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![ESP32](https://img.shields.io/badge/ESP32-Arduino-E7352C?logo=espressif)](https://www.espressif.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Overview

ParkX is a complete smart parking solution with three layers:

| Layer | Tech | What it does |
|-------|------|-------------|
| **Hardware** | ESP32 + sensors | Detects vehicles, controls gate/traffic light, sends data to Blynk |
| **Backend** | FastAPI + SQLite | Polls Blynk every 2s, REST API, AI chatbot, anomaly detection, email alerts |
| **Frontend** | Vanilla JS + Chart.js | Real-time dashboard with live map, booking, analytics, alerts |

### Features

- **Live monitoring** — slot occupancy, gate status, traffic light, LCD emulator
- **Smart booking** — reserve slots via form or AI chatbot, time-slot conflict detection
- **AI assistant** — Ollama (local) → Groq (cloud) → rule-based fallback
- **Analytics** — hourly/daily charts, per-slot utilization, occupancy predictions
- **Anomaly detection** — long-occupancy alerts, facility-full warnings, hardware offline detection
- **ANPR** — number plate recognition via EasyOCR (optional)
- **Simulation mode** — run the full demo without any physical hardware

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
python backend.py
```

Open http://localhost:8000. The dashboard works in simulation mode without any hardware — use the **Simulation Controls** buttons to test vehicle entry/exit.

### With real hardware

1. Flash `smart_parking_v2/smart_parking_v2.ino` to your ESP32 (copy `config.h.example` to `config.h` first)
2. Set your Blynk token and WiFi credentials in `config.h`
3. Connect IR sensors, ultrasonic sensor, servo, LEDs, and LCD per the pin definitions in the firmware

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│   ESP32     │────▶│   Blynk      │◀────│   FastAPI    │
│  (sensors)  │     │   Cloud      │     │   Backend    │
│  (actuators)│     │              │     │  (Python)    │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                                        ┌───────▼───────┐
                                        │   Dashboard   │
                                        │  (vanilla JS) │
                                        └───────────────┘
```

The ESP32 publishes sensor data to Blynk virtual pins. The backend polls Blynk every 2 seconds, stores events in SQLite, and exposes a REST API. The frontend polls the backend and updates the UI in real time.

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Live sensor data |
| GET | `/api/bookings` | All reservations |
| POST | `/api/bookings` | Create booking |
| POST | `/api/bookings/{id}/cancel` | Cancel booking |
| POST | `/api/chat` | AI chatbot |
| GET | `/api/analytics` | Usage statistics |
| GET | `/api/predict` | Occupancy forecast |
| GET | `/api/alerts` | System warnings |
| GET/POST | `/api/anpr` | Plate recognition |
| POST | `/api/simulate` | Hardware simulation |

---

## Project structure

```
backend.py                 # Entry point
requirements.txt           # Python dependencies
.env.example               # Config template (copy to .env)
knowledge_base.txt        # AI knowledge base

parking_backend/
├── config.py              # Settings from environment
├── main.py                # FastAPI app + lifespan
├── database.py            # SQLite operations
├── blynk.py               # Blynk poller + anomaly detection
├── routes.py              # API endpoints
└── ai.py                  # AI chatbot (Ollama/Groq/fallback)

frontend/
├── index.html             # Dashboard HTML
├── style.css              # Dark theme styles
└── app.js                 # Real-time UI logic

smart_parking_v2/
├── config.h.example       # ESP32 config template
└── smart_parking_v2.ino   # ESP32 firmware
```

---

## Tech stack

- **Backend:** Python, FastAPI, uvicorn, httpx, SQLite, python-dotenv
- **Frontend:** Vanilla JavaScript, Chart.js, FontAwesome
- **Hardware:** ESP32, HC-SR04 (ultrasonic), IR sensors, SG90 servo, 20x4 I2C LCD, traffic LEDs
- **Cloud:** Blynk IoT platform
- **AI:** Ollama (llama3.2), Groq API, rule-based fallback
- **Optional:** EasyOCR, Pillow (for ANPR)

---
