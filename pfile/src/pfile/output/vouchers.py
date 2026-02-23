"""Generate payment vouchers (Form 1040-V and NY IT-201-V) using ReportLab."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from pfile.models.session import FilingSession

_BLUE = colors.HexColor("#1a3a6b")
_LIGHT_BLUE = colors.HexColor("#e8f0fb")
_GRAY = colors.HexColor("#6c757d")
_BLACK = colors.black


def _fmt(d: Decimal) -> str:
    return f"${d:,.2f}"


def _box_table(rows: list[list[str]], col_widths: list) -> Table:
    style = TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, _BLACK),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#aaaaaa")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4ff")),
    ])
    return Table(rows, colWidths=col_widths, style=style)


def _cut_here(styles) -> list:
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=_GRAY)
    return [
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.5, color=_GRAY, dash=(3, 3)),
        Paragraph("✂  Cut here and mail with your payment  ✂", small),
        Spacer(1, 10),
    ]


def generate_1040v(
    session: FilingSession,
    amount_due: Decimal,
    output_path: Path,
) -> Path:
    """Render a Form 1040-V style payment voucher."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=_BLUE, fontSize=16, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], textColor=_BLUE, fontSize=10, spaceBefore=8, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, textColor=_GRAY, leading=12)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )

    story = []
    story.append(Paragraph("Form 1040-V — Payment Voucher", h1))
    story.append(Paragraph(
        f"Department of the Treasury — Internal Revenue Service &nbsp;|&nbsp; Tax Year {session.tax_year}",
        small,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        "Use this voucher only if you are making a paper check or money order payment. "
        "Do not staple or attach this voucher to your payment.",
        ParagraphStyle("note", parent=styles["Normal"], fontSize=9, leading=13),
    ))

    for item in _cut_here(styles):
        story.append(item)

    primary = session.primary
    ssn = primary.ssn if primary else ""
    full_name = session.display_name

    row_data = [
        ["Tax Year", str(session.tax_year)],
        ["Amount Enclosed", _fmt(amount_due)],
        ["Your SSN", ssn],
        ["Name", full_name],
        ["Address", _session_address(session)],
    ]
    story.append(_box_table(row_data, [2 * inch, 4.2 * inch]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("How to complete your payment:", h3))
    instructions = [
        f"1. Make check or money order payable to: <b>United States Treasury</b>",
        f"2. Write on memo line: <b>{ssn} — {session.tax_year} — Form 1040</b>",
        "3. Mail WITH this voucher to the address on your cover sheet.",
        "4. Do NOT send cash. Do NOT staple the check to your return.",
    ]
    for line in instructions:
        story.append(Paragraph(line, ParagraphStyle("inst", parent=styles["Normal"], fontSize=9, leading=14, leftIndent=8)))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Online alternative: Pay free at <b>irs.gov/directpay</b> (no voucher needed).",
        ParagraphStyle("tip", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#155724")),
    ))

    doc.build(story)
    return output_path


def generate_it201v(
    session: FilingSession,
    amount_due: Decimal,
    output_path: Path,
) -> Path:
    """Render a Form IT-201-V style NY payment voucher."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=_BLUE, fontSize=16, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], textColor=_BLUE, fontSize=10, spaceBefore=8, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, textColor=_GRAY, leading=12)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )

    story = []
    story.append(Paragraph("Form IT-201-V — Payment Voucher", h1))
    story.append(Paragraph(
        f"New York State Department of Taxation and Finance &nbsp;|&nbsp; Tax Year {session.tax_year}",
        small,
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph(
        "Use this voucher only if you are mailing a paper check or money order. "
        "Do not staple or attach this voucher to your IT-201 return.",
        ParagraphStyle("note", parent=styles["Normal"], fontSize=9, leading=13),
    ))

    for item in _cut_here(styles):
        story.append(item)

    primary = session.primary
    ssn = primary.ssn if primary else ""
    full_name = session.display_name

    row_data = [
        ["Tax Year", str(session.tax_year)],
        ["Amount Enclosed", _fmt(amount_due)],
        ["Your SSN", ssn],
        ["Name", full_name],
        ["Address", _session_address(session)],
    ]
    story.append(_box_table(row_data, [2 * inch, 4.2 * inch]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("How to complete your payment:", h3))
    instructions = [
        "1. Make check or money order payable to: <b>New York State Income Tax</b>",
        f"2. Write on memo line: <b>{ssn} — {session.tax_year} — IT-201</b>",
        "3. Mail WITH this voucher to the address on your cover sheet.",
        "4. Do NOT send cash. Do NOT staple the check to your return.",
    ]
    for line in instructions:
        story.append(Paragraph(line, ParagraphStyle("inst", parent=styles["Normal"], fontSize=9, leading=14, leftIndent=8)))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Online alternative: Pay free at <b>tax.ny.gov/pay</b> (no voucher needed).",
        ParagraphStyle("tip", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#155724")),
    ))

    doc.build(story)
    return output_path


def _session_address(session: FilingSession) -> str:
    """Format the primary taxpayer's address as a single line."""
    primary = session.primary
    if not primary or not getattr(primary, "address", None):
        return ""
    a = primary.address
    parts = [a.street]
    if a.apt:
        parts.append(f"Apt {a.apt}")
    parts.append(f"{a.city}, {a.state} {a.zip_code}")
    return "  ".join(parts)
