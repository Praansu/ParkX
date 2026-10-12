# ParkX — Startup Plan: Smart Parking for Nepal

> Status: working prototype (ESP32 + FastAPI + dashboard, demoable today via `/simulate`).
> This document turns it into a business: who pays, how much, and what has to be built next.

## The problem (Kathmandu-specific)

- Malls, hospitals, and offices in the Valley run parking with paper chits and
  flat-fee attendants. Drivers circle, owners can't see occupancy, and revenue
  leaks (no record of who parked how long).
- Event venues and commercial buildings have peak-hour chaos with zero
  advance booking. Customers currently solve this with phone calls or luck.
- Existing "smart parking" offerings in Nepal are imported, expensive, and
  sold as hardware — nobody sells the *software layer* (booking + payments +
  analytics) sized for a 20–50 bay lot.

## The product (what ParkX becomes)

A lot-owner dashboard + driver booking page + cheap ESP32 sensor kit:

1. **Driver side:** see free bays live, book a slot, pay online (Khalti/eSewa),
   get entry via plate or booking code. No app install — mobile web.
2. **Owner side:** live occupancy, daily revenue, peak-hour analytics,
   anomaly alerts (bay stuck occupied, sensor offline), booking management.
3. **Hardware kit:** ESP32 + IR bay sensors + ultrasonic entry/exit + servo
   gate + LCD, installed per lot. Backend polls sensor state; dashboard
   refreshes on a 2-second tick (proven sufficient — no WebSocket needed).

What exists today: everything above *except* online payment collection and
multi-lot support (code currently models exactly 3 bays).

## Who pays

| Customer | Why they buy | Entry offer |
|---|---|---|
| Private parking lots (New Road, Putalisadak, Thamel) | Stop revenue leakage, see occupancy | Paid pilot, 1 lot |
| Shopping malls | Peak-hour chaos, customer experience | Monthly SaaS per lot |
| Hospitals (e.g. valley private hospitals) | Visitor parking is a daily complaint | Monthly SaaS per lot |
| Offices / apartments | Reserved + visitor bays, access records | Monthly SaaS per lot |
| Event venues | Match-day/event peaks, advance booking | Per-event fee |

## Pricing (NPR, starting point — validate in pilots)

- Hardware kit per lot (sensors + ESP32 + gate servo + LCD): **cost + install
  margin, one-time**. Keep BOM public inside the repo so quotes stay honest.
- Software: **monthly per lot**, tiered by bay count (e.g. ≤20 bays / 21–50
  bays). Payment collection takes ~1.5–2% gateway fee (Khalti/eSewa standard)
  — price the SaaS to absorb it, don't surcharge drivers.
- Pilot pricing: first lot at hardware cost + nominal SaaS, in exchange for a
  written testimonial and usage data.

## Payments (the critical path)

- **Khalti first:** modern REST API — initiate payment, get `pidx`, verify
  server-to-server before marking a booking PAID. Test keys available from
  the merchant dashboard; self-serve integration in ~a day.
- **eSewa second:** largest user base in Nepal, but HMAC-signed form flow and
  callback-only verification. More work, wider reach.
- **Hard requirement:** both gateways settle only to a **registered company**
  (registration certificate + PAN + bank account + tax clearance). No
  production payments without this paperwork. Test/sandbox works without it.
- Booking payment states to implement: `UNPAID → PENDING → PAID | FAILED |
  REFUNDED`. Never trust client-side success callbacks — always verify
  server-to-server.

## Pilot plan (first paying lot)

1. Pick ONE friendly lot (10–30 bays, owner you can visit weekly).
2. Install kit + run 2 weeks in **shadow mode** (sensors live, attendants still
   in charge) to prove accuracy numbers.
3. Turn on bookings + Khalti test payments for staff/friends.
4. Go live with a banner + QR at entry. Attendant stays as fallback for month 1.
5. Measure: occupancy rate, booking conversion, revenue vs. prior paper records,
   sensor uptime. These four numbers ARE the pitch for lot #2.

## Technical roadmap (maps to code)

- [x] Single-lot system: firmware, backend, dashboard, bookings, chatbot
- [x] **Payments module** — gateway interface + Khalti implementation + test-mode
  simulator; booking `PAID/UNPAID` states (shipped; eSewa live needs merchant creds)
- [ ] **Multi-lot data model** — `lots` + `slots` tables replacing hardcoded 3
  bays; per-lot pricing and dashboards (Phase 3)
- [x] **Accounts & roles** — owner/attendant API keys; operator endpoints guarded
  (shipped; drivers stay keyless)
- [ ] Reduce Blynk dependence — direct MQTT/Wi-Fi reporting as an option for
  lots with reliable internet (later)
- [ ] Nepali-language UI toggle (real adoption driver outside central Kathmandu)

## Risks (honest)

- **Power + internet:** load-shedding-era wiring and flaky ISPs kill cloud-polled
  sensors. Mitigation: local buffering on the ESP32, graceful offline mode.
- **Hardware maintenance:** sensors get dusty, gates get hit. Someone must visit
  lots. Budget a maintenance visit per lot per month.
- **Blynk as a dependency:** fine for pilots; have the direct-reporting path
  (above) before signing lot #5.
- **ANPR is not real yet:** plate endpoint is a stub + optional EasyOCR. Sell
  booking codes first; cameras later.
- **Merchant onboarding time:** company registration + Khalti/eSewa KYC takes
  weeks. Start paperwork before the pilot ends, not after.

## What NOT to build yet

- A driver mobile app (mobile web is enough to validate).
- Dynamic surge pricing (flat NPR rates first; complexity later).
- Multi-city expansion (win 3 lots in Kathmandu first).
