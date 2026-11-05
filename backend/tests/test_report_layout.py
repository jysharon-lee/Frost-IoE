import unittest
from datetime import datetime, timezone
from io import BytesIO
from pypdf import PdfReader
from reporting import build_pdf, report_time


class ReportPresentationTests(unittest.TestCase):
    def test_malaysia_time_rolls_into_next_day(self):
        self.assertEqual(report_time(datetime(2026, 11, 1, 20, tzinfo=timezone.utc)),
                         "02 Nov 2026, 04:00:00")

    def test_report_excludes_reading_at_end_boundary(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        end = datetime(2026, 11, 2, tzinfo=timezone.utc)
        rows = [{"timestamp": start, "temp_c": -20},
                {"timestamp": end, "temp_c": 99}]
        pdf = build_pdf(rows, "3", "Pilot facility", start, end, -18, False)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertNotIn("99.00", text)
        self.assertIn("01 Nov 2026, 08:00:00", text)
        self.assertIn("No recorded temperatures were above", text)


if __name__ == "__main__":
    unittest.main()
