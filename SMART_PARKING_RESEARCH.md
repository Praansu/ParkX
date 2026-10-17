# Smart Parking Systems — Industry Research

Research compiled for ParkX to understand what real-world smart parking systems include, what ParkX already has, and what gaps need closing.

## Industry-Standard Components

### 1. Sensors & Detection
- **Bay sensors**: IR, ultrasonic, or magnetic for per-slot occupancy detection
- **LPR/ANPR cameras**: License plate recognition for ticketless entry/exit and enforcement
- **Entry/exit sensors**: Ultrasonic or IR loops to detect vehicle movement

### 2. Payments & Revenue
- **Multiple gateways**: Khalti, eSewa, IME Pay in Nepal; Stripe/PayPal internationally
- **Dynamic pricing**: Surge rates during peak hours, discounts for off-peak
- **Subscription passes**: Monthly/weekly unlimited access for regular parkers
- **Pay-on-foot**: Central payment stations before exit (common in airports/malls)

### 3. Reservations
- **Pre-booking**: Reserve a slot ahead of time with TTL holds (15-30 min grace)
- **No-show detection**: Release slot if vehicle doesn't arrive within grace period
- **QR/code entry**: Booking confirmation code scanned at gate

### 4. Management Platform
- **Multi-tenant**: Single dashboard managing multiple lots with per-lot settings
- **Role-based access**: Owner, attendant, auditor with different permissions
- **Revenue reporting**: Daily/weekly/monthly reconciliation, export to accounting
- **Analytics**: Occupancy trends, peak hours, revenue per slot

### 5. User-Facing Apps
- **Driver app**: Find lots, see live availability, book, pay, get directions
- **Attendant app**: View occupancy, manual overrides, violation logging
- **Web fallback**: Mobile-responsive web for users who won't install an app

### 6. Operational Standards
- **PCI compliance**: Payment data never touches merchant servers
- **Offline resilience**: Local SQLite + sync when connectivity returns
- **Hardware-agnostic**: API supports multiple sensor/camera vendors

## ParkX vs. Industry Standards

| Feature | ParkX Status | Industry Standard | Gap |
|---------|-------------|-------------------|-----|
| Bay sensors | ✅ ESP32 + IR | ✅ | None |
| Booking system | ✅ With NPR pricing | ✅ | None |
| Payments | ✅ Khalti/eSewa/test mode | ✅ | None |
| Multi-lot | ✅ Backend done | ✅ | None |
| Dynamic pricing | ❌ Flat rates only | ✅ | Medium priority |
| LPR/ANPR | ⚠️ Stub + EasyOCR | ✅ | High priority for ticketless |
| Mobile driver app | ❌ Web-only | ✅ | Medium priority |
| Admin roles | ✅ Owner/attendant | ✅ | None |
| Analytics | ✅ Occupancy/revenue | ✅ | None |
| Offline mode | ❌ Cloud-dependent | ✅ | High priority for Nepal |
| Subscription passes | ❌ Not implemented | ✅ | Low priority initially |

## Key Takeaways for ParkX

1. **Offline mode is critical in Nepal**: Load-shedding and flaky ISPs mean cloud-polled sensors will fail. ESP32 should buffer events locally and sync when connectivity returns.

2. **LPR is the next big feature**: Ticketless entry via plate recognition is what airports and malls use. EasyOCR stub exists; production needs a proper LPR pipeline.

3. **Dynamic pricing adds revenue**: Flat NPR rates are simple but leave money on the table during peak hours. A rules engine (time-based multipliers) is the next pricing feature.

4. **Mobile web is enough for now**: A driver-facing mobile web app (PWA) covers the reservation + payment flow without app store overhead.

5. **Subscription passes for offices**: Monthly unlimited passes for office buildings are a recurring revenue stream that flat per-booking pricing doesn't capture.

## References
- A Reference Architecture for Smart Car Parking Management Systems (Systems, 2025)
- Unified IoT Framework for Smart Parking Management (IEEE ISAECT, 2025)
- NCTCOG Parking Technology Guide (2025)
- EPS Global Smart Parking Solutions (2025)
- NIX United Parking System Case Study (2025)
- MLI PARCS RFP — Quad Cities International Airport (2026)
- Rezcomm Parking Module
- NoctoPark Core
- SpaceGenius Platform Features
