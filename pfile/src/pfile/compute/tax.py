"""Federal income tax computations — ordinary income, LTCG/qualified dividends, NIIT."""

from __future__ import annotations

from decimal import Decimal

from pfile.compute._utils import load_federal as _load
from pfile.compute._utils import status_key as _status_key
from pfile.models.filer import FilingStatus


def _apply_brackets(income: Decimal, brackets: list[dict]) -> Decimal:
    """Apply progressive brackets and return the tax owed."""
    if income <= 0:
        return Decimal(0)
    for bracket in reversed(brackets):
        if income > Decimal(str(bracket["min"])):
            excess = income - Decimal(str(bracket["min"]))
            return Decimal(str(bracket["base"])) + excess * Decimal(str(bracket["rate"]))
    return Decimal(0)


def ordinary_income_tax(
    taxable_income: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute federal income tax on ordinary taxable income using progressive brackets.

    Source: IRC §1; Rev. Proc. 2024-40.
    """
    data = _load(year)
    key = _status_key(status)
    return _apply_brackets(taxable_income, data["brackets"][key])


def qualified_div_ltcg_tax(
    qualified_dividends: Decimal,
    net_ltcg: Decimal,
    taxable_income: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute the preferential tax on qualified dividends and long-term capital gains.

    The 0/15/20% rates apply to the LESSER of (qualified divs + LTCG) and the
    amount of taxable income that falls in the preferential rate brackets.

    Source: IRC §1(h); Rev. Proc. 2024-40.
    """
    pref_income = max(Decimal(0), qualified_dividends + net_ltcg)
    if pref_income == 0:
        return Decimal(0)

    data = _load(year)
    key = _status_key(status)
    rates = data["ltcg_rates"][key]

    # The preferential income sits on top of ordinary income.
    # ordinary_income = taxable_income - pref_income (floored at 0)
    ordinary_base = max(Decimal(0), taxable_income - pref_income)

    tax = Decimal(0)
    # IRS Qualified Dividends and Capital Gain Tax Worksheet, step 9:
    # tax preferential rates on the *lesser* of (QD + LTCG) or taxable income.
    remaining = min(pref_income, taxable_income)

    for band in rates:
        band_max = Decimal(str(band["max"])) if band["max"] else Decimal("Inf")
        band_min = Decimal(str(band["min"]))
        rate = Decimal(str(band["rate"]))

        # How much of pref_income falls in this band?
        band_start = max(ordinary_base, band_min)
        band_end = band_max
        if band_start >= band_end:
            continue
        in_band = min(remaining, band_end - band_start)
        if in_band <= 0:
            continue
        tax += in_band * rate
        remaining -= in_band
        if remaining <= 0:
            break

    return tax


def net_investment_income_tax(
    net_investment_income: Decimal,
    agi: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    3.8% NIIT on the lesser of net investment income or AGI above the threshold.

    Source: IRC §1411.
    """
    data = _load(year)["niit"]
    key_map = {
        FilingStatus.SINGLE: "threshold_single",
        FilingStatus.MFJ:    "threshold_mfj",
        FilingStatus.MFS:    "threshold_mfs",
        FilingStatus.HOH:    "threshold_hoh",
        FilingStatus.QSS:    "threshold_mfj",
    }
    threshold = Decimal(str(data[key_map[status]]))
    excess_agi = max(Decimal(0), agi - threshold)
    base = min(net_investment_income, excess_agi)
    return (base * Decimal(str(data["rate"]))).quantize(Decimal("0.01"))


def additional_medicare_tax(
    wages_and_se: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    0.9% Additional Medicare Tax on wages/SE income above threshold.

    Source: IRC §3103.
    """
    data = _load(year)["additional_medicare"]
    key_map = {
        FilingStatus.SINGLE: "threshold_single",
        FilingStatus.MFJ:    "threshold_mfj",
        FilingStatus.MFS:    "threshold_mfs",
        FilingStatus.HOH:    "threshold_single",
        FilingStatus.QSS:    "threshold_mfj",
    }
    threshold = Decimal(str(data[key_map[status]]))
    base = max(Decimal(0), wages_and_se - threshold)
    return (base * Decimal(str(data["rate"]))).quantize(Decimal("0.01"))


def taxable_social_security(
    net_ss_benefits: Decimal,
    agi_before_ss: Decimal,
    tax_exempt_interest: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute the taxable portion of Social Security benefits.

    Combined income = AGI (before SS) + 50% of SS benefits + tax-exempt interest.
    Up to 85% of benefits may be taxable depending on combined income.

    Source: IRC §86; IRS Pub. 915.
    """
    if net_ss_benefits <= 0:
        return Decimal(0)

    data = _load(year)["social_security"]
    key = "mfj_qss" if status in (FilingStatus.MFJ, FilingStatus.QSS) else "single_hoh_mfs"
    thresholds = data[key]

    combined = agi_before_ss + tax_exempt_interest + (net_ss_benefits * Decimal("0.5"))
    tier1_lower = Decimal(str(thresholds["tier1_lower"]))
    tier1_upper = Decimal(str(thresholds["tier1_upper"]))

    if combined <= tier1_lower:
        return Decimal(0)
    elif combined <= tier1_upper:
        # Up to 50% taxable
        taxable = min(
            net_ss_benefits * Decimal("0.5"),
            (combined - tier1_lower) * Decimal("0.5"),
        )
    else:
        # Up to 85% taxable
        taxable = min(
            net_ss_benefits * Decimal("0.85"),
            Decimal("0.85") * (combined - tier1_upper)
            + Decimal("0.5") * min(net_ss_benefits, tier1_upper - tier1_lower),
        )

    return taxable.quantize(Decimal("0.01"))
