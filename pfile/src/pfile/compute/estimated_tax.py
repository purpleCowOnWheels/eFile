"""
Form 1040-ES — Estimated Tax for Individuals.

Computes quarterly estimated tax payments for the *following* tax year, based
on the current-year return and the IRS safe-harbor rules.

Safe-harbor rules (IRC §6654):
  - 100% of prior-year tax liability (if prior-year AGI ≤ $150,000 / $75,000 MFS), OR
  - 110% of prior-year tax liability (if prior-year AGI > $150,000 / $75,000 MFS), OR
  - 90% of current-year tax liability (annualised income method)

pFile uses the simpler 100%/110% prior-year safe-harbor because it only requires
data we already have from the current-year return.  The taxpayer can elect 90% if
their income will be significantly lower next year.

IRS due dates for 2026 estimated payments (tax year 2025 return):
  Q1: April 15, 2026
  Q2: June 16, 2026
  Q3: September 15, 2026
  Q4: January 15, 2027

Source: IRS Publication 505 (Tax Withholding and Estimated Tax),
        Form 1040-ES instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pfile.models.filer import FilingStatus
from pfile.models.forms import ComputedFederalReturn

# Quarter payment fractions: each quarter is 25% of annual estimate.
_QUARTER_FRACTION = Decimal("0.25")

# High-income threshold for 110% safe-harbor.
_HIGH_INCOME_THRESHOLD_JOINT = Decimal("150000")
_HIGH_INCOME_THRESHOLD_OTHER = Decimal("75000")  # MFS

# IRS due dates for estimated payments — keyed by next tax year.
_DUE_DATES: dict[int, list[date]] = {
    2025: [date(2025, 4, 15), date(2025, 6, 16), date(2025, 9, 15), date(2026, 1, 15)],
    2026: [date(2026, 4, 15), date(2026, 6, 16), date(2026, 9, 15), date(2027, 1, 15)],
    2027: [date(2027, 4, 15), date(2027, 6, 16), date(2027, 9, 15), date(2028, 1, 15)],
}


@dataclass(frozen=True)
class EstimatedTaxQuarter:
    quarter: int           # 1–4
    due_date: date
    payment: Decimal


@dataclass(frozen=True)
class EstimatedTaxPlan:
    """Computed 1040-ES plan for the next tax year."""
    current_tax_year: int
    next_tax_year: int
    prior_year_tax: Decimal
    safe_harbor_rate: Decimal       # 1.00 or 1.10
    annual_estimate: Decimal
    quarters: list[EstimatedTaxQuarter]
    method_note: str

    @property
    def total(self) -> Decimal:
        return sum(q.payment for q in self.quarters)


def compute_estimated_tax(
    result: ComputedFederalReturn,
    filing_status: FilingStatus,
) -> EstimatedTaxPlan:
    """
    Compute a 4-quarter estimated tax payment plan for the year following
    the return in ``result``.

    Uses the prior-year safe-harbor (100% or 110% depending on AGI).
    """
    current_year = result.form_1040  # type alias for brevity
    agi = current_year.line11_agi
    total_tax = current_year.line24_total_tax

    # Select safe-harbor rate
    is_mfs = filing_status == FilingStatus.MFS
    threshold = _HIGH_INCOME_THRESHOLD_OTHER if is_mfs else _HIGH_INCOME_THRESHOLD_JOINT
    rate = Decimal("1.10") if agi > threshold else Decimal("1.00")

    annual_estimate = (total_tax * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    quarterly = (annual_estimate * _QUARTER_FRACTION).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Re-balance so Q4 absorbs rounding remainder
    remainder = annual_estimate - quarterly * 3
    quarters_raw = [quarterly, quarterly, quarterly, remainder]

    # Determine next year (caller provides current year via context; default derived from AGI filing)
    # We'll accept an optional `current_tax_year` parameter; derive it here as 2025 default
    # since this will be called from the CLI with session.tax_year.
    # Actual year injection happens in generate_1040es() below.
    next_year = 2026  # will be overridden by generate_1040es
    due_dates = _DUE_DATES.get(next_year, _DUE_DATES[2026])

    quarters = [
        EstimatedTaxQuarter(quarter=i + 1, due_date=due_dates[i], payment=quarters_raw[i])
        for i in range(4)
    ]

    if rate > Decimal("1.00"):
        note = (
            f"Prior-year AGI ${agi:,.0f} exceeds ${threshold:,.0f} threshold — "
            "110% safe-harbor applied."
        )
    else:
        note = "100% of prior-year tax liability safe-harbor applied."

    return EstimatedTaxPlan(
        current_tax_year=0,  # filled by caller
        next_tax_year=next_year,
        prior_year_tax=total_tax,
        safe_harbor_rate=rate,
        annual_estimate=annual_estimate,
        quarters=quarters,
        method_note=note,
    )


def compute_estimated_tax_for_year(
    result: ComputedFederalReturn,
    filing_status: FilingStatus,
    current_tax_year: int,
) -> EstimatedTaxPlan:
    """
    Entry point used by the CLI and package generator.

    Computes the ES plan with the correct due dates for ``current_tax_year + 1``.
    """
    plan = compute_estimated_tax(result, filing_status)
    next_year = current_tax_year + 1
    due_dates = _DUE_DATES.get(next_year, [
        date(next_year, 4, 15),
        date(next_year, 6, 15),
        date(next_year, 9, 15),
        date(next_year + 1, 1, 15),
    ])

    quarterly = (plan.annual_estimate * _QUARTER_FRACTION).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    remainder = plan.annual_estimate - quarterly * 3
    quarters_raw = [quarterly, quarterly, quarterly, remainder]

    quarters = [
        EstimatedTaxQuarter(quarter=i + 1, due_date=due_dates[i], payment=quarters_raw[i])
        for i in range(4)
    ]

    return EstimatedTaxPlan(
        current_tax_year=current_tax_year,
        next_tax_year=next_year,
        prior_year_tax=plan.prior_year_tax,
        safe_harbor_rate=plan.safe_harbor_rate,
        annual_estimate=plan.annual_estimate,
        quarters=quarters,
        method_note=plan.method_note,
    )
