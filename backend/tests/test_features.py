import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from pypdf import PdfReader
from analytics import forecast, sensor_health, excursions, clean_points
from influx_client import influx_service
from main import app
from reporting import build_pdf

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)

def series(minutes=15, start=-20, slope=0.0, sensor=None):
    return [{"timestamp": NOW-timedelta(minutes=minutes-i), "temp_c": start+slope*i,
             "sensor_id": sensor, "source": "LIVE"} for i in range(minutes+1)]

class AnalyticsTests(unittest.TestCase):
    def test_rise_and_projection(self):
        result = forecast(series(10,-20,0.1), NOW,-18)
        self.assertAlmostEqual(result["rate_c_per_hour"],6)
        self.assertAlmostEqual(result["minutes_to_limit"],10)
        self.assertTrue(result["early_warning"])

    def test_cooling_and_breach(self):
        self.assertIsNone(forecast(series(10,-20,-0.1),NOW,-18)["minutes_to_limit"])
        result=forecast(series(10,-17,-0.01),NOW,-18)
        self.assertEqual(result["status"],"breached")
        self.assertEqual(result["minutes_to_limit"],0)

    def test_gap_and_stale(self):
        rows=series(10)
        self.assertEqual(forecast(rows[:3]+rows[7:],NOW,-18)["reason"],"data_gap")
        self.assertEqual(forecast(rows,NOW+timedelta(minutes=4),-18)["reason"],"stale_data")
        self.assertEqual(forecast([],NOW,-18)["reason"],"insufficient_data")

    def test_duplicates_and_invalid(self):
        rows=series(10)
        rows += [rows[0], {"timestamp":NOW,"temp_c":float("nan")}]
        self.assertEqual(len(clean_points(rows,NOW-timedelta(minutes=10),NOW)),11)
        rows += [{"timestamp": NOW,"temp_c":99}]
        self.assertEqual(len(clean_points(rows,NOW-timedelta(minutes=10),NOW)),10)

    def test_flatline_and_missing_identity(self):
        item=sensor_health(series(),NOW,{})[0]
        self.assertTrue(item["flatline_suspected"])
        self.assertIsNone(item["drift_suspected"])
        self.assertEqual(item["scope"],"zone")
        self.assertFalse(sensor_health(series(slope=0.1),NOW,{})[0]["flatline_suspected"])

    def test_six_hour_baseline_drift(self):
        rows=series(360,-20,0,"a")+series(360,-18.5,0,"b")
        result=sensor_health(rows,NOW,{"a":0,"b":0})
        self.assertTrue(all(x["drift_suspected"] for x in result))
        result=sensor_health(rows,NOW,{"a":0,"b":1.5})
        self.assertTrue(all(x["drift_suspected"] is False for x in result))
        self.assertIsNone(sensor_health(rows[:10],NOW,{"a":0})[0]["drift_suspected"])

    def test_excursions_do_not_bridge_gaps(self):
        points=[(NOW-timedelta(minutes=10),-17),(NOW-timedelta(minutes=9),-17),(NOW,-16)]
        events=excursions(points,-18)
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]["observed_minutes"],1)
        self.assertEqual(events[1]["observed_minutes"],0)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)

    def test_forecast_endpoint(self):
        with patch.object(influx_service,"get_raw_readings",return_value=[]):
            result=self.client.get("/api/forecast",params={"zone_id":"zone_a"})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["status"],"unavailable")
        self.assertEqual(self.client.get("/api/forecast").status_code,422)
        self.assertEqual(self.client.get("/api/forecast",params={"zone_id":"a","limit_c":"nan"}).status_code,422)

    def test_health_endpoint_and_safe_errors(self):
        with patch.object(influx_service,"get_raw_readings",return_value=[]):
            self.assertEqual(self.client.get("/api/sensor-health",params={"zone_id":"a"}).json()["status"],"no_data")
        with patch.object(influx_service,"get_raw_readings",side_effect=RuntimeError("secret token")):
            result=self.client.get("/api/forecast",params={"zone_id":"a"})
        self.assertEqual(result.status_code,503)
        self.assertNotIn("secret",result.text)

    def test_pdf_endpoint_and_dates(self):
        params={"zone_id":"a","start":"2026-10-31T00:00:00Z","end":"2026-11-01T00:00:00Z"}
        with patch.object(influx_service,"get_raw_readings",return_value=[]):
            result=self.client.get("/api/reports/export-pdf",params=params)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers["content-type"],"application/pdf")
        text=PdfReader(BytesIO(result.content)).pages[0].extract_text()
        self.assertIn("SYNTHETIC MOCK DATA",text)
        self.assertIn("No readings",text)
        for updates in [{"start":"2026-10-31T00:00:00"},{"end":params["start"]},{"start":"2026-01-01T00:00:00Z"}]:
            self.assertEqual(self.client.get("/api/reports/export-pdf",params=params|updates).status_code,422)
        with patch.object(influx_service,"get_raw_readings",side_effect=ValueError()):
            self.assertEqual(self.client.get("/api/reports/export-pdf",params=params).status_code,413)

    def test_pdf_multipage_and_escape(self):
        rows=series(360,-17,0,"sensor <one>")
        # Alternate readings so every second sample produces a separate excursion.
        for i,row in enumerate(rows):
            row["temp_c"] = -17 if i%2 else -20
        pdf=build_pdf(rows,"<zone>","A & B <site>",NOW-timedelta(hours=6),NOW,-18,False)
        reader=PdfReader(BytesIO(pdf))
        self.assertGreater(len(reader.pages),1)
        self.assertIn("A & B <site>",reader.pages[0].extract_text())

    def test_raw_query_validates_identifier(self):
        with self.assertRaises(ValueError):
            influx_service.get_raw_readings('x" |> die()',NOW-timedelta(minutes=10),NOW)
        api=MagicMock();api.query.return_value=[]
        with patch("influx_client.settings.USE_MOCK_DATA",False), patch.object(influx_service,"get_query_api",return_value=api):
            influx_service.get_raw_readings("zone_a",NOW-timedelta(minutes=10),NOW)
        query=api.query.call_args.args[0]
        self.assertNotIn("aggregateWindow",query)
        self.assertIn('r["zone_id"] == "zone_a"',query)
        self.assertEqual(self.client.get("/api/forecast",params={"zone_id":"${bad}"}).status_code,422)

    def test_record_cap_including_invalid_samples(self):
        record=MagicMock();record.get_value.return_value=None
        table=MagicMock();table.records=[record]*50001
        api=MagicMock();api.query.return_value=[table]
        with patch("influx_client.settings.USE_MOCK_DATA",False), patch.object(influx_service,"get_query_api",return_value=api):
            with self.assertRaises(ValueError):
                influx_service.get_raw_readings("zone_a",NOW-timedelta(minutes=10),NOW)

    def test_short_peer_history_is_not_healthy(self):
        rows=series(360,-20,0,"a")+series(10,-18,0,"b")
        self.assertTrue(all(x["drift_suspected"] is None for x in sensor_health(rows,NOW,{"a":0,"b":0})))

if __name__ == "__main__":
    unittest.main()
