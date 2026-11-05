import unittest
from datetime import datetime, timezone, timedelta
from io import BytesIO
from openpyxl import load_workbook
from pypdf import PdfReader
from reporting import build_pdf
from excel_reporting import build_excel


class ExportProtectionTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.args = ([], 'zone_a', 'Test', self.start, self.start+timedelta(days=1), -18, True)

    def test_workbook_and_all_sheets_are_protected(self):
        wb = load_workbook(BytesIO(build_excel(*self.args)))
        self.assertTrue(wb.security.lockStructure)
        self.assertTrue(wb.security.workbookPassword)
        for sh in wb:
            self.assertTrue(sh.protection.sheet)
            self.assertTrue(sh.protection.password)
            self.assertTrue(all(cell.protection.locked for row in sh for cell in row))
        self.assertIn('Read-only', wb['Review']['A4'].value)
        self.assertIn('separate review log', wb['Review']['A25'].value)

    def test_pdf_opens_without_password_and_has_restricted_permissions(self):
        reader = PdfReader(BytesIO(build_pdf(*self.args)))
        self.assertTrue(reader.is_encrypted)
        self.assertTrue(reader.decrypt(''))
        self.assertIn('Remarks:', reader.pages[0].extract_text())
        flags = int(reader.trailer['/Encrypt']['/P'])
        self.assertTrue(flags & 4)  # Printing allowed.
        self.assertFalse(flags & 8)  # Modify.
        self.assertFalse(flags & 16)  # Copy.
        self.assertFalse(flags & 32)  # Annotate.


if __name__ == '__main__':
    unittest.main()
