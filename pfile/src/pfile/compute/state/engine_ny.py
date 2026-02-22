"""
New York State tax computation engine.

Takes a FilingSession + ComputedFederalReturn and returns a ComputedNYReturn.
Covers Form IT-201 (full-year resident) and Form IT-2 (W-2 summary).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pfile.models.documents import W2
from pfile.models.forms import (
    ComputedFederalReturn,
    ComputedNYReturn,
    IT2,
    IT2Entry,
    IT201,
)
from pfile.models.session import FilingSession
from pfile.compute.credits import empire_state_child_credit
from pfile.compute.state.ny import (
    compute_ny_tax,
    ny_pension_subtraction,
    ny_social_security_subtraction,
    ny_standard_deduction,
)


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_it2(w2s: list[W2]) -> IT2:
    """
    Build Form IT-2 from all W-2s.

    IT-2 summarises Box 15–17 (NY state) and Box 18–20 (local) from each W-2.
    """
    entries: list[IT2Entry] = []
    for w2 in w2s:
        if w2.box15_state != "NY" and not w2.box16_state_wages:
            continue  # skip non-NY W-2 entries
        entries.append(IT2Entry(
            employer_name=w2.employer.name,
            employer_ein=w2.employer.ein,
            ny_state_wages=w2.box16_state_wages,
            ny_state_withheld=w2.box17_state_withheld,
            nyc_local_wages=w2.box18_local_wages,
            nyc_local_withheld=w2.box19_local_withheld,
        ))

    total_ny_wages = sum((e.ny_state_wages for e in entries), Decimal(0))
    total_ny_withheld = sum((e.ny_state_withheld for e in entries), Decimal(0))
    total_nyc_withheld = sum((e.nyc_local_withheld for e in entries), Decimal(0))

    return IT2(
        entries=entries,
        total_ny_wages=_round2(total_ny_wages),
        total_ny_withheld=_round2(total_ny_withheld),
        total_nyc_withheld=_round2(total_nyc_withheld),
    )


def compute_ny_return(
    session: FilingSession,
    federal: ComputedFederalReturn,
    year: int = 2025,
) -> ComputedNYReturn:
    """
    Compute the NY IT-201 full-year resident return.

    NY modifications to federal AGI (Phase 1 — most common items):
      Additions:
        - Interest from state/local bonds of other states
          (not needed for typical W-2 + 1099 filers, skipped in Phase 1)
      Subtractions:
        - Social Security benefits (NY fully excludes SS income)
        - Government pension exclusion (up to $20,000)
        - Interest from US government obligations (Box 3 of 1099-INT is already
          excluded at federal level; no double-deduction needed)

    Source: IT-201 instructions; NY Tax Law §§601, 612, 614.
    """
    if not session.primary:
        raise ValueError("Session has no primary taxpayer profile.")

    residency = session.primary.ny_residency
    if not residency:
        raise ValueError("Primary taxpayer has no NY residency info. Is this an NY filer?")

    status = session.filing_status

    # ------------------------------------------------------------------
    # Collect all W-2s (primary + spouse for MFJ)
    # ------------------------------------------------------------------
    all_w2s: list[W2] = list(session.primary_documents.w2s)
    if session.is_mfj and session.spouse_documents:
        all_w2s.extend(session.spouse_documents.w2s)

    # ------------------------------------------------------------------
    # Form IT-2
    # ------------------------------------------------------------------
    it2 = _build_it2(all_w2s)

    # ------------------------------------------------------------------
    # NY AGI modifications
    # ------------------------------------------------------------------
    federal_agi = federal.agi

    # NY additions (Phase 1: none for typical filers)
    ny_additions = Decimal(0)

    # NY subtractions
    # 1. Social Security — already in gross["taxable_ss"] on federal return;
    #    we need the TOTAL SS benefits paid (including the non-taxable portion).
    #    Proxy: pull from federal 1040 line 5b ratio isn't reliable without the
    #    original SSA-1099. For now, use the taxable SS that *was* included in
    #    federal AGI and subtract it (conservative: this understates NY
    #    subtraction when only 50% was taxable federally).
    #    TODO Phase 3: capture raw SSA-1099 net_benefits for exact calculation.
    taxable_ss_in_agi = federal.form_1040.line5b_taxable_ss
    ss_subtraction = ny_social_security_subtraction(taxable_ss_in_agi)

    # 2. Government pension exclusion — we don't currently parse 1099-R in depth
    #    enough to distinguish government pensions. Set to 0; Phase 3 will add.
    pension_sub = Decimal(0)

    ny_subtractions = ss_subtraction + pension_sub

    # ------------------------------------------------------------------
    # NY deduction: itemized (IT-196) overrides standard if provided
    # ------------------------------------------------------------------
    ny_deduction_override = session.ny_itemized_deduction  # None → use standard

    # ------------------------------------------------------------------
    # NY tax computation
    # ------------------------------------------------------------------
    num_dependents = len(session.dependents)

    result = compute_ny_tax(
        federal_agi=federal_agi,
        ny_additions=ny_additions,
        ny_subtractions=ny_subtractions,
        status=status,
        residency=residency,
        year=year,
        ny_deduction_override=ny_deduction_override,
        num_dependents=num_dependents,
    )

    ny_agi = _round2(result["ny_agi"])
    ny_taxable_income = _round2(result["ny_taxable_income"])
    state_tax = _round2(result["ny_tax"])
    city_tax = _round2(result["nyc_tax"])
    yonkers = _round2(result["yonkers_surcharge"])
    total_ny_tax_before_credits = _round2(result["total_ny_tax"])

    # ------------------------------------------------------------------
    # NY non-refundable credits — reduce tax (floor at zero)
    #
    # Supported keys in session.ny_credits:
    #   "solar_it255"        — IT-255 solar energy system equipment credit
    #   "college_tuition"    — College Tuition Credit (IT-272)
    #   "real_property_tax"  — Real Property Tax Credit (IT-214, low-income)
    #   "ptet_credit"        — NY Pass-Through Entity Tax credit (Form IT-653)
    #   "prior_year_credits" — Lump-sum carry from prior-year IT-201 ingest
    #
    # NOTE: "empire_state_ctc" should NOT be placed in session.ny_credits —
    # it is computed automatically below and treated as a refundable payment.
    # ------------------------------------------------------------------
    ny_credits_applied = _round2(sum(session.ny_credits.values(), Decimal(0)))
    total_ny_tax = max(Decimal(0), total_ny_tax_before_credits - ny_credits_applied)

    # ------------------------------------------------------------------
    # Empire State Child Credit (IT-213) — REFUNDABLE
    # Computed automatically from dependents; added to total payments.
    # Source: NY Tax Law §606(c-1); IT-213-I 2024 instructions.
    # ------------------------------------------------------------------
    empire_ctc = _round2(empire_state_child_credit(
        dependents=session.dependents,
        fagi=federal_agi,
        status=status,
        year=year,
    ))

    # ------------------------------------------------------------------
    # Withholding
    # ------------------------------------------------------------------
    ny_withheld = it2.total_ny_withheld
    nyc_withheld = it2.total_nyc_withheld
    yonkers_withheld = it2.total_yonkers_withheld
    total_ny_payments = _round2(ny_withheld + nyc_withheld + yonkers_withheld + empire_ctc)

    # ------------------------------------------------------------------
    # Balance / refund
    # ------------------------------------------------------------------
    balance_due = max(Decimal(0), total_ny_tax - total_ny_payments)
    refund = max(Decimal(0), total_ny_payments - total_ny_tax)

    # ------------------------------------------------------------------
    # Assemble IT-201
    # ------------------------------------------------------------------
    it201 = IT201(
        federal_agi=federal_agi,
        ny_additions=ny_additions,
        ny_subtractions=ny_subtractions,
        ny_agi=ny_agi,
        ny_standard_deduction=_round2(result["ny_standard_deduction"]),
        ny_itemized_deduction=ny_deduction_override or Decimal(0),
        ny_deduction_used=_round2(result["ny_deduction_used"]),
        ny_dependent_exemptions=_round2(result["ny_dependent_exemptions"]),
        ny_taxable_income=ny_taxable_income,
        ny_tax=state_tax,
        nyc_tax=city_tax,
        yonkers_surcharge=yonkers,
        ny_credits=ny_credits_applied,
        total_ny_tax=total_ny_tax,
        empire_state_ctc=empire_ctc,
        ny_withheld=ny_withheld,
        nyc_withheld=nyc_withheld,
        yonkers_withheld=yonkers_withheld,
        total_ny_payments=total_ny_payments,
        ny_amount_owed=balance_due,
        ny_refund=refund,
    )

    return ComputedNYReturn(
        it201=it201,
        it2=it2,
        ny_agi=ny_agi,
        ny_taxable_income=ny_taxable_income,
        total_ny_tax=total_ny_tax,
        total_ny_payments=total_ny_payments,
        balance_due=balance_due,
        refund=refund,
    )
