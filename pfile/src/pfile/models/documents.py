"""Input document models — all documents a filer can provide."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Union

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class Money(Decimal):
    """A non-negative dollar amount."""


class EntityInfo(BaseModel):
    """Payer / employer identifying info."""

    name: str
    ein: str | None = None
    address: str | None = None


class ParseConfidence(BaseModel):
    """Per-field confidence scores from LLM extraction (0.0–1.0)."""

    scores: dict[str, float] = Field(default_factory=dict)

    def low_confidence_fields(self, threshold: float = 0.8) -> list[str]:
        return [field for field, score in self.scores.items() if score < threshold]


# ---------------------------------------------------------------------------
# W-2
# ---------------------------------------------------------------------------


class Box12Entry(BaseModel):
    code: str
    amount: Decimal


class W2(BaseModel):
    """IRS Form W-2 — Wage and Tax Statement."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    employer: EntityInfo
    employee_ssn: str | None = None

    # Core wage/withholding boxes
    box1_wages: Decimal = Decimal(0)
    box2_federal_withheld: Decimal = Decimal(0)
    box3_ss_wages: Decimal = Decimal(0)
    box4_ss_withheld: Decimal = Decimal(0)
    box5_medicare_wages: Decimal = Decimal(0)
    box6_medicare_withheld: Decimal = Decimal(0)
    box7_ss_tips: Decimal = Decimal(0)
    box8_allocated_tips: Decimal = Decimal(0)
    box10_dependent_care: Decimal = Decimal(0)
    box11_nonqualified_plans: Decimal = Decimal(0)

    # Box 12 codes (e.g. 12a=D for 401k contributions)
    box12: list[Box12Entry] = Field(default_factory=list)

    # Box 13 checkboxes
    box13_statutory_employee: bool = False
    box13_retirement_plan: bool = False
    box13_third_party_sick: bool = False

    # Box 14 — other (freeform)
    box14: dict[str, str] = Field(default_factory=dict)

    # State / local (NY)
    box15_state: str | None = None
    box15_employer_state_id: str | None = None
    box16_state_wages: Decimal = Decimal(0)
    box17_state_withheld: Decimal = Decimal(0)
    box18_local_wages: Decimal = Decimal(0)
    box19_local_withheld: Decimal = Decimal(0)
    box20_locality: str | None = None


# ---------------------------------------------------------------------------
# K-1 (Form 1065) — Partnership
# ---------------------------------------------------------------------------


class K1_1065(BaseModel):
    """Schedule K-1 (Form 1065) — Partner's Share of Income, Deductions, Credits, etc."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    partnership: EntityInfo
    partner_ssn_or_ein: str | None = None
    tax_year: int | None = None
    final_k1: bool = False
    amended_k1: bool = False

    # Partner's share of profit/loss/capital
    profit_share_pct: Decimal | None = None
    loss_share_pct: Decimal | None = None
    capital_share_pct: Decimal | None = None

    # Income / loss
    box1_ordinary_income: Decimal = Decimal(0)
    box2_net_rental_re_income: Decimal = Decimal(0)
    box3_other_rental_income: Decimal = Decimal(0)
    box4_guaranteed_payments_services: Decimal = Decimal(0)
    box5_guaranteed_payments_capital: Decimal = Decimal(0)
    box6a_net_ltcg: Decimal = Decimal(0)
    box7_net_stcg: Decimal = Decimal(0)
    box8_collectibles_gain: Decimal = Decimal(0)
    box9a_section_1231_gain: Decimal = Decimal(0)
    box10_other_income: Decimal = Decimal(0)

    # Deductions
    box11_section_179: Decimal = Decimal(0)
    box12_other_deductions: dict[str, Decimal] = Field(default_factory=dict)

    # Credits (code → amount)
    box13_credits: dict[str, Decimal] = Field(default_factory=dict)

    # Self-employment
    box14_self_employment: Decimal = Decimal(0)

    # AMT
    box15_amt_items: dict[str, Decimal] = Field(default_factory=dict)

    # Tax-exempt / nondeductible
    box16_tax_exempt_income: dict[str, Decimal] = Field(default_factory=dict)

    # Distributions
    box19_distributions: Decimal = Decimal(0)

    # Other info — QBI, UBIA, etc. (code → value)
    box20_other_info: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# K-1 (Form 1120S) — S-Corporation
# ---------------------------------------------------------------------------


class K1_1120S(BaseModel):
    """Schedule K-1 (Form 1120S) — Shareholder's Share of Income, Deductions, Credits, etc."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    corporation: EntityInfo
    shareholder_ssn_or_ein: str | None = None
    tax_year: int | None = None
    final_k1: bool = False
    amended_k1: bool = False

    ownership_pct: Decimal | None = None

    # Income / loss
    box1_ordinary_income: Decimal = Decimal(0)
    box2_net_rental_re_income: Decimal = Decimal(0)
    box3_other_rental_income: Decimal = Decimal(0)
    box4_interest_income: Decimal = Decimal(0)
    box5a_ordinary_dividends: Decimal = Decimal(0)
    box5b_qualified_dividends: Decimal = Decimal(0)
    box6_royalties: Decimal = Decimal(0)
    box7_net_stcg: Decimal = Decimal(0)
    box8a_net_ltcg: Decimal = Decimal(0)
    box9_section_1231_gain: Decimal = Decimal(0)
    box10_other_income: Decimal = Decimal(0)

    # Deductions
    box11_section_179: Decimal = Decimal(0)
    box12_other_deductions: dict[str, Decimal] = Field(default_factory=dict)

    # Credits (code → amount)
    box13_credits: dict[str, Decimal] = Field(default_factory=dict)

    # AMT
    box15_amt_items: dict[str, Decimal] = Field(default_factory=dict)

    # Items affecting shareholder basis
    box16_basis_items: dict[str, Decimal] = Field(default_factory=dict)

    # Other info — QBI, UBIA, etc. (code → value)
    box17_other_info: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 1099-INT
# ---------------------------------------------------------------------------


class F1099_INT(BaseModel):
    """Form 1099-INT — Interest Income."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    # Set to True if this account is an IRA/401k/HSA — income is not taxable
    held_in_ira: bool = False

    payer: EntityInfo
    box1_interest_income: Decimal = Decimal(0)
    box2_early_withdrawal_penalty: Decimal = Decimal(0)
    box3_us_savings_bond_interest: Decimal = Decimal(0)
    box4_federal_withheld: Decimal = Decimal(0)
    box8_tax_exempt_interest: Decimal = Decimal(0)
    box10_market_discount: Decimal = Decimal(0)
    box11_bond_premium: Decimal = Decimal(0)
    box13_bond_premium_on_tax_exempt: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# 1099-DIV
# ---------------------------------------------------------------------------


class F1099_DIV(BaseModel):
    """Form 1099-DIV — Dividends and Distributions."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    # Set to True if this account is an IRA/401k/HSA — income is not taxable
    held_in_ira: bool = False

    payer: EntityInfo
    box1a_total_ordinary_dividends: Decimal = Decimal(0)
    box1b_qualified_dividends: Decimal = Decimal(0)
    box2a_total_capital_gain_dist: Decimal = Decimal(0)
    box2b_unrecap_sec1250_gain: Decimal = Decimal(0)
    box2c_section_1202_gain: Decimal = Decimal(0)
    box2d_collectibles_gain: Decimal = Decimal(0)
    box3_nondividend_distributions: Decimal = Decimal(0)
    box4_federal_withheld: Decimal = Decimal(0)
    box5_section_199a_dividends: Decimal = Decimal(0)
    box7_foreign_tax_paid: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# 1099-B
# ---------------------------------------------------------------------------


class TermType(StrEnum):
    SHORT = "short"
    LONG = "long"
    UNKNOWN = "unknown"


class CoverageType(StrEnum):
    COVERED = "covered"
    UNCOVERED = "uncovered"


class BrokerageTransaction(BaseModel):
    description: str
    proceeds: Decimal
    cost_basis: Decimal | None = None
    term: TermType = TermType.UNKNOWN
    coverage: CoverageType = CoverageType.COVERED
    wash_sale_disallowed: Decimal = Decimal(0)
    federal_withheld: Decimal = Decimal(0)


class F1099_B(BaseModel):
    """Form 1099-B — Proceeds from Broker and Barter Exchange Transactions."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    # Set to True if this account is an IRA/401k — gains are not taxable
    held_in_ira: bool = False

    payer: EntityInfo
    transactions: list[BrokerageTransaction] = Field(default_factory=list)

    # Aggregated totals (broker may report these directly)
    aggregate_proceeds: Decimal | None = None
    aggregate_cost_basis: Decimal | None = None
    aggregate_federal_withheld: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# 1099-R
# ---------------------------------------------------------------------------


class F1099_R(BaseModel):
    """Form 1099-R — Distributions from Pensions, Annuities, Retirement Plans, etc."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    payer: EntityInfo
    box1_gross_distribution: Decimal = Decimal(0)
    box2a_taxable_amount: Decimal = Decimal(0)
    box2b_taxable_amount_not_determined: bool = False
    box4_federal_withheld: Decimal = Decimal(0)
    box7_distribution_code: str = ""
    box9b_total_employee_contributions: Decimal | None = None
    box14_state_withheld: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# SSA-1099
# ---------------------------------------------------------------------------


class SSA_1099(BaseModel):
    """SSA-1099 — Social Security Benefit Statement."""

    source_file: Path | None = None
    confidence: ParseConfidence = Field(default_factory=ParseConfidence)

    box3_benefits_paid: Decimal = Decimal(0)
    box4_benefits_repaid: Decimal = Decimal(0)
    box6_voluntary_federal_withheld: Decimal = Decimal(0)

    @property
    def net_benefits(self) -> Decimal:
        return self.box3_benefits_paid - self.box4_benefits_repaid


# ---------------------------------------------------------------------------
# Union type for any document
# ---------------------------------------------------------------------------

AnyDocument = Annotated[
    Union[W2, K1_1065, K1_1120S, F1099_INT, F1099_DIV, F1099_B, F1099_R, SSA_1099],
    Field(discriminator=None),
]
