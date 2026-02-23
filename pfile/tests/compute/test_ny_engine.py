"""Tests for the NY State tax computation engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pfile.compute.engine import compute_federal_return
from pfile.compute.state.engine_ny import compute_ny_return
from pfile.models.documents import W2, EntityInfo
from pfile.models.session import DocumentSet, FilingSession
from pfile.models.filer import FilingStatus, NYResidencyInfo


def _compute_both(session: FilingSession, year: int = 2024):
    federal = compute_federal_return(session, year=year)
    ny = compute_ny_return(session, federal, year=year)
    return federal, ny


# ---------------------------------------------------------------------------
# Basic NY income flow
# ---------------------------------------------------------------------------

def test_ny_agi_equals_federal_agi_no_addbacks(single_w2_session):
    federal, ny = _compute_both(single_w2_session)
    # No NY additions/subtractions for a simple W-2 filer
    assert ny.it201.ny_agi == federal.form_1040.line11_agi


def test_ny_standard_deduction_single(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    # 2024 NY standard deduction for single = $8,000
    assert ny.it201.ny_deduction_used == Decimal("8000")


def test_ny_standard_deduction_mfj(mfj_session):
    _, ny = _compute_both(mfj_session)
    # 2024 NY MFJ standard deduction = $16,050
    assert ny.it201.ny_deduction_used == Decimal("16050")


def test_ny_taxable_income_less_than_agi(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.ny_taxable_income < ny.it201.ny_agi


def test_ny_tax_positive(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.ny_tax > Decimal("0")


def test_ny_withheld_from_w2(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    # W-2 box 17 = $2,000 in fixture
    assert ny.it201.ny_withheld == Decimal("2000")


def test_ny_refund_or_balance_consistent(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    it = ny.it201
    if it.ny_amount_owed > 0:
        assert it.ny_refund == Decimal("0")
    else:
        assert it.ny_amount_owed == Decimal("0")


# ---------------------------------------------------------------------------
# IT-2 W-2 summary
# ---------------------------------------------------------------------------

def test_it2_entry_created_for_ny_w2(single_w2_session):
    _, ny = _compute_both(single_w2_session)
    assert len(ny.it2.entries) == 1
    assert ny.it2.entries[0].employer_name == "Acme Corp"


def test_non_ny_w2_excluded_from_it2(single_w2_session):
    """W-2 from another state must not appear on IT-2."""
    from pfile.models.documents import W2, EntityInfo
    out_of_state = W2(
        employer=EntityInfo(name="California Corp"),
        box1_wages=Decimal("30000"),
        box2_federal_withheld=Decimal("5000"),
        box16_state_wages=Decimal("30000"),
        box17_state_withheld=Decimal("1500"),
        box15_state="CA",
    )
    single_w2_session.primary_documents.w2s.append(out_of_state)
    _, ny = _compute_both(single_w2_session)
    employer_names = [e.employer_name for e in ny.it2.entries]
    assert "California Corp" not in employer_names
    assert "Acme Corp" in employer_names


def test_it2_total_wages_aggregated(mfj_session):
    federal, ny = _compute_both(mfj_session)
    # Both W-2s are NY; total NY wages = 120k + 80k
    assert ny.it2.total_ny_wages == Decimal("200000")


# ---------------------------------------------------------------------------
# NY itemized deduction override
# ---------------------------------------------------------------------------

def test_ny_itemized_deduction_overrides_standard(single_w2_session):
    single_w2_session.ny_itemized_deduction = Decimal("12000")
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.ny_deduction_used == Decimal("12000")
    assert ny.it201.ny_itemized_deduction == Decimal("12000")


def test_ny_standard_used_when_itemized_lower(single_w2_session):
    # Itemized of $5,000 is below standard $8,000 for single → standard wins
    single_w2_session.ny_itemized_deduction = Decimal("5000")
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.ny_deduction_used == Decimal("8000")


# ---------------------------------------------------------------------------
# Dependents & Empire State CTC
# ---------------------------------------------------------------------------

def test_ny_dependent_exemption_applied(mfj_session):
    _, ny = _compute_both(mfj_session)
    # $1,000 per dependent
    assert ny.it201.ny_dependent_exemptions == Decimal("1000")


def test_empire_state_ctc_zero_high_income(mfj_session):
    """High-income filers (above $110K MFJ) → ESCTC = $0."""
    # fixture has $200K combined wages — above pre-TCJA phase-out ceiling
    _, ny = _compute_both(mfj_session)
    assert ny.it201.empire_state_ctc == Decimal("0")


# ---------------------------------------------------------------------------
# NYC / Yonkers
# ---------------------------------------------------------------------------

def test_nyc_tax_when_nyc_resident(single_w2_session):
    single_w2_session.primary.ny_residency.nyc_resident = True
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.nyc_tax > Decimal("0")


def test_no_nyc_tax_when_not_resident(single_w2_session):
    single_w2_session.primary.ny_residency.nyc_resident = False
    _, ny = _compute_both(single_w2_session)
    assert ny.it201.nyc_tax == Decimal("0")


def test_yonkers_withheld_from_w2(single_w2_session):
    """Yonkers local withholding should flow into total_ny_payments."""
    from pfile.models.documents import W2, EntityInfo
    w2_yonkers = W2(
        employer=EntityInfo(name="Yonkers Corp"),
        box1_wages=Decimal("60000"),
        box2_federal_withheld=Decimal("9000"),
        box16_state_wages=Decimal("60000"),
        box17_state_withheld=Decimal("2000"),
        box15_state="NY",
        box18_local_wages=Decimal("60000"),
        box19_local_withheld=Decimal("1200"),
        box20_locality="Yonkers",
    )
    single_w2_session.primary_documents.w2s = [w2_yonkers]
    single_w2_session.primary.ny_residency.yonkers_resident = True
    _, ny = _compute_both(single_w2_session)
    assert ny.it2.total_yonkers_withheld == Decimal("1200")
