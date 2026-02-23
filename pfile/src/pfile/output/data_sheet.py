"""Generate line-item data sheets for Form 1040 and IT-201 using ReportLab."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn
from pfile.models.session import FilingSession

_BLUE = colors.HexColor("#1a3a6b")
_LIGHT_BLUE = colors.HexColor("#e8f0fb")
_GRAY = colors.HexColor("#6c757d")
_SECTION_BG = colors.HexColor("#dce6f9")


def _fmt(d: Decimal) -> str:
    if d == Decimal(0):
        return "—"
    if d < 0:
        return f"(${abs(d):,.2f})"
    return f"${d:,.2f}"


def _line_table(rows: list[tuple[str, str, str | None]]) -> Table:
    """
    rows: [(line_no, description, amount)]
    If amount is None the row is a section header.
    """
    data = []
    style_cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("FONTNAME", (2, 0), (2, -1), "Courier"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#dee2e6")),
    ]
    for i, (line, desc, amt) in enumerate(rows):
        if amt is None:
            data.append([line, desc, ""])
            style_cmds += [
                ("BACKGROUND", (0, i), (-1, i), _SECTION_BG),
                ("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"),
                ("SPAN", (0, i), (1, i)),
            ]
        else:
            data.append([line, desc, amt])
    col_widths = [0.6 * inch, 4.5 * inch, 1.3 * inch]
    return Table(data, colWidths=col_widths, style=TableStyle(style_cmds))


def generate(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None,
    output_path: Path,
) -> Path:
    """Render the data sheet PDF and return output_path."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=_BLUE, fontSize=15, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=_BLUE, fontSize=11, spaceAfter=4, spaceBefore=8)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=_GRAY)

    story = []

    # --- Title ---
    story.append(Paragraph("pFile — Computed Tax Line Items", h1))
    story.append(Paragraph(
        f"{session.display_name} &nbsp;|&nbsp; Tax Year {session.tax_year} &nbsp;|&nbsp; Filing Status: {session.filing_status.value.replace('_', ' ').title()}",
        small,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=_BLUE, spaceAfter=8))

    # --- Form 1040 ---
    story.append(Paragraph("Form 1040 — U.S. Individual Income Tax Return", h2))
    story.extend(_build_1040_rows(federal))

    # --- Schedule B ---
    if federal.schedule_b and federal.schedule_b.required:
        sb = federal.schedule_b
        story.append(Spacer(1, 8))
        story.append(Paragraph("Schedule B — Interest and Ordinary Dividends", h2))
        sb_rows = [
            ("", "Interest Income", None),
            ("L1", "Total taxable interest", _fmt(sb.total_interest)),
            ("", "Ordinary Dividends", None),
            ("L6", "Total ordinary dividends", _fmt(sb.total_ordinary_dividends)),
        ]
        story.append(_line_table(sb_rows))

    # --- Schedule D ---
    if federal.schedule_d:
        sd = federal.schedule_d
        story.append(Spacer(1, 8))
        story.append(Paragraph("Schedule D — Capital Gains and Losses", h2))
        sd_rows = [
            ("", "Short-Term (held ≤ 1 year)", None),
            ("L1b", "Net short-term gain / (loss)", _fmt(sd.net_short_term)),
            ("", "Long-Term (held > 1 year)", None),
            ("L8b", "Net long-term gain / (loss)", _fmt(sd.net_long_term)),
            ("", "Summary", None),
            ("L16", "Net capital gain / (loss)", _fmt(sd.net_capital_gain_loss)),
        ]
        story.append(_line_table(sd_rows))

    # --- Schedule E ---
    if federal.schedule_e and federal.schedule_e.entries:
        se = federal.schedule_e
        story.append(Spacer(1, 8))
        story.append(Paragraph("Schedule E — Supplemental Income (K-1 Pass-Through)", h2))
        se_rows: list[tuple[str, str, str | None]] = [("", "K-1 Entries", None)]
        for entry in se.entries:
            label = entry.entity_name or "Unknown Entity"
            se_rows.append(("", f"  {label} — Ordinary income", _fmt(entry.ordinary_income)))
            if entry.ordinary_loss:
                se_rows.append(("", f"  {label} — Ordinary loss", _fmt(entry.ordinary_loss)))
            if entry.section_179:
                se_rows.append(("", f"  {label} — Section 179 deduction", _fmt(entry.section_179)))
            se_rows.append(("", f"  {label} — Net income / (loss)", _fmt(entry.net_income)))
        se_rows.append(("L41", "Total Schedule E income / (loss)", _fmt(se.total_income)))
        story.append(_line_table(se_rows))

    # --- Schedule SE ---
    if federal.schedule_se and federal.schedule_se.net_se_income > 0:
        sse = federal.schedule_se
        story.append(Spacer(1, 8))
        story.append(Paragraph("Schedule SE — Self-Employment Tax", h2))
        sse_rows = [
            ("L2", "Net SE income", _fmt(sse.net_se_income)),
            ("L4", "SE tax (15.3% / 2.9% above SS wage base)", _fmt(sse.se_tax)),
            ("L6", "Deductible portion of SE tax (½)", _fmt(sse.deductible_se_tax)),
        ]
        story.append(_line_table(sse_rows))

    # --- IT-201 ---
    if ny:
        story.append(PageBreak())
        story.append(Paragraph("NY Form IT-201 — Resident Income Tax Return", h2))
        story.extend(_build_it201_rows(ny))

        # IT-2 W-2 summary
        if ny.it2.entries:
            story.append(Spacer(1, 8))
            story.append(Paragraph("NY Form IT-2 — W-2 Summary", h2))
            it2_rows: list[tuple[str, str, str | None]] = [
                ("", "Employer", None),
            ]
            for e in ny.it2.entries:
                name = e.employer_name or "Unknown"
                it2_rows.append(("", f"  {name} — NY wages", _fmt(e.ny_state_wages)))
                it2_rows.append(("", f"  {name} — NY withheld", _fmt(e.ny_state_withheld)))
                if e.nyc_local_wages:
                    it2_rows.append(("", f"  {name} — NYC wages", _fmt(e.nyc_local_wages)))
                    it2_rows.append(("", f"  {name} — NYC withheld", _fmt(e.nyc_local_withheld)))
            it2_rows.append(("", "Totals", None))
            it2_rows.append(("", "Total NY wages", _fmt(ny.it2.total_ny_wages)))
            it2_rows.append(("", "Total NY withheld", _fmt(ny.it2.total_ny_withheld)))
            if ny.it2.total_nyc_withheld:
                it2_rows.append(("", "Total NYC withheld", _fmt(ny.it2.total_nyc_withheld)))
            story.append(_line_table(it2_rows))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=_GRAY))
    story.append(Paragraph(
        "This document is a pFile computation summary. Verify all amounts against original source documents.",
        small,
    ))

    doc.build(story)
    return output_path


def _build_1040_rows(federal: ComputedFederalReturn) -> list:
    f = federal.form_1040
    rows = [
        ("", "Income", None),
        ("L1a", "Wages, salaries, tips (W-2 box 1)", _fmt(f.line1a_w2_wages)),
        ("L2b", "Taxable interest", _fmt(f.line2b_taxable_interest)),
        ("L3b", "Ordinary dividends", _fmt(f.line3b_ordinary_dividends)),
        ("L3a", "  of which: qualified dividends", _fmt(f.line3a_qualified_dividends)),
        ("L4b", "IRA / pension distributions (taxable)", _fmt(f.line4b_ira_distributions)),
        ("L5b", "Pensions and annuities (taxable)", _fmt(f.line5b_pensions_annuities)),
        ("L5b", "Taxable Social Security", _fmt(f.line5b_taxable_ss)),
        ("L7",  "Capital gain / (loss)", _fmt(f.line7_capital_gain_loss)),
        ("L8",  "Other income (Schedule 1)", _fmt(f.line8_other_income)),
        ("L9",  "Total income", _fmt(f.line9_total_income)),
        ("", "Adjustments & AGI", None),
        ("L10", "Adjustments to income (Schedule 1 Part II)", _fmt(f.line10_adjustments)),
        ("L11", "Adjusted Gross Income (AGI)", _fmt(f.line11_agi)),
        ("", "Deductions & Tax", None),
        ("L12", "Standard or itemized deduction", _fmt(f.line12_standard_or_itemized)),
        ("L13", "QBI deduction (§199A)", _fmt(f.line13_qbi_deduction)),
        ("L15", "Taxable income", _fmt(f.line15_taxable_income)),
        ("L16", "Income tax", _fmt(f.line16_tax)),
        ("L17", "Alternative Minimum Tax (AMT)", _fmt(f.line17_amt)),
        ("L24", "Total tax", _fmt(f.line24_total_tax)),
        ("", "Credits", None),
        ("L19", "Child Tax Credit / Credit for Other Dependents", _fmt(f.line19_ctc)),
        ("L20", "Other credits", _fmt(f.line20_other_credits)),
        ("", "Payments", None),
        ("L25a", "Federal income tax withheld (W-2)", _fmt(f.line25a_w2_withheld)),
        ("L25b", "Federal income tax withheld (1099)", _fmt(f.line25b_1099_withheld)),
        ("L25c", "Other federal tax withheld", _fmt(f.line25c_other_withheld)),
        ("L26", "Estimated tax payments", _fmt(f.line26_estimated_payments)),
        ("L27", "Earned Income Credit", _fmt(f.line27_eitc)),
        ("L33", "Total payments", _fmt(f.line33_total_payments)),
        ("", "Result", None),
        ("L37/35", "Amount owed" if f.line37_amount_owed > 0 else "Refund",
         _fmt(f.line37_amount_owed if f.line37_amount_owed > 0 else f.line35a_refund)),
    ]
    return [_line_table(rows)]


def _build_it201_rows(ny: ComputedNYReturn) -> list:
    i = ny.it201
    rows = [
        ("", "NY Income", None),
        ("L19", "Federal AGI (IT-201 line 19)", _fmt(i.federal_agi)),
        ("L20", "NY additions", _fmt(i.ny_additions)),
        ("L22", "NY subtractions", _fmt(i.ny_subtractions)),
        ("L23", "NY AGI", _fmt(i.ny_agi)),
        ("", "Deductions", None),
        ("L34", "NY standard deduction", _fmt(i.ny_standard_deduction)),
        ("L34", "NY itemized deduction", _fmt(i.ny_itemized_deduction)),
        ("L34", "NY deduction used", _fmt(i.ny_deduction_used)),
        ("L36", "Dependent exemptions", _fmt(i.ny_dependent_exemptions)),
        ("L37", "NY taxable income", _fmt(i.ny_taxable_income)),
        ("", "Tax", None),
        ("L38", "NY state tax", _fmt(i.ny_tax)),
        ("L47", "NYC resident tax", _fmt(i.nyc_tax)),
        ("L50", "Yonkers resident income tax surcharge", _fmt(i.yonkers_surcharge)),
        ("L54", "NY non-refundable credits", _fmt(i.ny_credits)),
        ("L58", "Total NY/NYC/Yonkers tax after credits", _fmt(i.total_ny_tax)),
        ("", "Refundable Credits & Payments", None),
        ("L63", "Empire State Child Credit (IT-213)", _fmt(i.empire_state_ctc)),
        ("L64", "NY tax withheld (IT-2)", _fmt(i.ny_withheld)),
        ("L65", "NYC tax withheld", _fmt(i.nyc_withheld)),
        ("L66", "Yonkers tax withheld", _fmt(i.yonkers_withheld)),
        ("L79", "Total NY payments", _fmt(i.total_ny_payments)),
        ("", "Result", None),
        ("L80", "Amount owed" if i.ny_amount_owed > 0 else "Refund",
         _fmt(i.ny_amount_owed if i.ny_amount_owed > 0 else i.ny_refund)),
    ]
    return [_line_table(rows)]
