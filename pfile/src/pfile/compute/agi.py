"""AGI computation — gross income to Adjusted Gross Income."""

from __future__ import annotations

from decimal import Decimal

from pfile.compute.tax import taxable_social_security
from pfile.models.documents import F1099_R, SSA_1099, W2
from pfile.models.filer import FilingStatus
from pfile.models.forms import ScheduleB, ScheduleD, ScheduleE


def compute_gross_income(
    w2s: list[W2],
    schedule_b: ScheduleB,
    schedule_d: ScheduleD | None,
    schedule_e: ScheduleE | None,
    f1099_rs: list[F1099_R],
    ssa_1099s: list[SSA_1099],
    filing_status: FilingStatus,
    other_income: Decimal = Decimal(0),
    year: int = 2025,
) -> dict[str, Decimal]:
    """
    Compute each gross income component.

    Returns a dict with labelled amounts for traceability,
    plus a 'total' key.

    Source: IRC §61; 1040 instructions Lines 1-8.
    """
    wages = sum((w.box1_wages for w in w2s), Decimal(0))
    taxable_interest = schedule_b.total_taxable_interest        # Schedule B line 4
    ordinary_dividends = schedule_b.total_ordinary_dividends    # Schedule B line 6

    cap_gain = Decimal(0)
    if schedule_d:
        net = schedule_d.net_capital_gain_loss
        cap_gain = max(net, Decimal("-3000"))  # §1211(b) loss limit

    k1_income = schedule_e.net if schedule_e else Decimal(0)
    retirement_distributions = sum((f.box2a_taxable_amount for f in f1099_rs), Decimal(0))

    # Social Security: taxable portion (up to 85%) is computed after all other income is known.
    net_ss = sum((s.net_benefits for s in ssa_1099s), Decimal(0))
    agi_before_ss = (
        wages + taxable_interest + ordinary_dividends
        + cap_gain + k1_income + retirement_distributions + other_income
    )
    tax_exempt_interest = Decimal(0)  # TODO: pull from 1099-INT box 8 if needed
    ss_taxable = taxable_social_security(
        net_ss, agi_before_ss, tax_exempt_interest, filing_status, year
    )

    components = {
        "wages": wages,
        "taxable_interest": taxable_interest,
        "ordinary_dividends": ordinary_dividends,
        "capital_gain_loss": cap_gain,
        "k1_income": k1_income,
        "retirement_distributions": retirement_distributions,
        "taxable_ss": ss_taxable,
        "other_income": other_income,
    }
    components["total"] = sum(components.values())
    return components


def compute_agi(
    gross_components: dict[str, Decimal],
    se_tax_deduction: Decimal = Decimal(0),
    student_loan_interest: Decimal = Decimal(0),
    ira_deduction: Decimal = Decimal(0),
    other_adjustments: Decimal = Decimal(0),
) -> tuple[Decimal, dict[str, Decimal]]:
    """
    Compute AGI = Gross Income - Above-the-line adjustments.

    Returns (agi, adjustments_dict).

    Source: 1040 Schedule 1 Part II; IRC §62.
    """
    adjustments = {
        "se_tax_deduction": se_tax_deduction,
        "student_loan_interest": student_loan_interest,
        "ira_deduction": ira_deduction,
        "other_adjustments": other_adjustments,
    }
    total_adjustments = sum(adjustments.values())
    agi = gross_components["total"] - total_adjustments
    return agi, adjustments
