# Frost-IoE

Cold-storage monitoring dashboard. Sensors inside a cold room report temperature and humidity to a Raspberry Pi Pico W, which streams the readings to a database. This repo holds the web dashboard and the API behind it.

**What it does**

- Shows live temperature and humidity per zone, colour-coded against food-safety limits (safe at or below -18 °C).
- Draws 24-hour history charts for each zone and sensor node.
- Forecasts how fast a zone is warming and when it will breach the limit.
- Flags faulty sensors (flatlined or drifting readings).
- Exports audit reports (Excel and PDF).

**Structure**

| Folder | What it is |
|---|---|
| `backend/` | FastAPI server that reads InfluxDB and serves the data as JSON |
| `frontend/` | React + Vite dashboard that polls the API every 10 seconds |

See `Software_Architecture.md` for the full system design.

## Run it

Needs Python 3 and Node.js. Use two terminals, both starting from the repo root.

**Terminal 1: backend** (http://localhost:8000)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

**Terminal 2: frontend** (http://localhost:5173)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

## Setting up a client

Each client's zones, nodes and limits live in one file, `backend/sites/<client>.json`, chosen with `SITE_CONFIG=sites/<client>.json` in `backend/.env`. Copy `sites/demo.json` and edit it. Zone and node IDs must match the tags the firmware writes. The dashboard builds itself from that file; see `Software_Architecture.md` section 4.

## Mock vs live (MCU) data

Switch by editing `backend/.env`, then **restart the backend** (settings are read once at startup). `.env` is gitignored. Never commit the token.

**Mock data** (no hardware, no database): scripted 4-zone demo.

```
USE_MOCK_DATA=true
SITE_CONFIG=sites/demo.json
```

For a faster alert demo (~35 min), append the lines from `backend/.env.demo`.

**MCU data** (Pico W writing to InfluxDB):

```
USE_MOCK_DATA=false
INFLUX_TOKEN=your-influxdb-token
SITE_CONFIG=sites/demo.hw.json
```

1. Fill in Wi-Fi and InfluxDB details in `FROST_IoE/secrets.h`.
2. Set `NODE_ID` and `ZONE_ID` in `FROST_IoE/FROST_IoE.ino` to match a node in the site file.
3. To also publish simulated nodes N02-N06, keep `SIM_ENABLED 1` (one board only) and put `normal.csv` in the SD card root. Otherwise set it to 0.
4. Flash the board. Readings appear on the dashboard within ~10 s. Check `http://localhost:8000/health` shows `"mock_mode": false`.
