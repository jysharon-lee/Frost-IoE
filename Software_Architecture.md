# Frost-IoE: Software Architecture

Cold-storage monitoring product. One deployment serves one client. Each client gets a **site config** describing their rooms and sensors, so the same code base produces a different dashboard per client.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Site** | One client's cold-storage facility. One dashboard per site. |
| **Zone** | One cold room. Has an ID (`Z1`), a name, a room type and temperature limits. |
| **Node** | One Raspberry Pi Pico W (MCU) with one AHT20 temperature/humidity sensor, in an enclosure. Has an ID (`N01`) and belongs to one zone. A zone has many nodes. |

---

## 2. Architecture

```text
 ┌──────────────────────────────────────────────┐
 │ NODE (one per measurement point)             │
 │ Pico W + AHT20, polls every few seconds      │
 │  • Wi-Fi up   → HTTPS POST to InfluxDB Cloud │
 │  • Link down  → append to flash log          │
 │                 (tag buffered=true)          │
 │  • Link back  → flush log in batches         │
 │  • Time: NTP, else estimate (time_est=true)  │
 └───────────────────────┬──────────────────────┘
                         │ InfluxDB line protocol over HTTPS
                         ▼
 ┌──────────────────────────────────────────────┐
 │ INFLUXDB CLOUD  (bucket FROST-IoE)           │
 └───────────────────────┬──────────────────────┘
                         │ Flux queries
                         ▼
 ┌──────────────────────────────────────────────┐
 │ BACKEND  FastAPI (backend/)                  │
 │  • Reads sites/<client>.json at startup      │
 │  • Mean / status per zone, forecast, health  │
 │  • PDF + Excel audit reports                 │
 └───────────────────────┬──────────────────────┘
                         │ JSON, polled every 10 s
                         ▼
 ┌──────────────────────────────────────────────┐
 │ FRONTEND  React + Vite (frontend/)           │
 │  • Builds sidebar, zone pages and node cards │
 │    from the API; nothing client-specific in  │
 │    the UI code                               │
 └──────────────────────────────────────────────┘
```

There is no ingestor service: nodes write to InfluxDB directly.

---

## 3. Node data (firmware to InfluxDB)

One line per node per poll:

```text
environment,node_id=N02,zone_id=Z1,buffered=false temp_c=25.0,rh_pct=60.1,ok=true,time_est=false,uptime_s=210i 1760950000
```

| Item | Meaning |
|---|---|
| Measurement | `environment` |
| Tag `node_id`, `zone_id` | Must match the IDs in the site config. |
| Tag `buffered` | `true` if the point was logged during an outage and sent later. |
| Field `temp_c`, `rh_pct` | Readings (float). Absent when the sensor failed. |
| Field `ok` | `false` if the sensor did not answer. Then only `ok`, `time_est`, `uptime_s` are written. |
| Field `time_est` | `true` if the timestamp is an estimate (NTP not synced). |
| Field `uptime_s` | Seconds since boot. |

### Outage behaviour

1. Link to the database is lost: the node logs points to flash with `buffered=true`.
2. The dashboard cannot be told about this live, because the node cannot reach the database. It sees **silence** and shows an outage message (section 5).
3. Link returns: the node flushes its log with the original timestamps. The history charts fill the gap on the next poll.

---

## 4. Site config

One file per client: `backend/sites/<client>.json`, selected with `SITE_CONFIG` in `backend/.env`. We write it after the client consultation. **Clients cannot edit it.** Invalid config (unknown preset, duplicate IDs) stops the backend at startup.

```json
{
  "company": "Demo Client Sdn Bhd",
  "timezone": "Asia/Kuching",
  "zones": [
    {
      "zone_id": "Z1",
      "name": "Zone 1",
      "type": "Frozen storage",
      "preset": "frozen",
      "limits": { "max": -17 },
      "nodes": [
        { "node_id": "N01", "name": "Sensor 1", "location": "Near door", "baseline_offset": 0.0 }
      ]
    }
  ]
}
```

- `preset` supplies the limits (`backend/sitecfg.py`). `limits` is an optional per-zone override.
- Limits: `max`, optional `min`, and `warn_margin`. Inside the limits is NORMAL, outside by up to `warn_margin` is WARNING, beyond that is CRITICAL.
- **Preset values are provisional.** Only `frozen` (max -18 C) is confirmed. `chilled` is a placeholder, flagged `confirmed: false`, to be checked against the regulation.
- `baseline_offset` is optional, a commissioning offset used only by sensor drift detection.
- A configured node with no data shows as "no data". Data from a node that is not in the config is ignored.
- The frontend reads the config through `GET /api/site` (company name) and `GET /api/zones/live` (zones, nodes, limits).

---

## 5. What the dashboard shows

- **Header:** `FROST-IoE (MONITORING) · <company>`.
- **Zone page:** mean temperature and humidity of the zone, the **warmest sensor** beside it, then one small card per sensor. Click a card for location and limit. The warmest card is highlighted amber, a breaching card red.
- **Trend** (`↑ Rising`, `→ Stable`, `↓ Dropping`) on each sensor card, the zone card and the zone temperature tile: slope over the last 30 minutes, stable within ±1 °C/h (`TREND_LIMIT` in `frontend/src/utils/data.js`). Hidden for offline sensors or with under 10 minutes of data. Not available in backend mock mode.
- **Zone status** comes from the worst node, not the mean, so one warm corner is not averaged away.
- **Outage message** (a node counts as down when it is silent for 30 seconds or reported `ok=false`):
  - every sensor down: `Power down`
  - every sensor in one zone down: `Zone X down`
  - one sensor down: `Sensor Y in Zone X down`
- Forecast (dT/dt), sensor health and audit reports as described in `backend/FEATURES.md`.

---

## 6. Backend API

| Endpoint | Purpose |
|---|---|
| `GET /api/site` | Site config: company, zones, nodes, limits. |
| `GET /api/zones/live` | Every configured zone with mean, status and all its nodes. |
| `GET /api/zones/{zone_id}/trend` | Zone history, 5-minute means. |
| `GET /api/zones/{zone_id}/nodes[/{node_id}[/trend]]` | Node readings and history. |
| `GET /api/forecast` | Thermal rise rate and time to the limit. |
| `GET /api/sensor-health` | Flatline and drift suspicion. |
| `GET /api/reports/export-pdf`, `/export-excel` | Audit exports. |

---

## 7. Known gaps

- **Frontend, backend mode:** `frontend/src/api.js` (`getLiveZones`) replaces each zone's `nodes` with `[]` and so drops them. Node cards and the warmest-sensor card therefore appear only in demo mode until that is fixed.
- **Demo mode** uses its own generator in `frontend/src/utils/data.js`, not the site config.
- **Report size:** the 50,000-record cap is reached after about 46 hours for a 3-node zone polling every 10 s.
- **Room map:** node positions and room labels are stored in the browser (`localStorage`), not in the site config.
- Authentication and per-client access control do not exist yet.

---

## 8. Technology stack

| Layer | Tool |
|---|---|
| Node | Raspberry Pi Pico W, AHT20 sensor, LittleFS offline log |
| Database | InfluxDB Cloud (v2, Flux) |
| Backend | FastAPI (Python), ReportLab, openpyxl |
| Frontend | React + Vite, Recharts, lucide-react |
