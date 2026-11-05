from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from analytics import forecast, clean_points
from config import settings
from influx_client import influx_service

router = APIRouter(prefix="/api", tags=["Thermal forecast"])

@router.get("/forecast")
def get_forecast(zone_id: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
                 limit_c: float = Query(default=-18, ge=-100, le=100, allow_inf_nan=False)):
    now = datetime.now(timezone.utc)
    try:
        rows = influx_service.get_raw_readings(zone_id, now-timedelta(minutes=10), now)
    except Exception:
        raise HTTPException(503, "Temperature history is unavailable")
    # Equal weighting of available sensors at each timestamp, for the zone forecast.
    sensors = {}
    for row in rows:
        identity = row.get("sensor_id") or row.get("node_id") or "zone_aggregate"
        sensors.setdefault(identity, []).append(row)
    grouped = {}
    for readings in sensors.values():
        for stamp, temp in clean_points(readings, now-timedelta(minutes=10), now):
            grouped.setdefault(stamp, []).append(temp)
    series = [{"timestamp": t, "temp_c": sum(v)/len(v)} for t,v in grouped.items()]
    return {"zone_id": zone_id, "generated_at": now, "mock_mode": settings.USE_MOCK_DATA,
            "window_minutes": 10, "prediction_horizon_minutes": 20,
            "interpretation": "Linear temperature-limit projection, not a spoilage prediction or confirmed breach alarm.",
            **forecast(series, now, limit_c)}
