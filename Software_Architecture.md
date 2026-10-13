# Frost-IoE: Software Architecture & System Workflow Guide

---

## 1. High-Level Architecture Diagram

```text
 ┌────────────────────────────────────────────────────────┐
 │            INSIDE THE COLD ROOM / WAREHOUSE            │
 │                                                        │
 │   [Corner 1]      [Corner 2]      [Corner 3]      [Corner 4]
 │    Sensor          Sensor          Sensor          Sensor
 │      │               │               │               │
 └──────┼───────────────┼───────────────┼───────────────┼─┘
        └───────────────┼───────────────┴───────────────┘
                        ▼ (Cables through wall)
 ┌────────────────────────────────────────────────────────┐
 │         EDGE CONTROLLER (Outside Cold Room Wall)        │
 │                                                        │
 │   Raspberry Pi Pico W                                  │
 │   • Reads sensors every 60s & calculates average       │
 │   • Detects Power Loss (switches to Battery Backup)    │
 │   • Buffers offline data in Flash Memory if Wi-Fi cuts │
 └──────────────────────┬─────────────────────────────────┘
                        │
                        │ Wi-Fi TCP Stream (Port 5000)
                        │ Packet: "DATA,zone_a,uptime,temp,hum"
                        ▼
 ┌────────────────────────────────────────────────────────┐
 │       INGESTOR SERVICE (Python Background Service)     │
 │                                                        │
 │   • Listens for incoming Pico W TCP connection         │
 │   • Separates Live data vs. Backfill recovery data     │
 │   • Sends "Acknowledge" (k) so Pico clears its buffer  │
 └──────────────────────┬─────────────────────────────────┘
                        │
                        │ Fast Influx Line Protocol
                        ▼
 ┌────────────────────────────────────────────────────────┐
 │        INFLUXDB DATABASE (Time-Series Storage)         │
 │                                                        │
 │   • Stores data indexed by time and zone_id tag        │
 │   • 90+ days retention for regulatory compliance       │
 └──────────────────────┬─────────────────────────────────┘
                        │
                        │ Internal Flux Queries
                        ▼
 ┌────────────────────────────────────────────────────────┐
 │           BACKEND API (FastAPI - Python)               │
 │                                                        │
 │   • /api/zones/live       → Real-time average readings │
 │   • /api/zones/:id/trend  → 24-hour historical curves  │
 │   • /api/forecast         → Thermal rise rate (dT/dt)  │
 │   • /api/sensor-health    → Flatline & drift detection │
 │   • /api/reports/csv-pdf  → On-demand audit export     │
 └──────────────────────┬─────────────────────────────────┘
                        │
                        │ HTTP Polling (Every 10 seconds)
                        ▼
 ┌────────────────────────────────────────────────────────┐
 │         FRONTEND DASHBOARD (React + Vite Web App)      │
 │                                                        │
 │   • Live Zone Gauges (Temp & Humidity per Zone)        │
 │   • Power Status & Gateway Heartbeat Indicator         │
 │   • Interactive 24-Hour Temperature Curves (Recharts)  │
 │   • Time-to-Spoilage Countdown Alarm                   │
 │   • One-Click "Download PDF Audit Report" Button       │
 └────────────────────────────────────────────────────────┘
```

---

## 2. Software Component Breakdown

### Component 1: The Ingestor Service (`ingestor/`)
* **What it is:** A lightweight Python program running on your local computer that acts as the "receptionist" for the Pico W.
* **Why we need it:** The Pico W sends raw text streams over a network socket. We need a reliable program to listen on Port 5000, parse that text, organize it, and pass it cleanly into the database.
* **Key Tasks:**
  * **Distinguishes Data Types:** Knows if a packet is normal `LIVE` streaming or historical `BACKFILL` from a previous power outage.
  * **Handshake Confirmation:** When the Pico finishes dumping its backup data, the Ingestor replies with an acknowledgement byte (`b"k"`). This tells the Pico: *"I safely stored your data, you can now erase your flash memory."*
  * **Dynamic ID Detection:** Extracts the `zone_id` (e.g., `zone_a`). If no ID is provided, it automatically assigns a default ID so testing is never blocked.

---

### Component 2: InfluxDB (The Time-Series Database)
* **What it is:** A specialized database designed specifically for measurements that change over time (like temperature graphs).
* **How data is structured:**
  * **Bucket:** `frost_ioe`
  * **Tags (Labels for filtering):** `zone_id` (e.g. `zone_a`, `zone_b`), `source` (`LIVE` vs `BACKFILL`)
  * **Fields (Numeric numbers):** `temp_c`, `humidity`, `power_status` (1 = Mains, 0 = Battery)
  * **Timestamp:** Automatically marked in UTC+8.

---

### Component 3: FastAPI Backend Server (`backend/`)
* **What it is:** A fast, modern Python web server that connects the database to the user-facing dashboard.
* **What it does:** It creates clean "API Endpoints" (URLs that return data in JSON format):
  1. `GET /api/zones/live`: Asks InfluxDB for the single most recent reading for each zone.
  2. `GET /api/zones/{id}/trend`: Pulls the last 24 hours of data points to draw line graphs.
  3. `GET /api/forecast`: **The Predictive Engine.** Calculates the rate of temperature rise ($dT/dt$). If the freezer is warming up at $0.5\ ^\circ\text{C}$ per hour, it predicts: *"At this rate, statutory limit (-18 °C) will be breached in 3 hours 12 minutes."*
  4. `GET /api/sensor-health`: **Sanity Checker.** Flags if a sensor has flatlined (stuck on the exact same decimal number for 15 minutes) or if two probes are disagreeing widely.
  5. `GET /api/reports/export-csv` & `GET /api/reports/export-pdf`: Generates formal audit documents on demand.

---

### Component 4: The React Dashboard (`frontend/`)
* **What it is:** The clean visual interface that warehouse staff and food safety auditors see in their web browser.
* **Key Visual Elements:**
  * **Zone Overview Cards:** Large numbers showing current average temperature and humidity. Color-coded (Green = Safe $\le -18\ ^\circ\text{C}$, Amber = Warning, Red = Breach).
  * **Heartbeat & Power Indicator:** A green glowing dot showing the gateway is connected, and an icon indicating whether the system is running on **Mains Electricity** or **Battery Backup**.
  * **Time-Series Graphs:** Interactive charts powered by *Recharts* showing smooth temperature and humidity curves over the last 24 hours.
  * **Audit Report Center:** A date-picker and two buttons: **"Download Raw CSV"** and **"Download Authority PDF"**.
* **How it updates:** Uses simple, reliable **polling** every 10 seconds. Every 10 seconds, it asks the FastAPI backend for the latest numbers and updates the screen smoothly without reloading the page.

---

## 4. System Workflows

### Workflow A: Normal Day-to-Day Operation
```text
1. 4 Corner sensors take temperature and humidity readings.
2. Pico W calculates the average.
3. Pico W sends: "DATA,zone_a,3600,-19.2,82.4" via Wi-Fi TCP.
4. Ingestor receives line -> tags it as LIVE -> writes to InfluxDB.
5. InfluxDB stores the record.
6. React Dashboard polls FastAPI every 10s -> reads latest value -> Gauge shows "-19.2 °C (Safe)".
```

---

### Workflow B: Power Cut & Backfill Recovery (Zero Data Loss)
```text
1. Warehouse mains power trips at 2:00 AM.
2. Pico W hardware sense circuit detects voltage drop within 5s.
3. Pico switches to Battery Backup. Wi-Fi router is dead, so TCP fails.
4. Pico enters OFFLINE LOGGING MODE:
   - Takes readings every 60s.
   - Saves them to onboard LittleFS flash memory.
5. Mains power is restored at 4:30 AM. Wi-Fi reconnects.
6. Pico W connects to the Ingestor and sends:
   - "---BEGIN---"
   - 150 buffered rows: "<uptime>,<temp>,<hum>"
   - "---END---"
7. Ingestor receives all rows -> tags them as BACKFILL -> writes them into InfluxDB.
8. Ingestor sends back "k" (Acknowledge).
9. Pico receives "k" and safely deletes its local flash copy.
Result: The 2.5-hour blackout gap is completely filled in the database and dashboard!
```

---

### Workflow C: Predictive Forecasting ($dT/dt$)
```text
1. A forklift driver accidentally leaves the cold room door cracked open.
2. Temperature slowly rises: -19°C -> -18.5°C -> -18.1°C over 15 minutes.
3. FastAPI's /api/forecast analyzes the slope (rate of change over 10 minutes).
4. The system calculates:
   - Slope = +0.06 °C per minute
   - Distance to -18.0 °C statutory limit = 0.1 °C
5. Dashboard displays an early warning box:
   "Rising at 3.6 °C/hr. Estimated breach in 10 minutes. Check door seals."
```

---

### Workflow D: Compliance Audit Export (CSV & PDF)
```text
1. Ministry of Health (KKM) or internal auditor arrives for an inspection.
2. Manager opens the Frost-IoE Dashboard and selects: "Last 30 Days".
3. Manager clicks "Generate PDF Report".
4. FastAPI queries InfluxDB for all records in that window.
5. Python's ReportLab compiles a formal multi-page PDF containing:
   - Facility Name, Zone ID, Date Range
   - Minimum, Maximum, and Average Temperatures
   - Log of any threshold excursions with exact duration
   - Digital validation disclaimer ("Generated automatically by Frost-IoE")
6. PDF downloads directly to the manager's browser.
```

---

## 5. Telemetry Packet Protocol Reference

The communication between the Raspberry Pi Pico W and the Ingestor uses clean, comma-separated plain text over a TCP socket:

| Packet Header | Example | Meaning |
|---|---|---|
| `DATA` | `DATA,zone_a,1240,-19.4,85.0` | Real-time sensor reading (`zone_id`, `uptime_seconds`, `temp_c`, `humidity`). |
| `UPTIME` | `UPTIME,1240` | Timestamp synchronization message so the laptop knows the Pico's clock offset. |
| `---BEGIN---` | `---BEGIN---` | Flags the start of offline backfill transmission. |
| `[Backfill Row]` | `1180,-19.1,84.5` | Historical record logged during Wi-Fi or power outage. |
| `---END---` | `---END---` | Signals end of backfill. Expects `b"k"` acknowledgement from Ingestor. |

---

## 6. Recommended Repository File Structure

```text
Frost-IoE/
│
├── ingestor/                     # Background TCP listener
│   ├── main.py                   # Socket server & InfluxDB writer
│   ├── parser.py                 # Parses DATA / BACKFILL / UPTIME lines
│   └── config.py                 # InfluxDB URL, token, port configuration
│
├── backend/                      # FastAPI Web Server
│   ├── main.py                   # App entrypoint & CORS setup
│   ├── config.py                 # Settings & Threshold constants (-18 °C)
│   ├── influx_client.py          # Database query helper functions
│   ├── routers/
│   │   ├── zones.py              # Live status & trend endpoints
│   │   ├── forecast.py           # Thermal rise rate (dT/dt) logic
│   │   ├── health.py             # Heartbeat & sensor anomaly checks
│   │   └── reports.py            # CSV streaming & ReportLab PDF generator
│   └── templates/                # Optional PDF styling assets
│
├── frontend/                     # React + Vite Dashboard
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx               # Main dashboard layout
│       ├── api/
│       │   └── client.js         # Centralized API fetch calls
│       └── components/
│           ├── ZoneCard.jsx      # Live gauges & temperature indicators
│           ├── HeartbeatBar.jsx  # Network & power status bar
│           ├── TrendChart.jsx    # 24h interactive Recharts line graph
│           ├── ForecastCard.jsx  # Thermal rise rate countdown panel
│           ├── SensorHealth.jsx  # Stuck/drift sensor warnings
│           └── ReportExport.jsx  # CSV & PDF download buttons
│
├── requirements.txt              # Python dependencies
├── .env.example                  # Template for API keys & Influx tokens
└── README.md                     # Project overview & quickstart
```

---

## 7. Technology Stack Summary

| Layer | Chosen Tool | Reason for Choice |
|---|---|---|
| **Edge Hardware** | Raspberry Pi Pico W | Cheap, built-in Wi-Fi, low power, onboard flash storage. |
| **Ingestion** | Python (`socket`, `influxdb-client`) | Direct replacement for existing script; rock-solid TCP handling. |
| **Database** | InfluxDB v2 (Local or Cloud) | Purpose-built for time-series sensor data, high write performance. |
| **Backend API** | FastAPI (Python) | High performance, simple syntax, auto-generated documentation (`/docs`). |
| **PDF Generation** | ReportLab (Python) | Clean, code-generated PDF audit reports on demand. |
| **Frontend UI** | React (Vite) + Tailwind CSS | Fast development, modular component architecture, modern aesthetics. |
| **Visual Charts** | Recharts | Smooth SVG charts optimized for React state updates. |
