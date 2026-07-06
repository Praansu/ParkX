/*
 * ESP32 firmware v2.2 — non-blocking state machine
 * 
 * Reads IR sensors (slots), ultrasonic (entry), IR (exit).
 * Controls servo gate, traffic LEDs, 20x4 I2C LCD.
 * Sends data to Blynk cloud every 2s.
 *
 * Virtual pins:
 *   V0-V2 = slot states (1=empty, 0=occupied)
 *   V3 = free count, V4 = distance, V5 = gate
 *   V6-V8 = booking flags (set by backend)
 */

#include "config.h"

char ssid[] = WIFI_SSID;
char pass[] = WIFI_PASS;

#include <WiFi.h>
#include <BlynkSimpleEsp32.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// Pin definitions
#define ENTRY_TRIG   27
#define ENTRY_ECHO   26
#define EXIT_IR      12
#define IR1          25
#define IR2          33
#define IR3          32

#define RED_LED      18
#define YELLOW_LED   19
#define GREEN_LED    17
#define SERVO_PIN    13

// Thresholds
#define ENTRY_THRESHOLD   10    // cm
#define GATE_OPEN_TIME  4000    // ms
#define LOOP_INTERVAL    400    // sensor read interval

// Servo — tweak these if the gate doesn't close/open right
#define SERVO_CLOSED_ANGLE   20
#define SERVO_OPEN_ANGLE    90
#define SERVO_MIN_PULSE    544
#define SERVO_MAX_PULSE   2400


Servo             gateServo;
LiquidCrystal_I2C lcd(0x27, 20, 4);
BlynkTimer        timer;


// Gate state machine
enum GatePhase { PHASE_IDLE, PHASE_ENTRY, PHASE_EXIT, PHASE_DENIED };
GatePhase    gatePhase      = PHASE_IDLE;
unsigned long phaseStart    = 0;
bool          gateIsOpen    = false;
long          g_entryDist   = 0;

bool lastEntryTriggered = false;
bool lastExitTriggered  = false;
unsigned long lastSensorRead = 0;

// LCD flicker prevention
int _lastLCD_s1 = -1, _lastLCD_s2 = -1, _lastLCD_s3 = -1;


void sendSensorDataToBlynk() {
  int s1 = (digitalRead(IR1) == HIGH) ? 1 : 0;
  int s2 = (digitalRead(IR2) == HIGH) ? 1 : 0;
  int s3 = (digitalRead(IR3) == HIGH) ? 1 : 0;
  int gate = gateIsOpen ? 1 : 0;
  int free = s1 + s2 + s3;

  Blynk.virtualWrite(V0, s1);
  Blynk.virtualWrite(V1, s2);
  Blynk.virtualWrite(V2, s3);
  Blynk.virtualWrite(V3, free);
  Blynk.virtualWrite(V4, (int)g_entryDist);
  Blynk.virtualWrite(V5, gate);

  Serial.println("[BLYNK] S1:" + String(s1) + " S2:" + String(s2) + " S3:" + String(s3) +
                 " Free:" + String(free) + " Dist:" + String(g_entryDist) + "cm Gate:" + String(gate));
}


long getEntryDistance() {
  digitalWrite(ENTRY_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(ENTRY_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(ENTRY_TRIG, LOW);
  long dur = pulseIn(ENTRY_ECHO, HIGH, 26000);
  return dur * 0.034 / 2;
}


int countFreeSlots() {
  int c = 0;
  if (digitalRead(IR1) == HIGH) c++;
  if (digitalRead(IR2) == HIGH) c++;
  if (digitalRead(IR3) == HIGH) c++;
  return c;
}


void setTrafficLight(String state) {
  if (state == "STOP") {
    digitalWrite(RED_LED, HIGH); digitalWrite(YELLOW_LED, LOW); digitalWrite(GREEN_LED, LOW);
  } else if (state == "GO") {
    digitalWrite(RED_LED, LOW); digitalWrite(YELLOW_LED, LOW); digitalWrite(GREEN_LED, HIGH);
  } else if (state == "WARNING") {
    digitalWrite(RED_LED, LOW); digitalWrite(YELLOW_LED, HIGH); digitalWrite(GREEN_LED, LOW);
  } else {
    digitalWrite(RED_LED, LOW); digitalWrite(YELLOW_LED, LOW); digitalWrite(GREEN_LED, LOW);
  }
}


void updateLCD() {
  int free = countFreeSlots();
  bool s1 = (digitalRead(IR1) == HIGH);
  bool s2 = (digitalRead(IR2) == HIGH);
  bool s3 = (digitalRead(IR3) == HIGH);

  if (s1 == _lastLCD_s1 && s2 == _lastLCD_s2 && s3 == _lastLCD_s3) return;
  _lastLCD_s1 = s1; _lastLCD_s2 = s2; _lastLCD_s3 = s3;

  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("TOTAL FREE: "); lcd.print(free); lcd.print(" / 3");
  lcd.setCursor(0, 1); lcd.print("SLOT 1: "); lcd.print(s1 ? "EMPTY   " : "OCCUPIED");
  lcd.setCursor(0, 2); lcd.print("SLOT 2: "); lcd.print(s2 ? "EMPTY   " : "OCCUPIED");
  lcd.setCursor(0, 3); lcd.print("SLOT 3: "); lcd.print(s3 ? "EMPTY   " : "OCCUPIED");
}


// Advance the gate/light sequence based on timers
void handleGateState(unsigned long now) {
  switch (gatePhase) {
    case PHASE_IDLE:
      break;

    case PHASE_ENTRY:
    case PHASE_EXIT: {
      unsigned long elapsed = now - phaseStart;
      if (elapsed < 500) {
        setTrafficLight("WARNING");
      } else if (elapsed < (500 + GATE_OPEN_TIME)) {
        setTrafficLight("GO");
      } else if (elapsed < (500 + GATE_OPEN_TIME + 500)) {
        setTrafficLight("WARNING");
        gateServo.write(SERVO_CLOSED_ANGLE);
        gateIsOpen = false;
        Blynk.virtualWrite(V5, 0);
      } else {
        setTrafficLight("STOP");
        gatePhase = PHASE_IDLE;
        lcd.clear();
        updateLCD();
      }
      break;
    }

    case PHASE_DENIED:
      if (now - phaseStart >= 2500) {
        gatePhase = PHASE_IDLE;
        lcd.clear();
        updateLCD();
      }
      break;
  }
}


void startGateSequence(bool isEntry, const char* line1, const char* line2) {
  gatePhase = isEntry ? PHASE_ENTRY : PHASE_EXIT;
  phaseStart = millis();

  lcd.clear();
  lcd.setCursor(0, 1); lcd.print(line1);
  lcd.setCursor(0, 2); lcd.print(line2);

  gateServo.write(SERVO_OPEN_ANGLE);
  gateIsOpen = true;
  Blynk.virtualWrite(V5, 1);
  setTrafficLight("WARNING");

  Serial.print(" [ACTION] ");
  Serial.print(isEntry ? "ENTRY" : "EXIT");
  Serial.println(" - gate opening");
}


void setup() {
  Serial.begin(115200);
  Serial.println("\n=== SMART PARKING v2.2 ===");

  pinMode(ENTRY_TRIG, OUTPUT); pinMode(ENTRY_ECHO, INPUT);
  pinMode(EXIT_IR, INPUT); pinMode(IR1, INPUT); pinMode(IR2, INPUT); pinMode(IR3, INPUT);
  pinMode(RED_LED, OUTPUT); pinMode(YELLOW_LED, OUTPUT); pinMode(GREEN_LED, OUTPUT);

  gateServo.attach(SERVO_PIN, SERVO_MIN_PULSE, SERVO_MAX_PULSE);
  gateServo.write(SERVO_CLOSED_ANGLE);
  setTrafficLight("STOP");

  lcd.init(); lcd.backlight();
  lcd.setCursor(0, 0); lcd.print("Smart Parking");
  lcd.setCursor(0, 1); lcd.print("CC4003NI Islington");
  lcd.setCursor(0, 2); lcd.print("Connecting WiFi...");

  Blynk.begin(BLYNK_AUTH_TOKEN, ssid, pass);
  Serial.println("[WIFI] IP: " + WiFi.localIP().toString());

  timer.setInterval(2000L, sendSensorDataToBlynk);

  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("   SYSTEM READY    ");
  lcd.setCursor(0, 1); lcd.print("WiFi OK | Blynk OK ");
  lcd.setCursor(0, 2); lcd.print("Gate: CLOSED       ");
  lcd.setCursor(0, 3); lcd.print("Traffic: STOP      ");
  delay(2000);
  updateLCD();
}


void loop() {
  Blynk.run();
  timer.run();

  unsigned long now = millis();
  handleGateState(now);

  if (now - lastSensorRead >= LOOP_INTERVAL) {
    lastSensorRead = now;

    long dist = getEntryDistance();
    g_entryDist = dist;
    bool exitDetect = (digitalRead(EXIT_IR) == LOW);
    int free = countFreeSlots();

    if (gatePhase == PHASE_IDLE) updateLCD();

    // Entry trigger
    bool entryNow = (dist > 0 && dist < ENTRY_THRESHOLD);
    if (entryNow && !lastEntryTriggered && gatePhase == PHASE_IDLE) {
      if (free > 0) {
        startGateSequence(true, "  ACCESS GRANTED  ", " Welcome! Drive in");
      } else {
        gatePhase = PHASE_DENIED;
        phaseStart = millis();
        lcd.clear();
        lcd.setCursor(0, 0); lcd.print("!!!! PARKING FULL !!!!");
        lcd.setCursor(0, 1); lcd.print("   ENTRY  DENIED    ");
        lcd.setCursor(0, 2); lcd.print(" No slots available ");
        lcd.setCursor(0, 3); lcd.print("  Please try later  ");
      }
    }
    lastEntryTriggered = entryNow;

    // Exit trigger
    if (exitDetect && !lastExitTriggered && gatePhase == PHASE_IDLE) {
      startGateSequence(false, "   SAFE TRAVELS!   ", "   Goodbye!        ");
    }
    lastExitTriggered = exitDetect;
  }
}


BLYNK_WRITE(V6) { Serial.println("[BLYNK] V6 (Slot 1 booking) = " + String(param.asInt())); }
BLYNK_WRITE(V7) { Serial.println("[BLYNK] V7 (Slot 2 booking) = " + String(param.asInt())); }
BLYNK_WRITE(V8) { Serial.println("[BLYNK] V8 (Slot 3 booking) = " + String(param.asInt())); }
