import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from main import app
from influx_client import influx_service
from excel_reporting import build_excel

NOW = datetime.now(timezone.utc)


class AuditExportTests(unittest.TestCase):
    def test_excel_preserves_records_and_excludes_conflicts_from_summary(self):
        start = NOW-timedelta(hours=1)
        rows = [{"timestamp": start, "temp_c": -20, "source": "LIVE", "sensor_id": "=1+1"},
                {"timestamp": start, "temp_c": -20, "source": "BACKFILL", "sensor_id": "=1+1"},
                {"timestamp": start+timedelta(minutes=1), "temp_c": -17, "sensor_id": "=1+1"},
                {"timestamp": start+timedelta(minutes=1), "temp_c": -16, "sensor_id": "=1+1"},
                {"timestamp": start+timedelta(minutes=2), "temp_c": None, "sensor_id": "=1+1"},
                {"timestamp": NOW, "temp_c": 99}]
        data = build_excel(rows, "3", "=HYPERLINK(\"bad\")", start, NOW, -18, True, generated_at=NOW)
        wb = load_workbook(BytesIO(data))
        self.assertEqual(wb.sheetnames, ["Summary", "Readings", "Events", "Review"])
        self.assertEqual(wb['Summary']['B14'].value, 5)
        self.assertEqual(wb['Summary']['B15'].value, 1)
        self.assertEqual(wb['Summary']['B16'].value, 4)
        self.assertEqual(wb['Summary']['B5'].data_type, 's')
        self.assertEqual(wb['Readings']['D6'].data_type, 's')
        expected_time = start.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        self.assertLess(abs((wb['Readings']['B6'].value-expected_time).total_seconds()), .001)
        self.assertEqual(wb['Readings']['I7'].value, 'Repeated - counted once')
        self.assertEqual(wb['Readings']['I8'].value, 'Excluded - conflicting values')
        self.assertEqual(wb['Review']['B8'].value, 'Not reviewed')
        self.assertEqual(wb['Readings'].freeze_panes, 'A6')
        self.assertEqual(len(wb['Readings'].tables), 1)
        self.assertFalse(any(cell.data_type == 'f' for sh in wb for row in sh for cell in row))

    def test_future_end_exports_partial_and_caps_query_at_now(self):
        client = TestClient(app)
        params = {'zone_id': '3', 'start': (NOW-timedelta(hours=1)).isoformat(),
                  'end': (NOW+timedelta(days=1)).isoformat()}
        for kind in ('pdf', 'excel'):
            with patch.object(influx_service, 'get_raw_readings', return_value=[]) as query:
                result = client.get('/api/reports/export-'+kind, params=params)
            self.assertEqual(result.status_code, 200)
            self.assertLess(query.call_args.args[2], NOW+timedelta(minutes=1))
            if kind == 'excel':
                wb = load_workbook(BytesIO(result.content))
                self.assertIn('Partial', wb['Summary']['B11'].value)
            else:
                text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(result.content)).pages)
                self.assertIn('PARTIAL REPORT', text)
        params['start'] = (NOW+timedelta(hours=1)).isoformat()
        self.assertEqual(client.get('/api/reports/export-excel', params=params).status_code, 422)
        self.assertIn('datetime-local', client.get('/api/reports').text)


if __name__ == '__main__':
    unittest.main()
