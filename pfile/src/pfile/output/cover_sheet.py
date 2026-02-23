"""Generate the filing package cover sheet using ReportLab."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn
from pfile.models.session import FilingSession

_MAILING_DIR = Path(__file__).parents[3] / "data" / "mailing"

_BLUE = colors.HexColor("#1a3a6b")
_LIGHT_BLUE = colors.HexColor("#e8f0fb")
_GREEN = colors.HexColor("#155724")
_RED = colors.HexColor("#721c24")
_GRAY = colors.HexColor("#6c757d")


def _load_mailing(filename: str) -> dict:
    with (_MAILING_DIR / filename).open() as f:
        return yaml.safe_load(f)


def _fmt(d: Decimal) -> str:
    if d < 0:
        return f"(${abs(d):,.2f})"
    return f"${d:,.2f}"


def _mask_ssn(ssn: str) -> str:
    """Show only last 4 digits: XXX-XX-1234."""
    parts = ssn.split("-")
    if len(parts) == 3:
        return f"XXX-XX-{parts[2]}"
    return "XXX-XX-XXXX"


def generate(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None,
    output_path: Path,
) -> Path:
    """Render the cover sheet PDF to output_path and return it."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
    )

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=_BLUE, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=_BLUE, fontSize=12, spaceAfter=2, spaceBefore=10)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=12, textColor=_GRAY)
    check = ParagraphStyle("check", parent=body, leftIndent=12)

    story = []

    # --- Title ---
    story.append(Paragraph("pFile — Tax Filing Package", h1))
    story.append(Paragraph(
        f"Tax Year <b>{session.tax_year}</b> &nbsp;|&nbsp; "
        f"Generated {_today_str()}",
        small,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE, spaceAfter=10))

    # --- Filer summary ---
    story.append(Paragraph("Filer Information", h2))
    primary = session.primary
    filer_data = [
        ["Name", session.display_name],
        ["SSN", _mask_ssn(primary.ssn) if primary else "—"],
        ["Filing Status", session.filing_status.value.replace("_", " ").title()],
        ["Tax Year", str(session.tax_year)],
    ]
    if session.dependents:
        names = ", ".join(f"{d.first_name} {d.last_name}" for d in session.dependents)
        filer_data.append(["Dependents", names])
    story.append(_summary_table(filer_data))

    # --- Federal results ---
    story.append(Paragraph("Federal Form 1040", h2))
    f1040 = federal.form_1040
    fed_data = [
        ["AGI (line 11)",           _fmt(f1040.line11_agi)],
        ["Taxable income (line 15)", _fmt(f1040.line15_taxable_income)],
        ["Total tax (line 24)",      _fmt(f1040.line24_total_tax)],
        ["Total payments (line 33)", _fmt(f1040.line33_total_payments)],
    ]
    if federal.balance_due > 0:
        fed_data.append(["BALANCE DUE", _fmt(federal.balance_due)])
    else:
        fed_data.append(["REFUND", _fmt(federal.refund)])
    story.append(_summary_table(fed_data, highlight_last=True, due=federal.balance_due > 0))

    # Federal mailing address
    irs = _load_mailing("irs.yaml")
    story.append(Spacer(1, 6))
    if federal.balance_due > 0:
        addr = irs["with_payment"]["address"]
        story.append(Paragraph("<b>Mail TO (with payment):</b>", body))
        story.append(_address_block(addr, styles))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<b>Payable to:</b> {irs['with_payment']['payable_to']}", body
        ))
        story.append(Paragraph(irs["with_payment"]["note"], small))
    else:
        addr = irs["without_payment"]["address"]
        story.append(Paragraph("<b>Mail TO:</b>", body))
        story.append(_address_block(addr, styles))

    # Online payment option
    if federal.balance_due > 0:
        story.append(Spacer(1, 4))
        dp = irs["online_payment"]["direct_pay"]
        story.append(Paragraph(
            f"<b>Pay online (free):</b> {dp['url']} — {dp['note']}", small
        ))

    # --- NY results ---
    if ny:
        story.append(Paragraph("New York State IT-201", h2))
        it201 = ny.it201
        ny_data = [
            ["NY AGI",                   _fmt(it201.ny_agi)],
            ["NY taxable income",         _fmt(it201.ny_taxable_income)],
            ["Total NY tax",              _fmt(it201.total_ny_tax)],
            ["Total NY payments",         _fmt(it201.total_ny_payments)],
        ]
        if ny.balance_due > 0:
            ny_data.append(["BALANCE DUE", _fmt(ny.balance_due)])
        else:
            ny_data.append(["REFUND", _fmt(ny.refund)])
        story.append(_summary_table(ny_data, highlight_last=True, due=ny.balance_due > 0))

        ny_mail = _load_mailing("ny_dtf.yaml")
        story.append(Spacer(1, 6))
        if ny.balance_due > 0:
            addr_info = ny_mail["it201"]["balance_due"]
            story.append(Paragraph("<b>Mail TO (with payment):</b>", body))
            story.append(_address_block(addr_info["address"], styles))
            story.append(Paragraph(
                f"<b>Payable to:</b> {addr_info['payable_to']}", body
            ))
            story.append(Paragraph(ny_mail["it201_v"]["note"], small))
        else:
            addr_info = ny_mail["it201"]["refund_or_no_tax"]
            story.append(Paragraph("<b>Mail TO:</b>", body))
            story.append(_address_block(addr_info["address"], styles))

    # --- Payment timeline ---
    if federal.balance_due > 0 or (ny and ny.balance_due > 0):
        story.append(Paragraph("Payment Deadline", h2))
        story.append(Paragraph(
            f"<b>Due date: April 15, {session.tax_year + 1}</b> — "
            "Payment must be postmarked by this date to avoid penalties.",
            body,
        ))

    # --- Filing checklist ---
    story.append(Paragraph("Filing Checklist", h2))
    story.append(Paragraph("Verify all items below before mailing:", body))
    story.append(Spacer(1, 4))

    checklist = _build_checklist(session, federal, ny)
    for item in checklist:
        story.append(Paragraph(f"☐  {item}", check))

    # --- Estimated tax reminder ---
    if (federal.balance_due > 0 or (ny and ny.balance_due > 0)):
        story.append(Spacer(1, 8))
        story.append(Paragraph("Estimated Tax Reminder", h2))
        story.append(Paragraph(
            "If you owed more than $1,000 this year, you may need to make "
            "quarterly estimated payments to avoid penalties next year. "
            "See Form 1040-ES for federal and Form IT-2105 for NY state.",
            small,
        ))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY))
    story.append(Paragraph(
        "Generated by pFile — open-source tax filing tool. "
        "Verify all amounts against original documents before filing.",
        small,
    ))

    doc.build(story)
    return output_path


def _summary_table(
    rows: list[list[str]],
    highlight_last: bool = False,
    due: bool = False,
) -> Table:
    col_widths = [3.2 * inch, 2.4 * inch]
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
    ]
    if highlight_last:
        last = len(rows) - 1
        bg = colors.HexColor("#f8d7da") if due else colors.HexColor("#d4edda")
        fg = _RED if due else _GREEN
        style += [
            ("BACKGROUND", (0, last), (-1, last), bg),
            ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, last), (-1, last), fg),
        ]
    return Table(rows, colWidths=col_widths, style=TableStyle(style))


def _address_block(addr: dict, styles) -> Table:
    lines = []
    for key in ("line1", "line2"):
        if addr.get(key):
            lines.append(addr[key])
    lines.append(f"{addr['city']}, {addr['state']}  {addr['zip']}")
    data = [[line] for line in lines]
    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("BACKGROUND", (0, 0), (-1, -1), _LIGHT_BLUE),
    ])
    return Table(data, colWidths=[4 * inch], style=style)


def _build_checklist(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None,
) -> list[str]:
    items = [
        "Sign and date Form 1040 (both spouses if MFJ)",
        "Attach all W-2 forms behind Form 1040 (do NOT staple to check)",
    ]
    if federal.schedule_b and federal.schedule_b.required:
        items.append("Attach Schedule B")
    if federal.schedule_d:
        items.append("Attach Schedule D (capital gains/losses)")
    if federal.schedule_e:
        items.append("Attach Schedule E (K-1 pass-through income)")
    if federal.balance_due > 0:
        items.append("Attach Form 1040-V payment voucher (from this package)")
        items.append(
            f"Enclose check or money order for {_fmt(federal.balance_due)} "
            "payable to 'United States Treasury'"
        )
    if ny:
        items.append("Sign and date Form IT-201 (both spouses if MFJ)")
        items.append("Attach Form IT-2 (W-2 summary)")
        if ny.it201.empire_state_ctc > 0:
            items.append("Attach Form IT-213 (Empire State Child Credit)")
        if ny.it201.ny_credits > 0:
            items.append("Attach applicable NY credit forms (IT-255, IT-653, etc.)")
        if ny.balance_due > 0:
            items.append("Attach Form IT-201-V payment voucher (from this package)")
            items.append(
                f"Enclose check or money order for {_fmt(ny.balance_due)} "
                "payable to 'New York State Income Tax'"
            )
    items.append("Make copies of everything before mailing")
    items.append("Mail via USPS Certified Mail with Return Receipt for proof of filing")
    return items


def _today_str() -> str:
    from datetime import date
    return date.today().strftime("%B %d, %Y")
