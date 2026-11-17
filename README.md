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

## Mock vs live data

The backend uses mock data by default, so it runs without a database. For live data, create `backend/.env`:

```
USE_MOCK_DATA=false
INFLUX_TOKEN=your-influxdb-token
```

`.env` is gitignored. Never commit the token.
