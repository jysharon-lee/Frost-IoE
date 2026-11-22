import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.query_api import QueryApi
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi

from analytics import rate_per_min
from config import settings
from schemas import ComplianceStatus, LiveZoneReading, NodeReading, TrendPoint
from sitecfg import site, zone_limits

# Firmware schema: measurement "environment", tags zone_id/node_id/buffered,
# fields temp_c, rh_pct, ok (false = sensor did not answer; no temp_c/rh_pct written).
MEASUREMENT = "environment"
ALERT_MEASUREMENT = "alert_events"
SEVERITY = [ComplianceStatus.NORMAL, ComplianceStatus.WARNING, ComplianceStatus.CRITICAL]


class InfluxService:
    def __init__(self):
        self._client: Optional[InfluxDBClient] = None
        self._query_api: Optional[QueryApi] = None
        self._write_api: Optional[WriteApi] = None
        self._mock_alert_events: List[dict] = []

    def _ensure_client(self) -> InfluxDBClient:
        if self._client is None:
            self._client = InfluxDBClient(
                url=settings.INFLUX_HOST,
                token=settings.INFLUX_TOKEN,
                org=settings.clean_org,
                timeout=15_000
            )
        return self._client

    def get_query_api(self) -> QueryApi:
        """Lazy initialization of InfluxDB client and QueryApi."""
        if self._query_api is None:
            self._query_api = self._ensure_client().query_api()
        return self._query_api

    def get_write_api(self) -> WriteApi:
        """Lazy initialization of synchronous WriteApi for alert_events persistence."""
        if self._write_api is None:
            self._write_api = self._ensure_client().write_api(write_options=SYNCHRONOUS)
        return self._write_api

    def close(self):
        if self._write_api:
            self._write_api.close()
            self._write_api = None
        if self._client:
            self._client.close()
            self._client = None
            self._query_api = None

    def calculate_status(self, temp_c: Optional[float], limits: Optional[dict]) -> ComplianceStatus:
        """NORMAL inside limits, WARNING up to warn_margin outside them, CRITICAL beyond."""
        if temp_c is None or not limits:
            return ComplianceStatus.NO_DATA
        hi, lo = limits.get("max"), limits.get("min")
        over = max(temp_c - hi if hi is not None else 0, lo - temp_c if lo is not None else 0)
        if over <= 0:
            return ComplianceStatus.NORMAL
        return ComplianceStatus.WARNING if over <= limits.get("warn_margin", 0) else ComplianceStatus.CRITICAL

    def _latest_by_node(self) -> dict:
        """node_id -> {field: (value, time)}. Grouped without tags so buffered=true/false merge."""
        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -2h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          |> filter(fn: (r) => r["_field"] == "ok" or r["_field"] == "temp_c" or r["_field"] == "rh_pct")
          |> group(columns: ["zone_id", "node_id", "_field"])
          |> last()'''
        latest: dict = {}
        for table in self.get_query_api().query(query, org=settings.clean_org):
            for record in table.records:
                latest.setdefault(record.values.get("node_id"), {})[record.get_field()] = (
                    record.get_value(), record.get_time())
        return latest

    def _rate_by_node(self) -> dict:
        """node_id -> °C/hour over the last 30 min (1-min means). Best effort: {} if the query fails.
        30 min, not 10: a compressor cycle swings the room ~1 °C and would flip a short window."""
        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -30m)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}" and r["_field"] == "temp_c")
          |> group(columns: ["node_id"])
          |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)'''
        series: dict = {}
        try:
            for table in self.get_query_api().query(query, org=settings.clean_org):
                for record in table.records:
                    series.setdefault(record.values.get("node_id"), []).append((record.get_time(), record.get_value()))
        except Exception:
            return {}
        return {n: rate_per_min(pts) * 60 for n, pts in series.items() if len(pts) >= 10}

    def get_nodes_live(self, zone_id: Optional[str] = None, node_id: Optional[str] = None) -> List[NodeReading]:
        """Latest reading for every node in the site config. Nodes that never reported come back empty."""
        latest = {} if settings.USE_MOCK_DATA else self._latest_by_node()
        rates = {} if settings.USE_MOCK_DATA else self._rate_by_node()
        now = datetime.now(timezone.utc)
        nodes: List[NodeReading] = []
        for zone in site["zones"]:
            if zone_id not in (None, zone["zone_id"]):
                continue
            for node in zone["nodes"]:
                if node_id not in (None, node["node_id"]):
                    continue
                if settings.USE_MOCK_DATA:
                    base = self._mock_base(zone["zone_id"])
                    entry = {"ok": (True, now), "temp_c": (base + random.uniform(-0.4, 0.4), now),
                             "rh_pct": (80 + random.uniform(-1.5, 1.5), now)}
                else:
                    entry = latest.get(node["node_id"], {})
                ok, stamp = entry.get("ok", (False, None))
                # A failed sensor writes ok=false and no temp_c; ignore any older temp_c left in the window.
                # Too old = offline: drop the value, keep the timestamp as "last seen".
                good = (bool(ok) and entry.get("temp_c", (None, None))[1] == stamp
                        and now - stamp <= timedelta(seconds=settings.STALE_AFTER_S))
                temp = round(float(entry["temp_c"][0]), 2) if good else None
                hum = round(float(entry["rh_pct"][0]), 1) if good and "rh_pct" in entry else None
                nodes.append(NodeReading(
                    node_id=node["node_id"], zone_id=zone["zone_id"], name=node["name"],
                    location=node.get("location", ""), temp_c=temp, humidity=hum,
                    status=self.calculate_status(temp, zone["limits"]), timestamp=stamp,
                    rate_c_per_hour=round(rates[node["node_id"]], 2) if good and node["node_id"] in rates else None))
        return nodes

    def get_live_readings(self) -> List[LiveZoneReading]:
        """Per zone: mean of reporting nodes; status is the worst node's so one warm corner is not averaged away."""
        all_nodes = self.get_nodes_live()
        results: List[LiveZoneReading] = []
        for zone in site["zones"]:
            nodes = [n for n in all_nodes if n.zone_id == zone["zone_id"]]
            temps = [n.temp_c for n in nodes if n.temp_c is not None]
            hums = [n.humidity for n in nodes if n.humidity is not None]
            stamps = [n.timestamp for n in nodes if n.timestamp]
            rates = [n.rate_c_per_hour for n in nodes if n.rate_c_per_hour is not None]
            status = max((n.status for n in nodes if n.temp_c is not None),
                         key=SEVERITY.index, default=ComplianceStatus.NO_DATA)
            results.append(LiveZoneReading(
                zone_id=zone["zone_id"], name=zone["name"], type=zone.get("type", ""),
                limits=zone["limits"],
                temp_c=round(sum(temps) / len(temps), 2) if temps else None,
                humidity=round(sum(hums) / len(hums), 1) if hums else None,
                status=status, timestamp=max(stamps, default=None), nodes=nodes,
                rate_c_per_hour=round(sum(rates) / len(rates), 2) if rates else None))
        return results

    def get_zone_trend(self, zone_id: str, hours: int = 24) -> List[TrendPoint]:
        """Zone trend downsampled to 5-minute means across all its nodes."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_trend(zone_id=zone_id, hours=hours)

        flux_query = f'''
        from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -{int(hours)}h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          |> filter(fn: (r) => r["zone_id"] == {json.dumps(zone_id)})
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "rh_pct")
          |> group(columns: ["_field"])
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''
        return self._execute_trend_query(flux_query)

    def get_node_trend(self, zone_id: str, node_id: str, hours: int = 24) -> List[TrendPoint]:
        """Single node trend downsampled to 5-minute means."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_trend(zone_id=zone_id, hours=hours, node_id=node_id)

        flux_query = f'''
        from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -{int(hours)}h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")
          |> filter(fn: (r) => r["zone_id"] == {json.dumps(zone_id)})
          |> filter(fn: (r) => r["node_id"] == {json.dumps(node_id)})
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "rh_pct")
          |> group(columns: ["_field"])
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''
        return self._execute_trend_query(flux_query)

    def _execute_trend_query(self, flux_query: str) -> List[TrendPoint]:
        query_api = self.get_query_api()
        tables = query_api.query(flux_query, org=settings.clean_org)

        points: List[TrendPoint] = []
        for table in tables:
            for record in table.records:
                values = record.values
                temp_c = values.get("temp_c")
                humidity = values.get("rh_pct")
                points.append(
                    TrendPoint(
                        timestamp=record.get_time(),
                        temp_c=round(float(temp_c), 2) if temp_c is not None else None,
                        humidity=round(float(humidity), 2) if humidity is not None else None,
                    )
                )

        return points

    def get_raw_readings(self, zone_id: str, start: datetime, end: datetime) -> List[dict]:
        """Unrounded observations in [start, end), preserving individual sensor tags.

        Unlike chart data these must not use aggregateWindow: averaging hides faults.
        Bound the query globally and fail rather than silently truncate an audit report.
        """
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", zone_id):
            raise ValueError("Invalid zone identifier")
        max_records = 50_000
        if settings.USE_MOCK_DATA:
            rows = []
            stamp = start
            base = self._mock_base(zone_id)
            while stamp < end:
                if len(rows) >= max_records:
                    raise ValueError("Reading limit exceeded")
                rows.append({"timestamp": stamp, "temp_c": base + 0.2 * math.sin(len(rows)/7),
                             "humidity": 80.0, "source": "MOCK"})
                stamp += timedelta(minutes=1)
            return rows
        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: time(v: {json.dumps(start.isoformat())}), stop: time(v: {json.dumps(end.isoformat())}))
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}" and r["zone_id"] == {json.dumps(zone_id)})
          |> filter(fn: (r) => r["_field"] == "temp_c")
          |> group(columns: [])
          |> sort(columns: ["_time"])
          |> limit(n: {max_records + 1})'''
        tables = self.get_query_api().query(query, org=settings.clean_org)
        rows = []
        record_count = 0
        for table in tables:
            for record in table.records:
                record_count += 1
                if record_count > max_records:
                    raise ValueError("Reading limit exceeded")
                value = record.get_value()
                if value is None or not math.isfinite(float(value)):
                    continue
                rows.append({"timestamp": record.get_time(), "temp_c": float(value),
                             "sensor_id": record.values.get("sensor_id"),
                             "node_id": record.values.get("node_id"),
                             # Firmware tags points logged during an outage buffered=true.
                             "source": "BACKFILL" if record.values.get("buffered") == "true" else "LIVE"})
                if len(rows) > max_records:
                    raise ValueError("Reading limit exceeded")
        return rows

    # --- Alert & Notification Persistence (measurement: alert_events) ---

    def get_latest_live_timestamps(self) -> Dict[str, datetime]:
        """node_id -> latest LIVE (non-buffered) report timestamp over the last 24h.

        Excludes buffered="true" backfill rows so post-outage gap-filling never fires
        or masks live offline alerts.
        """
        now = datetime.now(timezone.utc)
        if settings.USE_MOCK_DATA:
            return {n["node_id"]: now for z in site["zones"] for n in z["nodes"]}

        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -24h)
          |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}" and r["_field"] == "ok")
          |> filter(fn: (r) => not exists r["buffered"] or r["buffered"] != "true")
          |> group(columns: ["zone_id", "node_id"])
          |> last()'''
        latest: Dict[str, datetime] = {}
        for table in self.get_query_api().query(query, org=settings.clean_org):
            for record in table.records:
                node_id = record.values.get("node_id")
                stamp = record.get_time()
                if node_id and stamp:
                    prev = latest.get(node_id)
                    if prev is None or stamp > prev:
                        latest[node_id] = stamp
        return latest

    def write_alert_event(self, event: dict) -> None:
        """Persist an alert or recovery event into InfluxDB measurement `alert_events`."""
        ts = event.get("timestamp") or datetime.now(timezone.utc)
        record = {
            "timestamp": ts,
            "zone_id": str(event["zone_id"]),
            "node_id": str(event.get("node_id") or "zone_aggregate"),
            "alert_type": str(event["alert_type"]),
            "severity": str(event["severity"]),
            "state": str(event["state"]),
            "message": str(event["message"]),
            "temp_c": float(event["temp_c"]) if event.get("temp_c") is not None else None,
            "limit_c": float(event["limit_c"]) if event.get("limit_c") is not None else None,
            "peak_c": float(event["peak_c"]) if event.get("peak_c") is not None else None,
            "duration_minutes": (
                float(event["duration_minutes"]) if event.get("duration_minutes") is not None else None
            ),
            "email_sent": bool(event.get("email_sent", False)),
        }
        if settings.USE_MOCK_DATA:
            self._mock_alert_events.append(record)
            if len(self._mock_alert_events) > 1000:
                self._mock_alert_events = self._mock_alert_events[-1000:]
            return

        point = (
            Point(ALERT_MEASUREMENT)
            .tag("zone_id", record["zone_id"])
            .tag("node_id", record["node_id"])
            .tag("alert_type", record["alert_type"])
            .tag("severity", record["severity"])
            .tag("state", record["state"])
            .field("message", record["message"])
            .field("email_sent", record["email_sent"])
            .time(ts)
        )
        for field_name in ("temp_c", "limit_c", "peak_c", "duration_minutes"):
            if record[field_name] is not None:
                point = point.field(field_name, record[field_name])

        self.get_write_api().write(bucket=settings.INFLUX_BUCKET, org=settings.clean_org, record=point)

    def get_alert_events(
        self,
        zone_id: Optional[str] = None,
        hours: int = 24,
        limit: int = 200,
    ) -> List[dict]:
        """Return alert and recovery events from InfluxDB `alert_events`, newest first."""
        if zone_id is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", zone_id):
            raise ValueError("Invalid zone identifier")
        if settings.USE_MOCK_DATA:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            filtered = [
                e for e in self._mock_alert_events
                if e["timestamp"] >= cutoff and (zone_id is None or e["zone_id"] == zone_id)
            ]
            filtered.sort(key=lambda e: e["timestamp"], reverse=True)
            return filtered[:limit]

        zone_filter = f'|> filter(fn: (r) => r["zone_id"] == {json.dumps(zone_id)})' if zone_id else ""
        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -{int(hours)}h)
          |> filter(fn: (r) => r["_measurement"] == "{ALERT_MEASUREMENT}")
          {zone_filter}
          |> pivot(rowKey: ["_time", "zone_id", "node_id", "alert_type", "severity", "state"], columnKey: ["_field"], valueColumn: "_value")
          |> group()
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: {int(limit)})'''
        return self._parse_alert_tables(self.get_query_api().query(query, org=settings.clean_org))

    def get_latest_alert_states(self, days: int = 7) -> Dict[Tuple[str, str, str], dict]:
        """Return the latest event per (zone_id, node_id, alert_type) for startup hydration."""
        if settings.USE_MOCK_DATA:
            latest: Dict[Tuple[str, str, str], dict] = {}
            for e in sorted(self._mock_alert_events, key=lambda x: x["timestamp"]):
                latest[(e["zone_id"], e["node_id"], e["alert_type"])] = e
            return latest

        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: -{int(days)}d)
          |> filter(fn: (r) => r["_measurement"] == "{ALERT_MEASUREMENT}")
          |> pivot(rowKey: ["_time", "zone_id", "node_id", "alert_type", "severity", "state"], columnKey: ["_field"], valueColumn: "_value")
          |> group(columns: ["zone_id", "node_id", "alert_type"])
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 1)'''
        events = self._parse_alert_tables(self.get_query_api().query(query, org=settings.clean_org))
        return {(e["zone_id"], e["node_id"], e["alert_type"]): e for e in events}

    @staticmethod
    def _parse_alert_tables(tables) -> List[dict]:
        events: List[dict] = []
        for table in tables:
            for record in table.records:
                v = record.values
                events.append({
                    "timestamp": record.get_time(),
                    "zone_id": v.get("zone_id", "unknown"),
                    "node_id": v.get("node_id", "zone_aggregate"),
                    "alert_type": v.get("alert_type", "unknown"),
                    "severity": v.get("severity", "CRITICAL"),
                    "state": v.get("state", "ALERTING"),
                    "message": v.get("message", ""),
                    "temp_c": round(float(v["temp_c"]), 2) if v.get("temp_c") is not None else None,
                    "limit_c": round(float(v["limit_c"]), 2) if v.get("limit_c") is not None else None,
                    "peak_c": round(float(v["peak_c"]), 2) if v.get("peak_c") is not None else None,
                    "duration_minutes": (
                        round(float(v["duration_minutes"]), 2)
                        if v.get("duration_minutes") is not None
                        else None
                    ),
                    "email_sent": bool(v.get("email_sent", False)),
                })
        return events

    # Mock data follows the site config so any client layout can be demoed.
    @staticmethod
    def _mock_base(zone_id: str) -> float:
        limits = zone_limits(zone_id) or {}
        hi, lo = limits.get("max", 2.0), limits.get("min")
        return (lo + hi) / 2 if lo is not None else hi - 1.2

    def _generate_mock_trend(self, zone_id: str, hours: int, node_id: Optional[str] = None) -> List[TrendPoint]:
        points: List[TrendPoint] = []
        now = datetime.now(timezone.utc)
        interval_minutes = 5
        total_points = (hours * 60) // interval_minutes
        base_temp = self._mock_base(zone_id)
        # Slight per-node offset so individual node curves look distinct
        offset = (sum(map(ord, node_id)) % 5 - 2) * 0.1 if node_id else 0.0

        for i in range(total_points, -1, -1):
            point_time = now - timedelta(minutes=i * interval_minutes)
            temp = round(base_temp + offset + random.uniform(-0.6, 0.6), 2)
            hum = round(80.0 + random.uniform(-3.0, 3.0), 1)
            points.append(TrendPoint(timestamp=point_time, temp_c=temp, humidity=hum))

        return points

# Singleton instance for import across backend
influx_service = InfluxService()
