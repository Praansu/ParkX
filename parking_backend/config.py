import os

# Blynk — reads sensor data from the cloud
BLYNK_TOKEN = os.getenv("BLYNK_TOKEN", "your_blynk_token_here")
BLYNK_BASE = os.getenv("BLYNK_BASE", "https://blynk.cloud/external/api")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))

# AI backends — tries Ollama first, falls back to Groq
OLLAMA_ACTIVE = os.getenv("OLLAMA_ACTIVE", "true").lower() == "true"
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "30"))

GROQ_ACTIVE = os.getenv("GROQ_ACTIVE", "false").lower() == "true"
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Database & server
DB_PATH = os.getenv("DB_PATH", "parking.db")
PORT = int(os.getenv("PORT", "8000"))

# Email alerts (optional, needs Gmail App Password)
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_PASS = os.getenv("ALERT_EMAIL_PASS", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

# Parking prices in NPR
PRICES = {1: 50, 2: 90, 3: 130, 4: 160, 8: 280}

def get_price(hours: int) -> int:
    return PRICES.get(hours, 50)

# Anomaly detection thresholds
ANOMALY_SLOT_HOURS = 6
ANOMALY_FULL_MINUTES = 60
ANOMALY_OFFLINE_MINS = 5
ANOMALY_CHECK_INTERVAL = 60

# ANPR — flip to True only with an ESP32-CAM
ANPR_ENABLED = False
