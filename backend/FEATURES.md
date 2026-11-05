# Forecast, sensor health and PDF reports

From the repository root (PowerShell):

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Set-Location backend
python -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs. Mock mode is enabled by default; every new endpoint identifies mock data and PDFs label it as demonstration data. Put actual database settings in backend/.env and set USE_MOCK_DATA=false to use InfluxDB. Do not commit credentials.

## Endpoints

- GET /api/forecast?zone_id=zone_a&limit_c=-18 : least-squares slope using actual timestamps over ten minutes, rates in C/min and C/hour, time to the selected upper limit, warning within twenty minutes. Cooling has no projected crossing; already-above-limit readings are labelled breached. This is not the separate confirmed-alarm rule or a product-spoilage estimate.
- GET /api/sensor-health?zone_id=zone_a : suspected flatline when the temperature range is below 0.05 C over fifteen minutes. Drift requires individual sensor_id or node_id tags and commissioned baseline offsets; compares offset-corrected readings to the median of available peers, aligned within thirty seconds, for six hours of sustained deviation over 1 C. Disagreement does not establish which sensor is faulty.
- GET /api/reports/export-pdf?zone_id=zone_a&start=2026-10-30T00:00:00Z&end=2026-10-31T00:00:00Z&facility=Pilot&limit_c=-18 : downloadable PDF with per-series sample statistics, source counts and observed excursions. Use timezone-aware start/end; end is exclusive; start must be in the past; a future end is allowed and clearly labelled partial; maximum period 31 days and 50,000 source records. Shorten the period when the record cap is reached. Times are printed in Malaysia time (MYT, UTC+8), in a readable 24-hour format. UTC storage and query boundaries are unchanged. The sample mean is not time-weighted. This is a summary, not a full raw-record export or compliance certificate.

Set a room-appropriate upper limit explicitly (for example limit_c=10 for a chilled-room scenario); the default is the existing frozen-room upper limit -18. Lower-limit breaches are outside this thermal-rise feature.

Zone IDs accepted by these new endpoints use letters, digits, underscore, dot, colon and hyphen (1-128 characters).

## Data requirements and limits

Existing measurement: zone_environment, zone_id tag, temp_c field, UTC timestamps, optional source tag. Preserve sensor_id or node_id tags on ingestion for individual health checks; zone averages cannot support sensor drift detection. Baselines must come from commissioning, not inferred automatically from potentially faulty data. Set SENSOR_BASELINE_OFFSETS in backend/.env as JSON, for example {"node_a":0.0,"node_b":0.3}. Offsets represent expected sensor/location differences and are subtracted before comparison. Only compare sensors in the same appropriate monitoring zone.

Forecast and flatline checks need at least three usable samples, history spanning the requested window minus one sampling minute, a last sample no older than 180 seconds, and no internal gap over 180 seconds. Missing coverage returns an unavailable reason rather than a healthy result. Suspected flatline can occur under genuinely stable conditions; corroborate with independent checks. Conflicting duplicate timestamps are discarded within each series. Drift is unavailable without comparable peer history. No background alert dispatch or SMS integration is introduced.

Raw analytics queries avoid the existing five-minute chart averages. Do not connect these features to ingestion data that has already averaged away individual sensors. The repository architecture guide still describes the earlier multi-probe controller; ingestion and firmware changes are outside this backend implementation.

No authentication or site ownership model exists in this starter backend. These endpoints follow the existing deployment scope; add authentication and site access checks before exposing customer data publicly.

## Audit exports and download page

Open http://127.0.0.1:8000/api/reports for calendar/time pickers in Malaysia time and PDF/Excel download buttons.

GET /api/reports/export-excel accepts the same parameters as export-pdf. Excel has Summary, Readings, Events and Review sheets. Temperature statistics use the same per-series cleaning as PDF. Readings retain returned source records, sensor/node IDs, MYT and UTC times, and duplicate/conflict flags. Invalid records already rejected upstream are not restored. Use the original database for full source verification.

Exports are fixed snapshots. Statistics do not recalculate when cells are edited. Excel sheets are password-protected and workbook structure is locked. Review starts as Not reviewed and is read-only; keep review notes in a separate log. PDF opens without a password and requests no editing, copying or annotations while allowing printing. Each export uses a random protection password that is not stored. These are application-level restrictions, not tamper-proof or copy-proof security; downloaded files can still be duplicated or protections bypassed. Reports support audit review but do not certify compliance, safety or authenticity.

A future end queries only up to the export time and produces a partial report in both formats. It does not schedule a later export. Export again when the period ends. Existing 31-day and 50,000-record limits still apply.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Tests use synthetic readings and mocked queries; live InfluxDB and hardware must be verified separately.
