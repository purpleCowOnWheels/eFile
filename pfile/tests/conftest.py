"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pfile.models.documents import W2, EntityInfo
from pfile.models.filer import (
    Address,
    DependentProfile,
    FilingStatus,
    NYResidencyInfo,
    TaxpayerProfile,
)
from pfile.models.session import DocumentSet, FilingSession


def _address() -> Address:
    return Address(street="1 Main St", city="Albany", state="NY", zip_code="12201")


def _primary(
    ssn: str = "111-22-3333",
    ny: bool = True,
) -> TaxpayerProfile:
    return TaxpayerProfile(
        first_name="Jane",
        last_name="Doe",
        ssn=ssn,
        dob=date(1985, 6, 15),
        address=_address(),
        ny_residency=NYResidencyInfo(county="Albany", full_year_resident=True) if ny else None,
    )


def _dependent(ctc: bool = True) -> DependentProfile:
    return DependentProfile(
        first_name="Kid",
        last_name="Doe",
        ssn="444-55-6666",
        dob=date(2015, 3, 1),
        relationship="child",
        child_tax_credit_eligible=ctc,
    )


def _w2(wages: float = 50_000.0, withheld: float = 8_000.0, state: str = "NY") -> W2:
    return W2(
        employer=EntityInfo(name="Acme Corp", ein="12-3456789"),
        box1_wages=Decimal(str(wages)),
        box2_federal_withheld=Decimal(str(withheld)),
        box16_state_wages=Decimal(str(wages)),
        box17_state_withheld=Decimal("2000"),
        box15_state=state,
    )


@pytest.fixture
def single_w2_session() -> FilingSession:
    """Single filer, one W-2, NY resident, no dependents."""
    docs = DocumentSet(w2s=[_w2(wages=60_000, withheld=9_000)])
    return FilingSession(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        primary=_primary(),
        primary_documents=docs,
    )


@pytest.fixture
def mfj_session() -> FilingSession:
    """MFJ, two W-2s, NY resident, one CTC-eligible child."""
    primary_docs = DocumentSet(w2s=[_w2(wages=120_000, withheld=20_000)])
    spouse_docs = DocumentSet(w2s=[_w2(wages=80_000, withheld=13_000)])
    return FilingSession(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        primary=_primary(),
        primary_documents=primary_docs,
        spouse_documents=spouse_docs,
        dependents=[_dependent()],
    )
