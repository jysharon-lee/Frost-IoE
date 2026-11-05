"""Fill the styled audit template from the same observations used by the PDF."""
from datetime import datetime, timezone
from io import BytesIO
from math import isfinite
from pathlib import Path
from secrets import token_urlsafe
from statistics import mean
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.formatting.rule import FormulaRule
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.workbook.protection import WorkbookProtection
from reporting import MYT, report_series
from analytics import excursions

DATE_FORMAT = "dd mmm yyyy, hh:mm:ss"
REASONS = {"data_gap": "Gap in readings", "next_sample_within_limit": "Next reading within limit",
           "ongoing_or_end_of_range": "No return within limit recorded"}


def put(sheet, row, col, value):
    cell = sheet.cell(row, col)
    cell.value = value
    # User/source strings must never become executable spreadsheet formulas.
    if isinstance(value, str):
        cell.data_type = "s"
    elif isinstance(value, datetime):
        cell.number_format = DATE_FORMAT
    elif isinstance(value, float):
        cell.number_format = "0.00"
    cell.font = Font(name="Arial", size=10, color="243746")
    cell.alignment = Alignment(vertical="center", indent=1,
                               horizontal="right" if isinstance(value, (int, float, datetime)) else "left")


def local(value):
    return value.astimezone(MYT).replace(tzinfo=None)


def data_table(sheet, name, header, last, columns):
    if last <= header:
        put(sheet, header + 1, 1, "No records available")
        return
    table = Table(displayName=name, ref=f"A{header}:{columns}{last}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)
    sheet.print_title_rows = f"1:{header}"


def build_excel(rows, zone_id, facility, start, end, limit, mock, *, generated_at=None, observed_until=None):
    generated_at = generated_at or datetime.now(timezone.utc)
    observed_until = observed_until or min(end, generated_at)
    wb = load_workbook(Path(__file__).with_name("templates") / "audit-template.xlsx")
    summary, readings, events, review = [wb[name] for name in ("Summary", "Readings", "Events", "Review")]
    for column, width in zip("ABCDEFGHI", [30, 17, 16, 16, 16, 27, 27, 17, 23]):
        summary.column_dimensions[column].width = width
    review.column_dimensions["A"].width = 24
    grouped = report_series(rows, start, observed_until)
    usable_count = sum(len(points) for _, _, points in grouped)
    records = sorted([row for _, values, _ in grouped for row in values], key=lambda row: row["timestamp"])
    metadata = [facility, zone_id, local(start), local(end), local(generated_at), local(observed_until),
                "Partial - selected period has not ended" if end > generated_at else "Selected period has ended",
                "SIMULATED DATA - demonstration only" if mock else "Recorded data", limit,
                len(records), usable_count, len(records) - usable_count]
    for i, value in enumerate(metadata, 5):
        put(summary, i, 2, value)
    # Longer metadata values have reserved space beside the label.
    for r in (5, 6, 7, 8, 9, 10, 11, 12):
        summary.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        summary.cell(r, 2).alignment = Alignment(horizontal="left", vertical="center", indent=1)
    summary["B11"].fill = PatternFill("solid", fgColor="FFF3D6" if end > generated_at else "FFFFFF")
    sr, rr, er = 20, 6, 6
    for identity, values, points in grouped:
        title = "Zone readings" if identity == "zone_aggregate" else identity
        temps = [temp for _, temp in points]
        gaps = sum((b[0] - a[0]).total_seconds() > 180 for a, b in zip(points, points[1:]))
        stats = [title, len(points), min(temps) if temps else None, max(temps) if temps else None,
                 mean(temps) if temps else None, local(points[0][0]) if points else None,
                 local(points[-1][0]) if points else None, gaps, sum(temp > limit for temp in temps)]
        for col, value in enumerate(stats, 1):
            put(summary, sr, col, value)
        sr += 1
        for event in excursions(points, limit):
            values_out = [title, local(event["start"]), local(event["last_observed"]),
                          event["observed_minutes"], event["peak_c"], REASONS[event["end_reason"]]]
            for col, value in enumerate(values_out, 1):
                put(events, er, col, value)
            er += 1
    point_sets = {identity: dict(points) for identity, _, points in grouped}
    used = set()
    for number, record in enumerate(records, 1):
        stamp = record["timestamp"]
        identity = record.get("sensor_id") or record.get("node_id") or "zone_aggregate"
        temp = record.get("temp_c")
        key = identity, stamp
        if temp is None or not isfinite(temp):
            quality = "Excluded - invalid temperature"
        elif stamp not in point_sets[identity]:
            quality = "Excluded - conflicting values"
        elif key in used:
            quality = "Repeated - counted once"
        else:
            quality = "Used"
            used.add(key)
        values_out = [number, local(stamp), stamp.astimezone(timezone.utc).replace(tzinfo=None),
                      record.get("sensor_id") or "", record.get("node_id") or "",
                      "Zone readings" if identity == "zone_aggregate" else identity,
                      temp if temp is None or isfinite(temp) else str(temp), record.get("source", "unknown"), quality]
        for col, value in enumerate(values_out, 1):
            put(readings, rr, col, value)
        rr += 1
    data_table(summary, "SensorSummary", 19, sr - 1, "I")
    data_table(readings, "TemperatureRecords", 5, rr - 1, "I")
    data_table(events, "HighTemperatureEvents", 5, er - 1, "F")
    if rr > 6:
        readings.conditional_formatting.add(f"G6:G{rr-1}", FormulaRule(
            formula=[f"AND(ISNUMBER(G6),G6>{limit:g})"], fill=PatternFill("solid", fgColor="FDE9E7")))
    notes = ["Reading times use MYT (UTC+8). UTC timestamps are also preserved on Readings.",
             "From is included. Until is excluded. Future readings are never generated by this export.",
             "History queried until is a query boundary, not proof of continuous sensor coverage.",
             "Counts and averages use valid, unique readings per series. Conflicting timestamps are excluded.",
             "Average means the arithmetic mean of readings, not a time-weighted average.",
             "Gaps count intervals longer than 3 minutes between usable readings. Boundary gaps are not counted.",
             "Event spans use the first and last high reading. They do not prove exact exposure duration.",
             "This is a protected snapshot. Re-export for new results. Keep review notes in a separate log.",
             "Air temperatures alone do not prove product safety, legal compliance or record authenticity.",
             "Export row numbers identify rows in this file only. Keep original database and calibration records."]
    note_start = sr + 2
    for i, note in enumerate(notes, note_start):
        put(summary, i, 1, note)
        summary.merge_cells(start_row=i, start_column=1, end_row=i, end_column=9)
        summary.cell(i, 1).alignment = Alignment(wrap_text=True, vertical="center")
        summary.row_dimensions[i].height = 25
    put(readings, 4, 1, "Source: FROST-IoE returned temperature history. SIMULATED DATA." if mock else
        "Source: InfluxDB zone_environment, temp_c field. Invalid temperature records may be absent upstream.")
    readings.merge_cells("A4:I4")
    put(events, 4, 1, "Spans between high readings only. Gaps >3 min split events. Separate from confirmed alarms.")
    events.merge_cells("A4:F4")
    review.merge_cells("A4:G4")
    review.merge_cells("A25:G25")
    for r in range(6, 10):
        review.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
    review["B7"].number_format = DATE_FORMAT
    review["A9"] = "Evidence reference"
    put(review, 4, 1, "Read-only review snapshot. No manual review has been recorded in this export.")
    put(review, 25, 1, "Keep findings and follow-up actions in a separate review log. Refer to this report's dates and zone.")
    for area in ("B6:D9", "A13:G22"):
        for cells in review[area]:
            for cell in cells:
                cell.fill = PatternFill(fill_type=None)
    put(review, 8, 2, "Not reviewed")
    password = token_urlsafe(32)
    wb.security = WorkbookProtection(workbookPassword=password, lockStructure=True)
    for sh in wb:
        for cells in sh:
            for cell in cells:
                cell.protection = Protection(locked=True)
        sh.protection.sheet = True
        sh.protection.set_password(password)
        # Existing filters and keyboard navigation remain usable in read-only sheets.
        sh.protection.autoFilter = False
        sh.protection.selectLockedCells = False
        sh.protection.selectUnlockedCells = False
        sh.sheet_view.showGridLines = False
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.page_setup.orientation = "landscape"
        sh.page_setup.paperSize = sh.PAPERSIZE_A4
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
        sh.print_options.horizontalCentered = True
        sh.print_area = sh.dimensions
        sh.oddFooter.center.text = "FROST-IoE - " + ("SIMULATED DATA" if mock else "Recorded temperatures")
        sh.oddFooter.right.text = "Page &P of &N"
    wb.properties.title = "FROST-IoE Temperature Audit Report"
    wb.properties.creator = "FROST-IoE"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
