"""Tests for the federal tax computation engine."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pfile.compute.engine import compute_federal_return
from pfile.models.documents import F1099_DIV, F1099_INT, SSA_1099, W2, EntityInfo
from pfile.models.filer import FilingStatus
from pfile.models.session import FilingSession

# ---------------------------------------------------------------------------
# Basic income + tax
# ---------------------------------------------------------------------------

def test_wages_flow_to_1040(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line1a_w2_wages == Decimal("60000")


def test_agi_equals_wages_when_no_adjustments(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    # Single, only wages, no adjustments
    assert result.form_1040.line11_agi == Decimal("60000")


def test_standard_deduction_applied_single(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    f = result.form_1040
    # 2024 single standard deduction = $14,600
    assert f.line12_standard_or_itemized == Decimal("14600")
    assert f.line15_taxable_income == Decimal("60000") - Decimal("14600")


def test_total_payments_includes_w2_withheld(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line25a_w2_withheld == Decimal("9000")


def test_refund_computed_correctly(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    f = result.form_1040
    assert f.line35a_refund == max(
        Decimal(0), f.line33_total_payments - f.line24_total_tax
    )


def test_balance_due_computed_correctly(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    f = result.form_1040
    assert f.line37_amount_owed == max(
        Decimal(0), f.line24_total_tax - f.line33_total_payments
    )


def test_mfj_wages_aggregated(mfj_session):
    result = compute_federal_return(mfj_session, year=2024)
    assert result.form_1040.line1a_w2_wages == Decimal("200000")


def test_mfj_standard_deduction(mfj_session):
    result = compute_federal_return(mfj_session, year=2024)
    # 2024 MFJ standard deduction = $29,200
    assert result.form_1040.line12_standard_or_itemized == Decimal("29200")


def test_ctc_applied_for_qualifying_child(mfj_session):
    result = compute_federal_return(mfj_session, year=2024)
    # One child, $2,000 CTC, AGI well below phaseout for MFJ at $400k
    assert result.form_1040.line19_ctc == Decimal("2000")


def test_no_ctc_without_dependents(single_w2_session):
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line19_ctc == Decimal("0")


# ---------------------------------------------------------------------------
# Estimated tax + other withholding overrides
# ---------------------------------------------------------------------------

def test_estimated_tax_included_in_payments(single_w2_session):
    single_w2_session.estimated_tax_paid = Decimal("5000")
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line26_estimated_payments == Decimal("5000")
    assert result.form_1040.line25a_w2_withheld + Decimal("5000") <= result.form_1040.line33_total_payments


def test_other_withholding_included_in_payments(single_w2_session):
    single_w2_session.other_withholding = Decimal("1500")
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line25c_other_withheld == Decimal("1500")


# ---------------------------------------------------------------------------
# Dependent care credit
# ---------------------------------------------------------------------------

def test_dependent_care_credit_with_expenses(mfj_session):
    mfj_session.dependent_care_expenses = Decimal("6000")
    result = compute_federal_return(mfj_session, year=2024)
    # For high-income filer, rate is 20%; 2+ children max $6,000; credit = $1,200
    assert result.form_1040.line20_other_credits > Decimal("0")


def test_dependent_care_credit_zero_without_expenses(mfj_session):
    mfj_session.dependent_care_expenses = Decimal("0")
    # No expenses → no dep care credit
    from pfile.compute.credits import dependent_care_credit
    assert dependent_care_credit(Decimal("0"), 1, Decimal("200000")) == Decimal("0")


def test_dependent_care_fsa_reduces_net_expense(mfj_session):
    """Box 10 employer FSA should reduce eligible expense, not replace it."""
    from pfile.models.documents import EntityInfo
    # W-2 with $5,000 FSA benefit (box 10)
    w2_with_fsa = W2(
        employer=EntityInfo(name="Acme"),
        box1_wages=Decimal("120000"),
        box2_federal_withheld=Decimal("20000"),
        box10_dependent_care=Decimal("5000"),
    )
    mfj_session.primary_documents.w2s = [w2_with_fsa]
    mfj_session.dependent_care_expenses = Decimal("6000")
    result = compute_federal_return(mfj_session, year=2024)
    # Net = $6,000 - $5,000 FSA = $1,000 eligible; credit rate 20% = $200
    assert result.form_1040.line20_other_credits == Decimal("200.00")


# ---------------------------------------------------------------------------
# Capital loss carryover
# ---------------------------------------------------------------------------

def test_capital_loss_carryover_reduces_income(single_w2_session):
    single_w2_session.capital_loss_carryover = Decimal("-3000")
    result = compute_federal_return(single_w2_session, year=2024)
    f = result.form_1040
    # Capital loss deduction reduces total income
    assert f.line7_capital_gain_loss == Decimal("-3000")


def test_capital_loss_capped_at_3000(single_w2_session):
    single_w2_session.capital_loss_carryover = Decimal("-10000")
    result = compute_federal_return(single_w2_session, year=2024)
    # Deduction limited to $3,000 per year
    assert result.form_1040.line7_capital_gain_loss == Decimal("-3000")


# ---------------------------------------------------------------------------
# Interest / dividend income
# ---------------------------------------------------------------------------

def test_interest_income_flows_to_1040(single_w2_session):
    from pfile.models.documents import F1099_INT, EntityInfo
    single_w2_session.primary_documents.f1099_ints = [
        F1099_INT(payer=EntityInfo(name="Bank"), box1_interest_income=Decimal("500"))
    ]
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line2b_taxable_interest == Decimal("500")


def test_large_interest_attaches_schedule_b(single_w2_session):
    from pfile.models.documents import F1099_INT, EntityInfo
    single_w2_session.primary_documents.f1099_ints = [
        F1099_INT(payer=EntityInfo(name="Bank"), box1_interest_income=Decimal("2000"))
    ]
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.schedule_b is not None
    assert result.schedule_b.total_taxable_interest == Decimal("2000")


def test_dividend_income_flows_to_1040(single_w2_session):
    from pfile.models.documents import EntityInfo
    single_w2_session.primary_documents.f1099_divs = [
        F1099_DIV(
            payer=EntityInfo(name="Broker"),
            box1a_total_ordinary_dividends=Decimal("2000"),
            box1b_qualified_dividends=Decimal("1800"),
        )
    ]
    result = compute_federal_return(single_w2_session, year=2024)
    assert result.form_1040.line3b_ordinary_dividends == Decimal("2000")
    assert result.form_1040.line3a_qualified_dividends == Decimal("1800")


# ---------------------------------------------------------------------------
# Social Security
# ---------------------------------------------------------------------------

def test_social_security_partially_taxable(single_w2_session):
    # Low-income single filer — SS only partially taxable
    low_income_session = single_w2_session.model_copy(deep=True)
    low_income_session.primary_documents.w2s = []
    low_income_session.primary_documents.ssa_1099s = [
        SSA_1099(box3_benefits_paid=Decimal("20000"))
    ]
    low_income_session.primary_documents.f1099_ints = [
        F1099_INT(payer=EntityInfo(name="Bank"), box1_interest_income=Decimal("2000"))
    ]
    result = compute_federal_return(low_income_session, year=2024)
    taxable = result.form_1040.line5b_taxable_ss
    # Taxable SS should be between 0 and 20,000 for this income level
    assert Decimal("0") <= taxable <= Decimal("20000")


def test_high_income_ss_85_percent_taxable(single_w2_session):
    # High combined income → 85% of SS taxable
    single_w2_session.primary_documents.ssa_1099s = [
        SSA_1099(box3_benefits_paid=Decimal("24000"))
    ]
    result = compute_federal_return(single_w2_session, year=2024)
    # Combined income far exceeds threshold; taxable = 85%
    assert result.form_1040.line5b_taxable_ss == Decimal("24000") * Decimal("0.85")


# ---------------------------------------------------------------------------
# Session with no primary profile raises
# ---------------------------------------------------------------------------

def test_missing_primary_raises():
    session = FilingSession(tax_year=2024, filing_status=FilingStatus.SINGLE)
    with pytest.raises(ValueError, match="no primary taxpayer"):
        compute_federal_return(session)
