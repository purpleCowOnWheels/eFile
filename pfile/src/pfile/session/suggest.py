"""
Missing-document suggestions based on prior-year return data.

After ingesting a prior-year PDF, we can compare the income line items that
were non-zero against what has been uploaded to the current session and flag
anything that looks like it's missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pfile.models.prior_year import PriorYearReturn
from pfile.models.session import FilingSession


@dataclass
class DocumentSuggestion:
    doc_type: str             # human-readable type
    reason: str               # why we think it's needed
    prior_year_amount: Decimal
    urgency: str              # "required", "likely", "possible"


def suggest_missing_documents(
    prior: PriorYearReturn,
    session: FilingSession,
) -> list[DocumentSuggestion]:
    """
    Compare prior-year income line items against the documents already
    uploaded to the current session and return a list of suggestions.

    Logic:
      - If a prior-year line item was non-zero, we expect the same document
        type again this year (income sources are usually recurring).
      - We check what's already been parsed into the session and only flag
        what's genuinely absent.
    """
    suggestions: list[DocumentSuggestion] = []
    f = prior.form_1040

    # Aggregate current-session document counts
    primary = session.primary_documents
    spouse = session.spouse_documents if session.is_mfj else None

    def _count(attr: str) -> int:
        n = len(getattr(primary, attr, []))
        if spouse:
            n += len(getattr(spouse, attr, []))
        return n

    w2_count    = _count("w2s")
    int_count   = _count("f1099_ints")
    div_count   = _count("f1099_divs")
    b_count     = _count("f1099_bs")
    r_count     = _count("f1099_rs")
    ssa_count   = _count("ssa_1099s")
    k1_1120_ct  = _count("k1_1120ss")
    k1_1065_ct  = _count("k1_1065s")

    # --- W-2 ---
    if f.line1a_wages > 0 and w2_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form W-2",
            reason=f"Prior year reported ${f.line1a_wages:,.0f} in wages — W-2(s) expected from your employer(s).",
            prior_year_amount=f.line1a_wages,
            urgency="required",
        ))

    # --- 1099-INT ---
    if f.line2b_taxable_interest > 0 and int_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form 1099-INT",
            reason=f"Prior year reported ${f.line2b_taxable_interest:,.2f} in taxable interest — check Ally, Fidelity, or other savings accounts.",
            prior_year_amount=f.line2b_taxable_interest,
            urgency="likely",
        ))

    # --- 1099-DIV ---
    if f.line3b_ordinary_dividends > 0 and div_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form 1099-DIV",
            reason=f"Prior year reported ${f.line3b_ordinary_dividends:,.2f} in ordinary dividends — check brokerage accounts.",
            prior_year_amount=f.line3b_ordinary_dividends,
            urgency="likely",
        ))

    # --- 1099-B (capital gains/losses) ---
    if f.line7_capital_gain_loss != 0 and b_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form 1099-B / Consolidated 1099",
            reason=f"Prior year reported capital gains/losses of ${f.line7_capital_gain_loss:,.2f} — brokerage consolidated statements expected.",
            prior_year_amount=f.line7_capital_gain_loss,
            urgency="likely",
        ))

    # --- Schedule E / K-1 ---
    k1_count = k1_1120_ct + k1_1065_ct
    if f.line8_other_income > 0 and k1_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Schedule K-1 (Form 1065 or 1120-S)",
            reason=f"Prior year reported ${f.line8_other_income:,.0f} in pass-through income — K-1(s) expected from partnership(s) or S-corp(s).",
            prior_year_amount=f.line8_other_income,
            urgency="required",
        ))

    # --- 1099-R ---
    if f.line4b_ira_distributions > 0 and r_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form 1099-R",
            reason=f"Prior year reported ${f.line4b_ira_distributions:,.2f} in IRA/pension distributions.",
            prior_year_amount=f.line4b_ira_distributions,
            urgency="required",
        ))

    # --- SSA-1099 ---
    if f.line6b_taxable_ss > 0 and ssa_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="SSA-1099 (Social Security Benefit Statement)",
            reason=f"Prior year had taxable Social Security benefits (${f.line6b_taxable_ss:,.2f}).",
            prior_year_amount=f.line6b_taxable_ss,
            urgency="required",
        ))

    # --- NY-specific: check that W-2s have state withholding if prior year did ---
    if prior.it201 and prior.it201.ny_withheld > 0:
        # Check whether any uploaded W-2 has NY state wages
        ny_w2s = [
            w for w in primary.w2s
            if w.box15_state == "NY" and w.box16_state_wages > 0
        ]
        if spouse:
            ny_w2s += [
                w for w in spouse.w2s
                if w.box15_state == "NY" and w.box16_state_wages > 0
            ]
        if not ny_w2s and w2_count > 0:
            suggestions.append(DocumentSuggestion(
                doc_type="W-2 with NY state wages",
                reason=(
                    f"Prior year had ${prior.it201.ny_withheld:,.0f} in NY state withholding "
                    "but none of the uploaded W-2s show NY state wages. "
                    "Check that the correct W-2(s) were uploaded."
                ),
                prior_year_amount=prior.it201.ny_withheld,
                urgency="required",
            ))

    # --- QBI / S-corp specific: prior year had QBI deduction ---
    if f.line13_qbi_deduction > 0 and k1_count == 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Schedule K-1 (S-corp or partnership with QBI)",
            reason=(
                f"Prior year claimed a ${f.line13_qbi_deduction:,.0f} QBI deduction — "
                "the underlying K-1 is needed to recompute it."
            ),
            prior_year_amount=f.line13_qbi_deduction,
            urgency="required",
        ))

    # --- NY PTET: if K-1s are present, remind user to set the PTET credit ---
    if prior.it201 and k1_count > 0:
        suggestions.append(DocumentSuggestion(
            doc_type="NY Pass-Through Entity Tax credit (Form IT-653 / PTET)",
            reason=(
                "Your K-1 entity may have elected to pay the NY Pass-Through Entity Tax (PTET). "
                "If so, you are entitled to a credit on your IT-201 equal to your share of PTET paid. "
                "Check your entity's Form PTET or K-1 Box 13 (code ZZ) and set "
                "session.ny_credits['ptet_credit'] to the correct amount."
            ),
            prior_year_amount=Decimal(0),
            urgency="possible",
        ))

    # --- EV credit carry: flag if prior year had non-standard credits ---
    if f.ev_credit_repayment > 0:
        suggestions.append(DocumentSuggestion(
            doc_type="Form 8936 (Clean Vehicle Credit)",
            reason=(
                f"Prior year had a ${f.ev_credit_repayment:,.0f} EV clean vehicle credit repayment. "
                f"If you purchased or leased another EV in {session.tax_year}, you may need Form 8936 again."
            ),
            prior_year_amount=f.ev_credit_repayment,
            urgency="possible",
        ))

    return suggestions


def format_suggestions(
    suggestions: list[DocumentSuggestion],
    tax_year: int,
) -> str:
    """Return a human-readable string of the suggestions."""
    if not suggestions:
        return f"✓ No missing documents detected based on your {tax_year - 1} return."

    lines = [f"Documents that may be missing for {tax_year} (based on your {tax_year - 1} return):\n"]
    icons = {"required": "🔴", "likely": "🟡", "possible": "⚪"}
    for s in suggestions:
        icon = icons.get(s.urgency, "•")
        lines.append(f"  {icon} [{s.urgency.upper()}] {s.doc_type}")
        lines.append(f"     {s.reason}")
    return "\n".join(lines)
