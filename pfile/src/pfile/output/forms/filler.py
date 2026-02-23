"""
PDF AcroForm filler using PyMuPDF.

Fills official IRS 1040 and NY IT-201 PDFs with computed return data.
The filled PDFs are written to a caller-supplied output directory.

Phase 2 scope:
  - Form 1040 (pages 1–2): identity, income, deductions, tax, payments, refund/balance
  - NY IT-201 (pages 1–4): identity, income, modifications, deductions, tax, payments, refund
  - Up to 4 dependents on each form
  - Checkbox for filing status

Limitations / future work:
  - Schedule D, E, B attachments not filled (separate PDF files)
  - MFS/QSS/HOH filing status boxes not yet differentiated on 1040
  - IRS direct-deposit routing/account fields omitted (security risk)
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any

import fitz  # PyMuPDF

from pfile.models.filer import FilingStatus, TaxpayerProfile
from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn
from pfile.models.session import FilingSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money(amount: Decimal | None) -> str:
    """Format a Decimal as a plain dollar string (no sign for positives)."""
    if amount is None:
        return ""
    return str(amount.quantize(Decimal("0.00")))


def _apply_fields(doc: fitz.Document, updates: dict[str, Any]) -> None:
    """
    Apply a name→value mapping to the PDF's AcroForm fields.

    Widgets are updated in the same pass that iterates their parent page,
    keeping the page reference alive and avoiding 'Annot not bound to page'.
    """
    remaining = dict(updates)
    for page in doc:
        for widget in page.widgets():
            name = widget.field_name
            if name not in remaining:
                continue
            value = remaining.pop(name)
            if widget.field_type_string == "CheckBox":
                widget.field_value = "Yes" if value else "Off"
            else:
                widget.field_value = str(value) if value is not None else ""
            widget.update()
            if not remaining:
                return


# ---------------------------------------------------------------------------
# Federal Form 1040
# ---------------------------------------------------------------------------

def _build_1040_updates(
    session: FilingSession,
    result: ComputedFederalReturn,
) -> dict[str, Any]:
    """Build the full name→value update dict for Form 1040."""
    p = session.primary
    s = session.spouse
    status = session.filing_status
    f = result.form_1040
    p1 = "topmostSubform[0].Page1[0]."
    p2 = "topmostSubform[0].Page2[0]."

    updates: dict[str, Any] = {}

    # Filing status checkboxes
    updates[p1 + "c1_1[0]"] = status == FilingStatus.SINGLE
    updates[p1 + "c1_2[0]"] = status == FilingStatus.MFJ
    updates[p1 + "c1_3[0]"] = status in {FilingStatus.MFS, FilingStatus.HOH, FilingStatus.QSS}

    # Taxpayer identity
    if p:
        updates[p1 + "f1_01[0]"] = f"{p.first_name} {p.last_name}"
        updates[p1 + "f1_03[0]"] = p.ssn
        if p.address:
            addr = p.address
            updates[p1 + "Address_ReadOrder[0].f1_20[0]"] = addr.street
            updates[p1 + "Address_ReadOrder[0].f1_22[0]"] = addr.city
            updates[p1 + "Address_ReadOrder[0].f1_23[0]"] = addr.state
            updates[p1 + "Address_ReadOrder[0].f1_24[0]"] = addr.zip_code

    if s and status == FilingStatus.MFJ:
        updates[p1 + "f1_05[0]"] = f"{s.first_name} {s.last_name}"
        updates[p1 + "f1_04[0]"] = s.ssn

    # Dependents (up to 4)
    dep_rows = [
        ("f1_31[0]", "f1_32[0]", "f1_33[0]", "Row1"),
        ("f1_35[0]", "f1_36[0]", "f1_37[0]", "Row2"),
        ("f1_39[0]", "f1_40[0]", "f1_41[0]", "Row3"),
        ("f1_43[0]", "f1_44[0]", "f1_45[0]", "Row4"),
    ]
    for dep, (fn_f, ssn_f, rel_f, row) in zip(session.dependents[:4], dep_rows):
        pre = p1 + f"Table_Dependents[0].{row}[0]."
        updates[pre + fn_f] = f"{dep.first_name} {dep.last_name}"
        updates[pre + ssn_f] = dep.ssn
        updates[pre + rel_f] = dep.relationship

    # Income (page 1)
    updates[p1 + "f1_47[0]"] = _money(f.line1a_w2_wages)
    updates[p1 + "f1_53[0]"] = _money(f.line2b_taxable_interest)
    updates[p1 + "f1_54[0]"] = _money(f.line3a_qualified_dividends)
    updates[p1 + "f1_55[0]"] = _money(f.line3b_ordinary_dividends)
    updates[p1 + "f1_57[0]"] = _money(f.line4b_ira_distributions)
    updates[p1 + "f1_59[0]"] = _money(f.line5b_taxable_ss)
    updates[p1 + "f1_61[0]"] = _money(f.line7_capital_gain_loss)
    updates[p1 + "f1_62[0]"] = _money(f.line8_other_income)
    updates[p1 + "f1_63[0]"] = _money(f.line9_total_income)
    updates[p1 + "f1_64[0]"] = _money(f.line10_adjustments)
    updates[p1 + "f1_65[0]"] = _money(f.line11_agi)
    updates[p1 + "f1_66[0]"] = _money(f.line12_standard_or_itemized)
    updates[p1 + "f1_67[0]"] = _money(f.line13_qbi_deduction)
    updates[p1 + "f1_69[0]"] = _money(f.line15_taxable_income)
    updates[p1 + "f1_70[0]"] = _money(f.line15_taxable_income)

    # Tax & credits (page 2)
    updates[p2 + "f2_02[0]"] = _money(f.line16_tax)
    updates[p2 + "f2_04[0]"] = _money(f.line16_tax)
    updates[p2 + "f2_05[0]"] = _money(f.line19_ctc)
    updates[p2 + "f2_06[0]"] = _money(f.line20_other_credits)
    total_credits = (f.line19_ctc or Decimal(0)) + (f.line20_other_credits or Decimal(0))
    updates[p2 + "f2_07[0]"] = _money(total_credits)
    updates[p2 + "f2_08[0]"] = _money(max(Decimal(0), f.line16_tax - total_credits))
    updates[p2 + "f2_10[0]"] = _money(f.line24_total_tax)

    # Payments (page 2)
    updates[p2 + "f2_11[0]"] = _money(f.line25a_w2_withheld)
    updates[p2 + "f2_12[0]"] = _money(f.line25b_1099_withheld)
    updates[p2 + "f2_13[0]"] = _money(f.line25c_other_withheld)
    withheld_total = (
        (f.line25a_w2_withheld or Decimal(0))
        + (f.line25b_1099_withheld or Decimal(0))
        + (f.line25c_other_withheld or Decimal(0))
    )
    updates[p2 + "f2_14[0]"] = _money(withheld_total)
    updates[p2 + "f2_15[0]"] = _money(f.line26_estimated_payments)
    updates[p2 + "f2_21[0]"] = _money(f.line33_total_payments)

    overpay = max(Decimal(0), f.line33_total_payments - f.line24_total_tax)
    owed = max(Decimal(0), f.line24_total_tax - f.line33_total_payments)
    if overpay > 0:
        updates[p2 + "f2_23[0]"] = _money(overpay)
        updates[p2 + "f2_24[0]"] = _money(overpay)
    if owed > 0:
        updates[p2 + "f2_28[0]"] = _money(owed)

    return updates


def fill_1040(
    session: FilingSession,
    federal: ComputedFederalReturn,
    template_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Fill a Form 1040 template with computed data and save to output_path."""
    updates = _build_1040_updates(session, federal)
    doc = fitz.open(str(template_path))
    _apply_fields(doc, updates)
    doc.save(str(output_path))
    doc.close()


# ---------------------------------------------------------------------------
# NY IT-201
# ---------------------------------------------------------------------------

def _build_it201_updates(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn,
) -> dict[str, Any]:
    """Build the full name→value update dict for IT-201."""
    p = session.primary
    s = session.spouse
    f = federal.form_1040
    it = ny.it201

    updates: dict[str, Any] = {}

    # Identity
    if p:
        updates["TP_first_name"] = p.first_name
        updates["TP_last_name"] = p.last_name
        updates["TP_SSN"] = p.ssn
        if p.dob:
            updates["TP_DOB"] = p.dob.strftime("%m/%d/%Y")
        if p.address:
            updates["TP_mail_address"] = p.address.street
            updates["TP_mail_city"] = p.address.city
            updates["TP_mail_state"] = p.address.state
            updates["TP_mail_zip"] = p.address.zip_code
        if p.ny_residency:
            updates["NYS_county_residence"] = p.ny_residency.county

    if s and session.is_mfj:
        updates["Spouse_first_name"] = s.first_name
        updates["Spouse_last_name"] = s.last_name
        updates["Spouse_SSN"] = s.ssn

    for i, dep in enumerate(session.dependents[:6], start=1):
        updates[f"H_first{i}"] = dep.first_name
        updates[f"H_last{i}"] = dep.last_name
        updates[f"H_relationship{i}"] = dep.relationship
        updates[f"H_dependent_ssn{i}"] = dep.ssn
        if dep.dob:
            updates[f"H_dependent_dob{i}"] = dep.dob.strftime("%m/%d/%Y")

    # Income
    updates["Line1"] = _money(f.line1a_w2_wages)
    updates["Line2"] = _money(f.line2b_taxable_interest)
    updates["Line3"] = _money(f.line3b_ordinary_dividends)
    updates["Line5"] = _money(f.line7_capital_gain_loss)
    updates["Line6"] = _money(f.line4b_ira_distributions)
    updates["Line10"] = _money(f.line5b_taxable_ss)
    updates["Line12"] = _money(f.line9_total_income)

    # NY modifications
    updates["Line13"] = _money(it.ny_additions)
    updates["Line15"] = _money(it.ny_subtractions)
    updates["Line16"] = _money(it.ny_agi)

    # Deductions / taxable income
    updates["Line34"] = _money(it.ny_deduction_used)
    updates["Line35"] = _money(it.ny_dependent_exemptions)
    updates["Line36"] = _money(it.ny_taxable_income)
    updates["Line37"] = _money(it.ny_tax)

    # NYC tax and total
    updates["Line51"] = _money(it.nyc_tax)
    total_tax = it.ny_tax + it.nyc_tax + it.yonkers_surcharge
    updates["Line55"] = _money(total_tax)

    # Empire State CTC (line 47 on the IT-201)
    if it.empire_state_ctc > 0:
        updates["Line47"] = _money(it.empire_state_ctc)

    # Payments
    updates["Line62"] = _money(it.ny_withheld)
    updates["Line63"] = _money(it.nyc_withheld)
    updates["Line72"] = _money(it.total_ny_payments)

    # Refund / balance
    if it.ny_refund > 0:
        updates["Line75"] = _money(it.ny_refund)
        updates["Line78a"] = _money(it.ny_refund)
    if it.ny_amount_owed > 0:
        updates["Line79"] = _money(it.ny_amount_owed)

    return updates


def fill_it201(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn,
    template_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Fill an IT-201 template with computed data and save to output_path."""
    updates = _build_it201_updates(session, federal, ny)
    doc = fitz.open(str(template_path))
    _apply_fields(doc, updates)
    doc.save(str(output_path))
    doc.close()
