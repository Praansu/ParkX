# ParkX Setup

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                    # add your Blynk token
cp smart_parking_v2\config.h.example smart_parking_v2\config.h  # for ESP32
python backend.py
```

Open http://localhost:8000 in your browser.

## LLM setup

**Option A — Ollama (recommended)**
```bash
ollama pull llama3.2:3b
ollama serve
```

**Option B — Groq (cloud)**
Set `GROQ_API_KEY` in `.env` and flip `GROQ_ACTIVE=true`.

## ESP32 firmware

Flash `smart_parking_v2/smart_parking_v2.ino` to your ESP32.
Make sure `config.h` has the right Blynk token and WiFi credentials.
The token in `config.h` must match `BLYNK_TOKEN` in `.env`.

## Email alerts

Requires a Gmail App Password. Set these in `.env`:
```
ALERT_EMAIL_FROM=yourname@gmail.com
ALERT_EMAIL_PASS=xxxx xxxx xxxx xxxx
ALERT_EMAIL_TO=owner@gmail.com
```

## ANPR

For real number plate recognition, install EasyOCR:
```bash
pip install easyocr pillow
```
Then set `ANPR_ENABLED = True` in `parking_backend/config.py`.
Without this, the ANPR button returns simulated Nepal-format plates.

## Project structure

```
├── backend.py
├── requirements.txt
├── .env.example
├── coursework_text.txt          # AI knowledge base
├── parking_backend/
│   ├── config.py
│   ├── main.py
│   ├── database.py
│   ├── blynk.py
│   ├── routes.py
│   └── ai.py
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── smart_parking_v2/
    ├── config.h.example
    └── smart_parking_v2.ino
```
