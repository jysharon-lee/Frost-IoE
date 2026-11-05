"""Readable summaries of observed temperatures; no compliance certification."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from secrets import token_urlsafe
from statistics import mean
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from analytics import clean_points, excursions

MYT = timezone(timedelta(hours=8), "MYT")


def report_time(value):
    return value.astimezone(MYT).strftime("%d %b %Y, %H:%M:%S")


def report_series(rows, start, end):
    """One cleaning rule for PDF and Excel statistics, with an exclusive end."""
    grouped = defaultdict(list)
    for row in rows:
        if start <= row["timestamp"] < end:
            grouped[row.get("sensor_id") or row.get("node_id") or "zone_aggregate"].append(row)
    return [(identity, values, clean_points(values, start, end))
            for identity, values in sorted(grouped.items())]


def build_pdf(rows, zone_id, facility, start, end, limit, mock, *, generated_at=None, observed_until=None):
    generated_at = generated_at or datetime.now(timezone.utc)
    observed_until = observed_until or min(end, generated_at)
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("ReportBody", fontName="Helvetica", fontSize=9,
                              leading=13, spaceAfter=7, textColor=colors.HexColor("#334155")))
    styles["Title"].fontSize = 23
    styles["Title"].leading = 28
    styles["Title"].alignment = 0
    styles["Title"].textColor = colors.HexColor("#153e52")
    styles["Heading2"].textColor = colors.HexColor("#153e52")
    story = []

    def cell(text):
        return Paragraph(str(text), styles["ReportBody"])

    def paragraph(text):
        story.append(cell(text))

    def table(data, widths, header=True):
        grid = LongTable([[cell(value) for value in row] for row in data],
                         colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
        commands = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#d9e2e8"))]
        if header:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0f4")))
        grid.setStyle(TableStyle(commands))
        story.append(grid)
        story.append(Spacer(1, 10))

    paragraph("<b>FROST-IoE / MONITORING REPORT</b>")
    story.append(Paragraph("Temperature report", styles["Title"]))
    if mock:
        paragraph("<b>DEMONSTRATION ONLY - SYNTHETIC MOCK DATA</b><br/>"
                  "These are simulated readings, not measurements from a real facility.")
    table([
        ["<b>Facility</b>", escape(facility), "<b>Zone</b>", escape(zone_id)],
        ["<b>From</b>", report_time(start), "<b>Until</b>", report_time(end)],
        ["<b>Created</b>", report_time(generated_at),
         "<b>Upper limit</b>", f"{limit:g} &deg;C"],
    ], [60, 194, 65, 196], header=False)
    paragraph("All times use Malaysia time (MYT, UTC+8), in 24-hour format. "
              "The report includes readings at or after From and before Until. "
              "Created is the time this PDF was made.")
    if end > generated_at:
        paragraph("<b>PARTIAL REPORT - the selected period has not ended.</b><br/>"
                  f"History was queried until {report_time(observed_until)} MYT. "
                  "Future readings are not included. Export again after the period ends.")
    else:
        paragraph("<b>Selected period has ended.</b> This does not confirm that all readings are present.")
    grouped = report_series(rows, start, observed_until)
    if not grouped:
        paragraph("No readings were available for the selected period.")
    for identity, values, points in grouped:
        title = "Zone readings" if identity == "zone_aggregate" else "Sensor: " + escape(identity)
        story.append(Paragraph(title, styles["Heading2"]))
        if not points:
            paragraph("No valid temperature readings were available for this period.")
            continue
        temps = [value for _, value in points]
        gaps = sum((b[0] - a[0]).total_seconds() > 180 for a, b in zip(points, points[1:]))
        table([["<b>Readings</b>", "<b>Lowest</b>", "<b>Highest</b>", "<b>Average</b>"],
               [str(len(points)), f"{min(temps):.2f} &deg;C", f"{max(temps):.2f} &deg;C", f"{mean(temps):.2f} &deg;C"]],
              [128, 129, 129, 129])
        paragraph(f"<b>First reading:</b> {report_time(points[0][0])}<br/>"
                  f"<b>Last reading:</b> {report_time(points[-1][0])}<br/>"
                  f"<b>Gaps longer than 3 minutes between readings:</b> {gaps}")
        counts = defaultdict(int)
        source_names = {"MOCK": "Simulated", "LIVE": "Live", "BACKFILL": "Uploaded later"}
        for row in values:
            source = str(row.get("source", "unknown"))
            counts[source_names.get(source, source)] += 1
        paragraph("<b>Source records:</b> " + escape(", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))))
        story.append(Paragraph("Readings above the limit", styles["Heading3"]))
        paragraph("Times below measure the span between recorded readings above the limit, "
                  "not the exact time the temperature stayed high. One reading gives a span of 0 minutes. "
                  "A gap longer than 3 minutes starts a new event. "
                  "This table is separate from the system's 5-minute confirmed-alarm rule.")
        reasons = {"data_gap": "Gap in readings", "next_sample_within_limit": "Next reading within limit",
                   "ongoing_or_end_of_range": "No return within limit recorded"}
        events = excursions(points, limit)
        if events:
            table([["<b>First high reading</b>", "<b>Recorded span (min)</b>", "<b>Peak (&deg;C)</b>", "<b>How it ended</b>"]] +
                  [[report_time(event["start"]), f'{event["observed_minutes"]:.1f}',
                    f'{event["peak_c"]:.2f}', escape(reasons[event["end_reason"]])] for event in events],
                  [154, 98, 72, 191])
        else:
            paragraph("No recorded temperatures were above the selected limit.")
    story.append(Paragraph("Remarks:", styles["Heading2"]))
    paragraph("This report shows recorded air temperatures only. It does not confirm that products are safe "
              "or that legal requirements were met, and it does not verify that the source records are authentic. "
              "Missing readings leave periods we cannot assess. The exact time spent above the limit is unknown. "
              "Readings uploaded later (backfill) are included when available.")

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#d9e2e8"))
        canvas.line(40, 37, 555, 37)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(40, 25, "FROST-IoE | MYT (UTC+8) | " + ("Simulated data" if mock else "Recorded temperatures"))
        canvas.drawRightString(555, 25, f"Page {doc.page}")

    permissions = StandardEncryption(userPassword="", ownerPassword=token_urlsafe(32),
                                     canPrint=1, canModify=0, canCopy=0, canAnnotate=0, strength=128)
    SimpleDocTemplate(output, encrypt=permissions, pagesize=(595.28, 841.89), rightMargin=40, leftMargin=40,
                      topMargin=36, bottomMargin=50, title="FROST-IoE Temperature Report").build(
                          story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
