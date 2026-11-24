from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from alerts.engine import alert_engine
from influx_client import influx_service

router = APIRouter(prefix="/api/alerts", tags=["Alerts & Notifications"])


class AlertConfigUpdate(BaseModel):
    alerts_enabled: Optional[bool] = None
    forecast_alerts_enabled: Optional[bool] = None
    email_alerts_enabled: Optional[bool] = None
    sustained_breach_minutes: Optional[float] = Field(None, ge=0.5, le=120.0)
    door_sustained_minutes: Optional[float] = Field(None, ge=0.5, le=240.0)
    forecast_warning_minutes: Optional[float] = Field(None, ge=1.0, le=240.0)
    offline_alert_after_s: Optional[int] = Field(None, ge=30, le=3600)


class TestEmailRequest(BaseModel):
    recipients: Optional[List[str]] = None


@router.get("/active", summary="Get currently active alerts")
def get_active_alerts():
    active = alert_engine.get_active_alerts()
    return {
        "alerts": active,
        "count": len(active),
        "server_time": datetime.now(timezone.utc),
    }


@router.get("/history", summary="Get alert and recovery history from InfluxDB")
def get_alert_history(
    zone_id: Optional[str] = Query(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    hours: int = Query(default=24, ge=1, le=720, description="History window in hours (up to 30 days)"),
    limit: int = Query(default=200, ge=1, le=500),
):
    try:
        events = influx_service.get_alert_events(zone_id=zone_id, hours=hours, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Alert history unavailable: {exc}")
    return {
        "zone_id": zone_id,
        "hours": hours,
        "count": len(events),
        "events": events,
    }


@router.get("/config", summary="Get current alert engine configuration and switches")
def get_alert_config():
    return alert_engine.get_config()


@router.patch("/config", summary="Update alert switches (e.g., forecast early-warning on/off)")
def update_alert_config(body: AlertConfigUpdate):
    return alert_engine.update_config(**body.model_dump(exclude_none=True))


@router.post("/test-email", summary="Send a test alert email to verify SMTP settings")
def send_test_email(body: Optional[TestEmailRequest] = None):
    recipients = body.recipients if body else None
    return alert_engine.notifier.send_test_email(recipients=recipients)
