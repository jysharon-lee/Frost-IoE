from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, HTTPException, Query

from influx_client import influx_service
from schemas import LiveZoneReading, LiveZonesResponse, ZoneTrendResponse

router = APIRouter(prefix="/api/zones", tags=["Zones & Cold Rooms"])

@router.get("/live", response_model=LiveZonesResponse, summary="Get latest live readings for all zones")
def get_live_zones():
    try:
        readings: List[LiveZoneReading] = influx_service.get_live_readings()
        return LiveZonesResponse(
            zones=readings,
            count=len(readings),
            server_time=datetime.now(timezone.utc)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")

@router.get("/{zone_id}/trend", response_model=ZoneTrendResponse, summary="Get historical trend data for Recharts")
def get_zone_trend(
    zone_id: str,
    hours: int = Query(default=24, ge=1, le=168, description="History window in hours (1h to 7 days)")
):
    try:
        points = influx_service.get_zone_trend(zone_id=zone_id, hours=hours)
        return ZoneTrendResponse(
            zone_id=zone_id,
            hours=hours,
            point_count=len(points),
            data=points
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query error: {str(e)}")