from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, HTMLResponse
from pathlib import Path
from config import settings
from influx_client import influx_service
from reporting import build_pdf
from excel_reporting import build_excel

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@dataclass
class ReportData:
    start: datetime
    end: datetime
    zone_id: str
    facility: str
    limit: float
    generated_at: datetime
    observed_until: datetime
    rows: list


def report_data(start: datetime, end: datetime,
                zone_id: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
                facility: str = Query(default="Not specified", min_length=1, max_length=200),
                limit_c: float = Query(default=-18, ge=-100, le=100, allow_inf_nan=False)):
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "Include a timezone, for example 2026-11-01T00:00:00+08:00 for Malaysia time")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if end <= start or end - start > timedelta(days=31):
        raise HTTPException(422, "Select a period greater than zero and no longer than 31 days")
    if start >= now:
        raise HTTPException(422, "The start must be in the past. Future readings do not exist yet.")
    observed_until = min(end, now)
    try:
        rows = influx_service.get_raw_readings(zone_id, start, observed_until)
    except ValueError:
        raise HTTPException(413, "Too many readings; select a shorter report period")
    except Exception:
        raise HTTPException(503, "Report history is unavailable")
    return ReportData(start, end, zone_id, facility, limit_c, now, observed_until, rows)


def export(report, builder, media_type, filename):
    data = builder(report.rows, report.zone_id, report.facility, report.start, report.end,
                   report.limit, settings.USE_MOCK_DATA, generated_at=report.generated_at,
                   observed_until=report.observed_until)
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@router.get("/export-pdf", response_class=Response)
def export_pdf(report: ReportData = Depends(report_data)):
    return export(report, build_pdf, "application/pdf", "frost-ioe-report.pdf")


@router.get("/export-excel", response_class=Response)
def export_excel(report: ReportData = Depends(report_data)):
    return export(report, build_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                  "frost-ioe-audit.xlsx")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def report_page():
    return HTMLResponse((Path(__file__).resolve().parent.parent / "report_download.html").read_text(encoding="utf-8"))
