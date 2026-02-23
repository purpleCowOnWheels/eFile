"""FilingSession — the central state object for a pFile tax filing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Union

from pydantic import BaseModel, Field

from pfile.models.documents import (
    AnyDocument,
    F1099_B,
    F1099_DIV,
    F1099_INT,
    F1099_R,
    K1_1065,
    K1_1120S,
    SSA_1099,
    W2,
)
from pfile.models.filer import (
    DependentProfile,
    FilingStatus,
    TaxpayerProfile,
    SpouseProfile,
)
from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn


class SessionStatus(StrEnum):
    DRAFT = "draft"           # interview in progress
    REVIEWED = "reviewed"     # user has confirmed all extracted document data
    COMPUTED = "computed"     # tax math complete, awaiting user review
    COMPLETE = "complete"     # output package generated


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class DocumentSet(BaseModel):
    """All documents for a single filer (primary or spouse)."""

    w2s: list[W2] = Field(default_factory=list)
    k1_1065s: list[K1_1065] = Field(default_factory=list)
    k1_1120ss: list[K1_1120S] = Field(default_factory=list)
    f1099_ints: list[F1099_INT] = Field(default_factory=list)
    f1099_divs: list[F1099_DIV] = Field(default_factory=list)
    f1099_bs: list[F1099_B] = Field(default_factory=list)
    f1099_rs: list[F1099_R] = Field(default_factory=list)
    ssa_1099s: list[SSA_1099] = Field(default_factory=list)

    def all_documents(self) -> list[AnyDocument]:
        return (
            self.w2s
            + self.k1_1065s
            + self.k1_1120ss
            + self.f1099_ints
            + self.f1099_divs
            + self.f1099_bs
            + self.f1099_rs
            + self.ssa_1099s
        )


class FilingSession(BaseModel):
    """
    Central state object for one tax year's filing.
    Persisted to ~/.pfile/sessions/<id>.json.
    """

    id: str = Field(default_factory=_new_id)
    tax_year: int
    filing_status: FilingStatus

    primary: TaxpayerProfile | None = None
    spouse: SpouseProfile | None = None           # MFJ / MFS only
    dependents: list[DependentProfile] = Field(default_factory=list)

    primary_documents: DocumentSet = Field(default_factory=DocumentSet)
    spouse_documents: DocumentSet = Field(default_factory=DocumentSet)

    # ------------------------------------------------------------------
    # Manual overrides / carry-forwards (populated from prior-year ingest
    # or via CLI interview)
    # ------------------------------------------------------------------

    # Federal line 25c: withholding from "other forms" not captured by standard
    # document types (e.g., W-2G gambling, 1042-S, backup withholding).
    other_withholding: Decimal = Decimal(0)

    # Federal line 26: estimated tax payments applied from prior-year refund
    # or quarterly estimated payments made during the year.
    estimated_tax_paid: Decimal = Decimal(0)

    # Federal: prior-year capital loss carryover (negative = loss).
    # Sourced from Schedule D of the prior-year return.
    capital_loss_carryover: Decimal = Decimal(0)

    # NY: itemized deduction amount if the filer is using IT-196 instead of
    # the NY standard deduction.  Set to None to use the standard deduction.
    ny_itemized_deduction: Decimal | None = None

    # NY: prior-year credit amounts carried forward or claimed this year.
    # Keys are credit names ("solar_it255", "empire_state_ctc", etc.)
    ny_credits: dict[str, Decimal] = Field(default_factory=dict)

    computed_federal: ComputedFederalReturn | None = None
    computed_ny: ComputedNYReturn | None = None

    status: SessionStatus = SessionStatus.DRAFT
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = _now()

    @property
    def is_mfj(self) -> bool:
        return self.filing_status == FilingStatus.MFJ

    @property
    def needs_ny(self) -> bool:
        """True if the primary filer has NY residency info."""
        return self.primary is not None and self.primary.ny_residency is not None

    @property
    def display_name(self) -> str:
        if self.primary:
            name = f"{self.primary.first_name} {self.primary.last_name}"
            if self.is_mfj and self.spouse:
                name += f" & {self.spouse.first_name} {self.spouse.last_name}"
            return name
        return f"Session {self.id[:8]}"

    def has_low_confidence_documents(self, threshold: float = 0.8) -> bool:
        """True if any parsed document has fields below the confidence threshold."""
        for doc in (
            self.primary_documents.all_documents()
            + self.spouse_documents.all_documents()
        ):
            if hasattr(doc, "confidence") and doc.confidence.low_confidence_fields(threshold):
                return True
        return False
