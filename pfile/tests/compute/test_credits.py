"""Tests for individual credit computations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pfile.compute.credits import (
    child_tax_credit,
    dependent_care_credit,
    empire_state_child_credit,
)
from pfile.models.filer import DependentProfile, FilingStatus


def _child(ctc: bool = True) -> DependentProfile:
    return DependentProfile(
        first_name="Kid", last_name="Doe", ssn="123-45-6789",
        dob=date(2015, 1, 1), relationship="child",
        child_tax_credit_eligible=ctc,
    )


# ---------------------------------------------------------------------------
# Child Tax Credit
# ---------------------------------------------------------------------------

class TestChildTaxCredit:
    def test_single_qualifying_child(self):
        credit = child_tax_credit([_child()], Decimal("50000"), FilingStatus.SINGLE, year=2024)
        assert credit == Decimal("2000")

    def test_two_qualifying_children(self):
        credit = child_tax_credit([_child(), _child()], Decimal("50000"), FilingStatus.MFJ, year=2024)
        assert credit == Decimal("4000")

    def test_no_qualifying_children_returns_zero(self):
        non_qualifying = _child(ctc=False)
        assert child_tax_credit([non_qualifying], Decimal("50000"), FilingStatus.SINGLE, year=2024) == Decimal("0")

    def test_phaseout_single_above_200k(self):
        credit = child_tax_credit([_child()], Decimal("210000"), FilingStatus.SINGLE, year=2024)
        # $200k threshold, $10k over → 10 × $50 = $500 reduction → $1,500
        assert credit == Decimal("1500")

    def test_fully_phased_out(self):
        credit = child_tax_credit([_child()], Decimal("250000"), FilingStatus.SINGLE, year=2024)
        assert credit == Decimal("0")

    def test_mfj_phaseout_threshold_higher(self):
        # MFJ threshold = $400k; $390k → no phaseout
        credit = child_tax_credit([_child()], Decimal("390000"), FilingStatus.MFJ, year=2024)
        assert credit == Decimal("2000")


# ---------------------------------------------------------------------------
# Dependent Care Credit
# ---------------------------------------------------------------------------

class TestDependentCareCredit:
    def test_low_income_35pct_rate(self):
        # AGI ≤ $15k → 35% rate; 1 child, $3,000 expenses
        credit = dependent_care_credit(Decimal("3000"), 1, Decimal("10000"), year=2024)
        assert credit == Decimal("1050.00")

    def test_high_income_20pct_rate(self):
        # AGI > $43k → minimum 20% rate; 2 children, $6,000 max
        credit = dependent_care_credit(Decimal("6000"), 2, Decimal("200000"), year=2024)
        assert credit == Decimal("1200.00")

    def test_expenses_capped_at_3000_one_child(self):
        credit = dependent_care_credit(Decimal("10000"), 1, Decimal("50000"), year=2024)
        # Max expenses for 1 child = $3,000
        capped_credit = dependent_care_credit(Decimal("3000"), 1, Decimal("50000"), year=2024)
        assert credit == capped_credit

    def test_expenses_capped_at_6000_two_children(self):
        credit = dependent_care_credit(Decimal("10000"), 2, Decimal("50000"), year=2024)
        capped_credit = dependent_care_credit(Decimal("6000"), 2, Decimal("50000"), year=2024)
        assert credit == capped_credit

    def test_zero_expenses_returns_zero(self):
        assert dependent_care_credit(Decimal("0"), 1, Decimal("50000"), year=2024) == Decimal("0")

    def test_zero_children_returns_zero(self):
        assert dependent_care_credit(Decimal("5000"), 0, Decimal("50000"), year=2024) == Decimal("0")


# ---------------------------------------------------------------------------
# Empire State Child Credit
# ---------------------------------------------------------------------------

class TestEmpireStateChildCredit:
    def test_low_income_uses_floor(self):
        # FAGI well below $110k MFJ threshold → $100/child floor may apply
        credit = empire_state_child_credit(
            [_child()], Decimal("50000"), FilingStatus.MFJ, year=2024
        )
        # 33% of pre-TCJA $1,000 = $330; floor $100; max($330, $100) = $330
        assert credit == Decimal("330")

    def test_high_income_zero(self):
        # FAGI well above $110k → pre-TCJA credit phases out → $0
        credit = empire_state_child_credit(
            [_child()], Decimal("500000"), FilingStatus.MFJ, year=2024
        )
        assert credit == Decimal("0")

    def test_no_qualifying_children_zero(self):
        assert empire_state_child_credit(
            [_child(ctc=False)], Decimal("50000"), FilingStatus.SINGLE, year=2024
        ) == Decimal("0")
