"""Schedule B — Interest and Ordinary Dividends."""

from __future__ import annotations

from decimal import Decimal

from pfile.models.documents import F1099_DIV, F1099_INT
from pfile.models.forms import ScheduleB


# Schedule B is required if total taxable interest > $1,500 or dividends > $1,500,
# or if you had a foreign account or trust.
_SCHEDULE_B_THRESHOLD = Decimal("1500")


def compute_schedule_b(
    int_forms: list[F1099_INT],
    div_forms: list[F1099_DIV],
) -> ScheduleB:
    """
    Compute Schedule B totals from all 1099-INT and 1099-DIV documents.

    Source: 1040 Schedule B instructions; IRC §61(a)(4) (interest),
            IRC §61(a)(7) (dividends).
    """
    interest_entries: list[tuple[str, Decimal]] = []
    dividend_entries: list[tuple[str, Decimal]] = []

    for form in int_forms:
        taxable = (
            form.box1_interest_income
            + form.box3_us_savings_bond_interest
            - form.box2_early_withdrawal_penalty
        )
        if taxable != Decimal(0):
            interest_entries.append((form.payer.name, taxable))

    for form in div_forms:
        if form.box1a_total_ordinary_dividends != Decimal(0):
            dividend_entries.append((form.payer.name, form.box1a_total_ordinary_dividends))

    total_interest = sum(amt for _, amt in interest_entries)
    total_dividends = sum(amt for _, amt in dividend_entries)

    return ScheduleB(
        interest_entries=interest_entries,
        total_taxable_interest=total_interest,
        dividend_entries=dividend_entries,
        total_ordinary_dividends=total_dividends,
        required=(
            total_interest > _SCHEDULE_B_THRESHOLD
            or total_dividends > _SCHEDULE_B_THRESHOLD
        ),
    )
