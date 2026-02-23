"""New York State income tax computation — IT-201 (full-year resident)."""

from __future__ import annotations

from decimal import Decimal

from pfile.compute._utils import load_ny as _load
from pfile.compute._utils import status_key as _status_key
from pfile.models.filer import FilingStatus, NYResidencyInfo


def _apply_brackets(income: Decimal, brackets: list[dict]) -> Decimal:
    if income <= 0:
        return Decimal(0)
    for bracket in reversed(brackets):
        if income > Decimal(str(bracket["min"])):
            excess = income - Decimal(str(bracket["min"]))
            return Decimal(str(bracket["base"])) + excess * Decimal(str(bracket["rate"]))
    return Decimal(0)


def ny_standard_deduction(status: FilingStatus, year: int = 2025) -> Decimal:
    """
    Return the NY standard deduction for the given filing status.

    Source: NY Tax Law §614; IT-201 instructions.
    """
    data = _load(year)["standard_deduction"]
    key = _status_key(status)
    return Decimal(str(data[key]))


def _ny_rate_schedule(taxable_income: Decimal, status: FilingStatus, year: int = 2025) -> Decimal:
    """
    Apply the NY tax rate schedule (base progressive brackets only).
    Do not call this directly for high-income filers; use ny_state_tax() instead.
    """
    data = _load(year)
    key = _status_key(status)
    return _apply_brackets(taxable_income, data["ny_state"][key])


def ny_benefit_recapture(
    taxable_income: Decimal,
    ny_agi: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute the NY Benefit Recapture surcharge added on top of the rate schedule
    for filers with NY AGI > $107,650.

    Implements Tax Computation Worksheets 1–16 from the IT-201-I instructions.
    Source: NY IT-201-I 2024 "Tax computation—NYS AGI of more than $107,650".

    Returns the ADDITIONAL amount to add to the rate-schedule tax.  Returns
    Decimal(0) when NY AGI ≤ $107,650 (no worksheet required).
    """
    data = _load(year)
    key = _status_key(status)
    cfg = data.get("benefit_recapture", {}).get(key)
    if not cfg:
        return Decimal(0)

    low_threshold = Decimal(str(cfg["low_agi_threshold"]))
    if ny_agi <= low_threshold:
        return Decimal(0)

    # Flat-top worksheet (AGI > $25 M): tax = taxable × flat_rate, no surcharge
    flat_top = cfg.get("flat_top", {})
    if ny_agi > Decimal(str(flat_top.get("agi_threshold", 0))):
        flat_rate = Decimal(str(flat_top["flat_rate"]))
        return taxable_income * flat_rate - _ny_rate_schedule(taxable_income, status, year)

    # Flat-recapture worksheet (Worksheets 1/7/12): low taxable income range
    fr = cfg["flat_recapture"]
    fr_ceiling = Decimal(str(fr["taxable_ceiling"]))
    fr_rate    = Decimal(str(fr["flat_rate"]))
    fr_full    = Decimal(str(fr["full_phase_agi"]))

    if taxable_income <= fr_ceiling:
        base_tax = _ny_rate_schedule(taxable_income, status, year)
        if ny_agi >= fr_full:
            # Fully phased in: tax = taxable × flat_rate (replace rate schedule)
            return taxable_income * fr_rate - base_tax
        else:
            # Partial phase-in: blend rate_schedule toward flat rate
            diff = taxable_income * fr_rate - base_tax
            fraction = (ny_agi - low_threshold) / Decimal("50000")
            fraction = min(fraction, Decimal(1))
            return diff * fraction

    # Standard recapture tiers (Worksheets 2–5 / 8–10 / 13–15)
    for tier in cfg["tiers"]:
        t_min = Decimal(str(tier["taxable_min"]))
        t_max = Decimal(str(tier["taxable_max"]))
        if t_min < taxable_income <= t_max:
            base      = Decimal(str(tier["recapture_base"]))
            benefit   = Decimal(str(tier["incremental_benefit"]))
            agi_thr   = Decimal(str(tier["agi_threshold"]))
            excess    = max(Decimal(0), ny_agi - agi_thr)
            fraction  = min(Decimal(1), excess / Decimal("50000"))
            return base + benefit * fraction

    return Decimal(0)


def ny_state_tax(
    taxable_income: Decimal,
    status: FilingStatus,
    year: int = 2025,
    ny_agi: Decimal | None = None,
) -> Decimal:
    """
    Compute NY state income tax from NY taxable income.

    If ``ny_agi`` is provided and exceeds $107,650, the Benefit Recapture
    worksheets are applied on top of the base rate schedule.

    Source: NY Tax Law §601; IT-201-I Tax Computation Worksheets.
    """
    base = _ny_rate_schedule(taxable_income, status, year)
    if ny_agi is not None:
        base += ny_benefit_recapture(taxable_income, ny_agi, status, year)
    return base


def nyc_tax(taxable_income: Decimal, status: FilingStatus, year: int = 2025) -> Decimal:
    """
    Compute NYC resident income tax.

    Source: NYC Administrative Code §11-1701.
    """
    data = _load(year)
    key = _status_key(status)
    return _apply_brackets(taxable_income, data["nyc"][key])


def yonkers_surcharge(
    ny_state_tax_amount: Decimal,
    residency: NYResidencyInfo,
    year: int = 2025,
) -> Decimal:
    """
    Compute Yonkers resident surcharge (16.75% of NY state tax liability).

    Source: Yonkers City Code; IT-201 instructions.
    """
    if not residency.yonkers_resident:
        return Decimal(0)
    data = _load(year)
    rate = Decimal(str(data["yonkers"]["resident_surcharge_rate"]))
    return ny_state_tax_amount * rate


def ny_social_security_subtraction(ss_benefits: Decimal) -> Decimal:
    """
    NY fully excludes Social Security benefits from income.

    Source: NY Tax Law §612(c)(3-a).
    """
    return ss_benefits


def ny_pension_subtraction(government_pension_income: Decimal, year: int = 2025) -> Decimal:
    """
    NY excludes up to $20,000 of government (federal, NY, military) pension income.

    Source: NY Tax Law §612(c)(3).
    """
    data = _load(year)["pension_exclusions"]
    limit = Decimal(str(data["government_pension_max"]))
    return min(government_pension_income, limit)


NY_DEPENDENT_EXEMPTION = Decimal("1000")  # $1,000 per dependent, IT-201 line 36


def compute_ny_tax(
    federal_agi: Decimal,
    ny_additions: Decimal,
    ny_subtractions: Decimal,
    status: FilingStatus,
    residency: NYResidencyInfo,
    year: int = 2025,
    ny_deduction_override: Decimal | None = None,
    num_dependents: int = 0,
) -> dict[str, Decimal]:
    """
    Full NY tax computation pipeline.

    If ``ny_deduction_override`` is provided it is used instead of the standard
    deduction (e.g. when the taxpayer itemizes on the NY return).

    ``num_dependents`` is the number of dependents claimed on the federal return.
    NY allows a $1,000 exemption per dependent (IT-201 line 36).

    Returns a dict with labelled intermediate values:
      ny_agi, ny_standard_deduction, ny_dependent_exemptions,
      ny_taxable_income, ny_tax, nyc_tax, yonkers_surcharge, total_ny_tax.

    Source: IT-201 instructions; NY Tax Law §616(a).
    """
    ny_agi = federal_agi + ny_additions - ny_subtractions
    std_ded = ny_standard_deduction(status, year)
    # Use itemized only when it exceeds the standard deduction — otherwise standard wins.
    ny_deduction = max(ny_deduction_override, std_ded) if ny_deduction_override is not None else std_ded
    ny_dependent_exemptions = NY_DEPENDENT_EXEMPTION * num_dependents
    ny_taxable_income = max(Decimal(0), ny_agi - ny_deduction - ny_dependent_exemptions)

    state_tax = ny_state_tax(ny_taxable_income, status, year, ny_agi=ny_agi)
    city_tax = nyc_tax(ny_taxable_income, status, year) if residency.nyc_resident else Decimal(0)
    yonkers = yonkers_surcharge(state_tax, residency, year)

    return {
        "ny_agi": ny_agi,
        "ny_standard_deduction": std_ded,
        "ny_deduction_used": ny_deduction,
        "ny_dependent_exemptions": ny_dependent_exemptions,
        "ny_taxable_income": ny_taxable_income,
        "ny_tax": state_tax,
        "nyc_tax": city_tax,
        "yonkers_surcharge": yonkers,
        "total_ny_tax": state_tax + city_tax + yonkers,
    }
