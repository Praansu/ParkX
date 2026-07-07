# ParkX — Smart Parking Dashboard

A web dashboard for monitoring parking slot availability in real time. Built as a learning project to explore IoT, backend development, and real-time data.

## What It Does
- Reads sensor data from an ESP32 microcontroller connected to ultrasonic sensors
- Sends data to the cloud using Blynk IoT platform
- Displays real-time parking slot status on a web dashboard
- Includes a basic booking system and chatbot (experimental)

## What I Learned
- How to write Arduino firmware for ESP32
- How to build a REST API with FastAPI
- How to integrate IoT devices with a web backend
- How to create a real-time dashboard with Chart.js
- Database design with SQLite

## Tech Stack
- **Backend:** FastAPI (Python)
- **Hardware:** ESP32, ultrasonic sensors
- **IoT:** Blynk Cloud
- **Frontend:** HTML, CSS, JavaScript, Chart.js
- **Database:** SQLite

## How to Run
1. Install dependencies: pip install -r requirements.txt
2. Configure your Blynk token in backend.py
3. Run: python backend.py
4. Open the dashboard in your browser

## Project Structure
backend.py — Main FastAPI server
parking_backend/ — Backend modules (AI, Blynk, database, routes)
frontend/ — Web dashboard files
smart_parking_v2/ — ESP32 Arduino firmware
