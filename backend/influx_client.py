import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

from config import settings
from schemas import ComplianceStatus, LiveZoneReading, TrendPoint

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

    def get_live_readings(self) -> List[LiveZoneReading]:
        """Query 1: Fetches the most recent reading for each zone using last() and pivot()."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_live()

        flux_query = f'''
        from(bucket: "{settings.INFLUX_BUCKET}")
          |> range(start: -2h)
          |> filter(fn: (r) => r["_measurement"] == "zone_environment")
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "humidity" or r["_field"] == "power_ok")
          |> last()
          |> pivot(rowKey: ["_time", "zone_id"], columnKey: ["_field"], valueColumn: "_value")
        '''

        query_api = self.get_query_api()
        tables = query_api.query(flux_query, org=settings.clean_org)

        results: List[LiveZoneReading] = []
        zone_names = {
            "zone_a": "Freezer Room A (Frozen Poultry)",
            "zone_b": "Chilled Room B (Fresh Poultry)",
            "zone_c": "Loading Dock (Buffer)",
        }

        for table in tables:
            for record in table.records:
                values = record.values
                zone_id = values.get("zone_id", "unknown")
                temp_c = values.get("temp_c")
                humidity = values.get("humidity")
                power_ok = values.get("power_ok", True)
                source = values.get("source", "LIVE")
                record_time = record.get_time()

                results.append(
                    LiveZoneReading(
                        zone_id=zone_id,
                        name=zone_names.get(zone_id, f"Storage Zone ({zone_id})"),
                        temp_c=round(float(temp_c), 2) if temp_c is not None else None,
                        humidity=round(float(humidity), 2) if humidity is not None else None,
                        power_ok=bool(power_ok),
                        source=str(source),
                        status=self.calculate_status(temp_c),
                        timestamp=record_time if record_time else datetime.now(timezone.utc),
                    )
                )

        return results

    def get_zone_trend(self, zone_id: str, hours: int = 24) -> List[TrendPoint]:
        """Query 2: Fetches historical trend downsampled to 5-minute averages using aggregateWindow."""
        if settings.USE_MOCK_DATA:
            return self._generate_mock_trend(zone_id, hours)

        flux_query = f'''
        from(bucket: "{settings.INFLUX_BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_measurement"] == "zone_environment")
          |> filter(fn: (r) => r["zone_id"] == "{zone_id}")
          |> filter(fn: (r) => r["_field"] == "temp_c" or r["_field"] == "humidity")
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''

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

    # Safe Mock Generators for Offline Testing 
    def _generate_mock_live(self) -> List[LiveZoneReading]:
        now = datetime.now(timezone.utc)
        return [
            LiveZoneReading(
                zone_id="zone_a",
                name="Freezer Room A (Frozen Poultry)",
                temp_c=round(-19.3 + random.uniform(-0.3, 0.3), 2),
                humidity=round(82.4 + random.uniform(-1.0, 1.0), 1),
                power_ok=True,
                source="LIVE",
                status=ComplianceStatus.NORMAL,
                timestamp=now,
            ),
            LiveZoneReading(
                zone_id="zone_b",
                name="Chilled Room B (Fresh Poultry)",
                temp_c=round(2.1 + random.uniform(-0.2, 0.2), 2),
                humidity=round(78.5 + random.uniform(-1.5, 1.5), 1),
                power_ok=True,
                source="LIVE",
                status=ComplianceStatus.NORMAL,
                timestamp=now,
            ),
        ]

    def _generate_mock_trend(self, zone_id: str, hours: int) -> List[TrendPoint]:
        points = []
        now = datetime.now(timezone.utc)
        interval_minutes = 5
        total_points = (hours * 60) // interval_minutes
        base_temp = -19.2 if zone_id == "zone_a" else 2.0

        for i in range(total_points, -1, -1):
            point_time = now - timedelta(minutes=i * interval_minutes)
            temp = round(base_temp + random.uniform(-0.6, 0.6), 2)
            hum = round(80.0 + random.uniform(-3.0, 3.0), 1)
            points.append(TrendPoint(timestamp=point_time, temp_c=temp, humidity=hum))

        return points

# Singleton instance for import across backend
influx_service = InfluxService()