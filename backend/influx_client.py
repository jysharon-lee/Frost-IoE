import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

from config import settings
from schemas import ComplianceStatus, LiveZoneReading, NodeReading, TrendPoint

ZONE_NAMES: Dict[str, str] = {
    "zone_a": "Freezer Room A (Frozen Poultry)",
    "zone_b": "Chilled Room B (Fresh Poultry)",
    "zone_c": "Loading Dock (Buffer)",
}

NODE_NAMES: Dict[str, str] = {
    "node_1": "Corner 1 (node_1)",
    "node_2": "Corner 2 (node_2)",
    "node_3": "Corner 3 (node_3)",
    "node_4": "Corner 4 (node_4)",
}

class InfluxService:
    def __init__(self):
        self._client: Optional[InfluxDBClient] = None
        self._query_api: Optional[QueryApi] = None

    def get_query_api(self) -> QueryApi:
        """Lazy initialization of InfluxDB client and QueryApi."""
        if self._query_api is None:
            self._client = InfluxDBClient(
                url=settings.INFLUX_HOST,
                token=settings.INFLUX_TOKEN,
                org=settings.clean_org,
                timeout=15_000
            )
            self._query_api = self._client.query_api()
        return self._query_api

    def close(self):
        if self._client:
            self._client.close()

    def calculate_status(self, temp_c: Optional[float]) -> ComplianceStatus:
        """Determines statutory compliance based on temperature threshold."""
        if temp_c is None:
            return ComplianceStatus.WARNING
        if temp_c <= settings.TEMP_SAFE_THRESHOLD:
            return ComplianceStatus.NORMAL
        elif temp_c <= settings.TEMP_WARNING_THRESHOLD:
            return ComplianceStatus.WARNING
        else:
            return ComplianceStatus.CRITICAL

    def get_nodes_live(self, zone_id: Optional[str] = None, node_id: Optional[str] = None) -> List[NodeReading]:
        """Fetches the most recent reading for each sensor node using last() and pivot()."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_nodes(zone_id=zone_id, node_id=node_id)

        zone_filter = f'|> filter(fn: (r) => r["zone_id"] == "{zone_id}")' if zone_id else ""
        node_filter = f'|> filter(fn: (r) => r["node_id"] == "{node_id}")' if node_id else ""

        flux_query = f'''
        from(bucket: "{settings.INFLUX_BUCKET}")
          |> range(start: -2h)
          |> filter(fn: (r) => r["_measurement"] == "zone_environment")
          {zone_filter}
          {node_filter}
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "humidity" or r["_field"] == "power_ok")
          |> last()
          |> map(fn: (r) => ({{ r with node_id: if exists r.node_id then r.node_id else "node_1" }}))
          |> pivot(rowKey: ["_time", "zone_id", "node_id"], columnKey: ["_field"], valueColumn: "_value")
        '''

        query_api = self.get_query_api()
        tables = query_api.query(flux_query, org=settings.clean_org)

        nodes: List[NodeReading] = []
        for table in tables:
            for record in table.records:
                values = record.values
                z_id = values.get("zone_id", zone_id or "unknown")
                n_id = values.get("node_id", node_id or "node_1")
                temp_c = values.get("temp_c")
                humidity = values.get("humidity")
                power_ok = values.get("power_ok", True)
                source = values.get("source", "LIVE")
                record_time = record.get_time()

                nodes.append(
                    NodeReading(
                        node_id=str(n_id),
                        zone_id=str(z_id),
                        name=NODE_NAMES.get(str(n_id), f"Sensor Node ({n_id})"),
                        temp_c=round(float(temp_c), 2) if temp_c is not None else None,
                        humidity=round(float(humidity), 2) if humidity is not None else None,
                        power_ok=bool(power_ok),
                        source=str(source),
                        status=self.calculate_status(temp_c),
                        timestamp=record_time if record_time else datetime.now(timezone.utc),
                    )
                )

        nodes.sort(key=lambda n: (n.zone_id, n.node_id))
        return nodes

    def get_live_readings(self) -> List[LiveZoneReading]:
        """Query 1: Fetches the most recent reading for each zone aggregated across its nodes."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_live()

        all_nodes = self.get_nodes_live()
        grouped: Dict[str, List[NodeReading]] = {}
        for node in all_nodes:
            grouped.setdefault(node.zone_id, []).append(node)

        results: List[LiveZoneReading] = []
        for zone_id, zone_nodes in sorted(grouped.items()):
            valid_temps = [n.temp_c for n in zone_nodes if n.temp_c is not None]
            valid_hums = [n.humidity for n in zone_nodes if n.humidity is not None]

            avg_temp = round(sum(valid_temps) / len(valid_temps), 2) if valid_temps else None
            avg_hum = round(sum(valid_hums) / len(valid_hums), 2) if valid_hums else None
            power_ok = all(n.power_ok for n in zone_nodes)
            source = "BACKFILL" if any(n.source == "BACKFILL" for n in zone_nodes) else "LIVE"
            latest_time = max((n.timestamp for n in zone_nodes), default=datetime.now(timezone.utc))

            results.append(
                LiveZoneReading(
                    zone_id=zone_id,
                    name=ZONE_NAMES.get(zone_id, f"Storage Zone ({zone_id})"),
                    temp_c=avg_temp,
                    humidity=avg_hum,
                    power_ok=power_ok,
                    source=source,
                    status=self.calculate_status(avg_temp),
                    timestamp=latest_time,
                    nodes=zone_nodes,
                )
            )

        return results

    def get_zone_trend(self, zone_id: str, hours: int = 24) -> List[TrendPoint]:
        """Query 2: Fetches historical zone trend downsampled to 5-minute averages across all nodes in the zone."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_trend(zone_id=zone_id, hours=hours)

        flux_query = f'''
        from(bucket: "{settings.INFLUX_BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_measurement"] == "zone_environment")
          |> filter(fn: (r) => r["zone_id"] == "{zone_id}")
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "humidity")
          |> group(columns: ["_field"])
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''

        return self._execute_trend_query(flux_query)

    def get_node_trend(self, zone_id: str, node_id: str, hours: int = 24) -> List[TrendPoint]:
        """Query 3: Fetches historical trend for a single sensor node downsampled to 5-minute averages."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_trend(zone_id=zone_id, hours=hours, node_id=node_id)

        flux_query = f'''
        from(bucket: "{settings.INFLUX_BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_measurement"] == "zone_environment")
          |> filter(fn: (r) => r["zone_id"] == "{zone_id}")
          |> filter(fn: (r) => r["node_id"] == "{node_id}")
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "humidity")
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
                humidity = values.get("humidity")
                record_time = record.get_time()

                points.append(
                    TrendPoint(
                        timestamp=record_time,
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
            base = -19.2 if zone_id == "zone_a" else 2.0
            while stamp < end:
                if len(rows) >= max_records:
                    raise ValueError("Reading limit exceeded")
                rows.append({"timestamp": stamp, "temp_c": base + 0.2 * math.sin(len(rows)/7),
                             "humidity": 80.0, "source": "MOCK"})
                stamp += timedelta(minutes=1)
            return rows
        query = f'''from(bucket: {json.dumps(settings.INFLUX_BUCKET)})
          |> range(start: time(v: {json.dumps(start.isoformat())}), stop: time(v: {json.dumps(end.isoformat())}))
          |> filter(fn: (r) => r["_measurement"] == "zone_environment" and r["zone_id"] == {json.dumps(zone_id)})
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
                             "source": record.values.get("source", "unknown")})
                if len(rows) > max_records:
                    raise ValueError("Reading limit exceeded")
        return rows

    # Safe Mock Generators for Offline Testing (Simulating 4 Corner Nodes per Zone)
    def _generate_mock_nodes(self, zone_id: Optional[str] = None, node_id: Optional[str] = None) -> List[NodeReading]:
        now = datetime.now(timezone.utc)
        target_zones = [zone_id] if zone_id else ["zone_a", "zone_b"]
        all_node_ids = ["node_1", "node_2", "node_3", "node_4"]
        target_nodes = [n for n in all_node_ids if n == node_id] if node_id else all_node_ids

        nodes: List[NodeReading] = []
        for z_id in target_zones:
            base_temp = -19.3 if z_id == "zone_a" else 2.1
            base_hum = 82.4 if z_id == "zone_a" else 78.5
            for n_id in target_nodes:
                temp = round(base_temp + random.uniform(-0.4, 0.4), 2)
                hum = round(base_hum + random.uniform(-1.5, 1.5), 1)
                nodes.append(
                    NodeReading(
                        node_id=n_id,
                        zone_id=z_id,
                        name=NODE_NAMES.get(n_id, f"Sensor Node ({n_id})"),
                        temp_c=temp,
                        humidity=hum,
                        power_ok=True,
                        source="LIVE",
                        status=ComplianceStatus.NORMAL,
                        timestamp=now,
                    )
                )
        return nodes

    def _generate_mock_live(self) -> List[LiveZoneReading]:
        now = datetime.now(timezone.utc)
        results: List[LiveZoneReading] = []

        for z_id in ["zone_a", "zone_b"]:
            zone_nodes = self._generate_mock_nodes(zone_id=z_id)
            avg_temp = round(sum(n.temp_c for n in zone_nodes if n.temp_c is not None) / len(zone_nodes), 2)
            avg_hum = round(sum(n.humidity for n in zone_nodes if n.humidity is not None) / len(zone_nodes), 1)

            results.append(
                LiveZoneReading(
                    zone_id=z_id,
                    name=ZONE_NAMES.get(z_id, f"Storage Zone ({z_id})"),
                    temp_c=avg_temp,
                    humidity=avg_hum,
                    power_ok=True,
                    source="LIVE",
                    status=ComplianceStatus.NORMAL,
                    timestamp=now,
                    nodes=zone_nodes,
                )
            )
        return results

    def _generate_mock_trend(self, zone_id: str, hours: int, node_id: Optional[str] = None) -> List[TrendPoint]:
        points: List[TrendPoint] = []
        now = datetime.now(timezone.utc)
        interval_minutes = 5
        total_points = (hours * 60) // interval_minutes
        base_temp = -19.2 if zone_id == "zone_a" else 2.0
        # Slight per-node offset in mock mode so individual node curves look distinct
        node_offsets = {"node_1": -0.15, "node_2": 0.10, "node_3": -0.05, "node_4": 0.20}
        offset = node_offsets.get(node_id, 0.0) if node_id else 0.0

        for i in range(total_points, -1, -1):
            point_time = now - timedelta(minutes=i * interval_minutes)
            temp = round(base_temp + offset + random.uniform(-0.6, 0.6), 2)
            hum = round(80.0 + random.uniform(-3.0, 3.0), 1)
            points.append(TrendPoint(timestamp=point_time, temp_c=temp, humidity=hum))

        return points

# Singleton instance for import across backend
influx_service = InfluxService()
