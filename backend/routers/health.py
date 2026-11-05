from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from analytics import sensor_health
from config import settings
from influx_client import influx_service

router = APIRouter(prefix="/api", tags=["Sensor health"])

@router.get("/sensor-health")
def get_sensor_health(zone_id: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")):
    now = datetime.now(timezone.utc)
    try:
        rows = influx_service.get_raw_readings(zone_id, now-timedelta(hours=6), now)
    except Exception:
        raise HTTPException(503, "Sensor history is unavailable")
    return {"zone_id": zone_id, "generated_at": now, "mock_mode": settings.USE_MOCK_DATA,
            "sensors": sensor_health(rows, now, settings.SENSOR_BASELINE_OFFSETS),
            "status": "available" if rows else "no_data"}
