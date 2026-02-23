"""Computed tax form models — outputs of the tax computation engine."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, computed_field


# ---------------------------------------------------------------------------
# Federal schedules
# ---------------------------------------------------------------------------


class ScheduleB(BaseModel):
    """Schedule B — Interest and Ordinary Dividends."""

    # Part I — Interest
    interest_entries: list[tuple[str, Decimal]] = Field(default_factory=list)  # (payer, amount)
    total_taxable_interest: Decimal = Decimal(0)

    # Part II — Dividends
    dividend_entries: list[tuple[str, Decimal]] = Field(default_factory=list)
    total_ordinary_dividends: Decimal = Decimal(0)

    # Part III — Foreign accounts / trusts (checkboxes only for Phase 1)
    foreign_account: bool = False
    foreign_trust: bool = False

    required: bool = False  # True if total interest > $1,500 or total dividends > $1,500


class ScheduleEEntry(BaseModel):
    """A single pass-through entity row on Schedule E Part II."""

    entity_name: str
    ein: str | None = None
    ordinary_income: Decimal = Decimal(0)
    ordinary_loss: Decimal = Decimal(0)
    section_179: Decimal = Decimal(0)
    net_income: Decimal = Decimal(0)


class ScheduleE(BaseModel):
    """Schedule E — Supplemental Income and Loss (K-1 pass-through, Part II only for Phase 1)."""

    entries: list[ScheduleEEntry] = Field(default_factory=list)
    total_income: Decimal = Decimal(0)
    total_loss: Decimal = Decimal(0)

    @computed_field
    @property
    def net(self) -> Decimal:
        return self.total_income - self.total_loss


class CapitalTransaction(BaseModel):
    description: str
    proceeds: Decimal
    cost_basis: Decimal
    gain_loss: Decimal
    term: str  # "short" | "long"


class ScheduleD(BaseModel):
    """Schedule D — Capital Gains and Losses."""

    short_term_transactions: list[CapitalTransaction] = Field(default_factory=list)
    long_term_transactions: list[CapitalTransaction] = Field(default_factory=list)

    net_short_term: Decimal = Decimal(0)
    net_long_term: Decimal = Decimal(0)

    @computed_field
    @property
    def net_capital_gain_loss(self) -> Decimal:
        return self.net_short_term + self.net_long_term


class ScheduleSE(BaseModel):
    """Schedule SE — Self-Employment Tax."""

    net_se_income: Decimal = Decimal(0)
    se_tax: Decimal = Decimal(0)
    deductible_se_tax: Decimal = Decimal(0)  # 50% of SE tax, deducted on 1040


# ---------------------------------------------------------------------------
# Form 1040
# ---------------------------------------------------------------------------


class Form1040(BaseModel):
    """Form 1040 — U.S. Individual Income Tax Return (key lines only)."""

    # Income
    line1a_w2_wages: Decimal = Decimal(0)
    line2b_taxable_interest: Decimal = Decimal(0)
    line3b_ordinary_dividends: Decimal = Decimal(0)
    line3a_qualified_dividends: Decimal = Decimal(0)
    line4b_ira_distributions: Decimal = Decimal(0)
    line5b_pensions_annuities: Decimal = Decimal(0)
    line5a_ss_benefits: Decimal = Decimal(0)
    line5b_taxable_ss: Decimal = Decimal(0)
    line7_capital_gain_loss: Decimal = Decimal(0)
    line8_other_income: Decimal = Decimal(0)       # from Schedule 1

    line9_total_income: Decimal = Decimal(0)

    # Adjustments to income
    line10_adjustments: Decimal = Decimal(0)       # from Schedule 1 Part II
    line11_agi: Decimal = Decimal(0)

    # Deductions & tax
    line12_standard_or_itemized: Decimal = Decimal(0)
    line13_qbi_deduction: Decimal = Decimal(0)
    line15_taxable_income: Decimal = Decimal(0)
    line16_tax: Decimal = Decimal(0)
    line17_amt: Decimal = Decimal(0)
    line24_total_tax: Decimal = Decimal(0)

    # Credits
    line19_ctc: Decimal = Decimal(0)
    line20_other_credits: Decimal = Decimal(0)

    # Payments
    line25a_w2_withheld: Decimal = Decimal(0)
    line25b_1099_withheld: Decimal = Decimal(0)
    line25c_other_withheld: Decimal = Decimal(0)
    line26_estimated_payments: Decimal = Decimal(0)
    line27_eitc: Decimal = Decimal(0)
    line33_total_payments: Decimal = Decimal(0)

    # Result
    line37_amount_owed: Decimal = Decimal(0)
    line35a_refund: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# NY State forms
# ---------------------------------------------------------------------------


class IT2Entry(BaseModel):
    """A single W-2 row on NY Form IT-2."""

    employer_name: str
    employer_ein: str | None = None
    ny_state_wages: Decimal = Decimal(0)
    ny_state_withheld: Decimal = Decimal(0)
    nyc_local_wages: Decimal = Decimal(0)
    nyc_local_withheld: Decimal = Decimal(0)
    yonkers_wages: Decimal = Decimal(0)
    yonkers_withheld: Decimal = Decimal(0)


class IT2(BaseModel):
    """NY Form IT-2 — Summary of W-2 Statements."""

    entries: list[IT2Entry] = Field(default_factory=list)
    total_ny_wages: Decimal = Decimal(0)
    total_ny_withheld: Decimal = Decimal(0)
    total_nyc_withheld: Decimal = Decimal(0)
    total_yonkers_withheld: Decimal = Decimal(0)


class IT201(BaseModel):
    """NY Form IT-201 — Resident Income Tax Return (key lines only)."""

    # Federal amounts carried over
    federal_agi: Decimal = Decimal(0)

    # NY additions / subtractions
    ny_additions: Decimal = Decimal(0)
    ny_subtractions: Decimal = Decimal(0)
    ny_agi: Decimal = Decimal(0)

    # NY deduction
    ny_standard_deduction: Decimal = Decimal(0)
    ny_itemized_deduction: Decimal = Decimal(0)
    ny_deduction_used: Decimal = Decimal(0)
    ny_dependent_exemptions: Decimal = Decimal(0)   # $1,000 × number of dependents

    ny_taxable_income: Decimal = Decimal(0)

    # Tax
    ny_tax: Decimal = Decimal(0)
    nyc_tax: Decimal = Decimal(0)
    yonkers_surcharge: Decimal = Decimal(0)
    ny_credits: Decimal = Decimal(0)         # total credits applied (IT-255, Empire State CTC, etc.)
    total_ny_tax: Decimal = Decimal(0)       # after credits

    # Refundable credits (added to payments, not applied against tax)
    empire_state_ctc: Decimal = Decimal(0)   # IT-213, line 10 — refundable child credit

    # Withholding & credits
    ny_withheld: Decimal = Decimal(0)
    nyc_withheld: Decimal = Decimal(0)
    yonkers_withheld: Decimal = Decimal(0)
    total_ny_payments: Decimal = Decimal(0)  # withholding + refundable credits

    # Result
    ny_amount_owed: Decimal = Decimal(0)
    ny_refund: Decimal = Decimal(0)


# ---------------------------------------------------------------------------
# Top-level computed return
# ---------------------------------------------------------------------------


class ComputedFederalReturn(BaseModel):
    """Full federal tax computation result."""

    form_1040: Form1040
    schedule_b: ScheduleB | None = None
    schedule_d: ScheduleD | None = None
    schedule_e: ScheduleE | None = None
    schedule_se: ScheduleSE | None = None

    agi: Decimal = Decimal(0)
    taxable_income: Decimal = Decimal(0)
    total_tax: Decimal = Decimal(0)
    total_payments: Decimal = Decimal(0)
    balance_due: Decimal = Decimal(0)
    refund: Decimal = Decimal(0)

    @computed_field
    @property
    def has_balance_due(self) -> bool:
        return self.balance_due > 0


class ComputedNYReturn(BaseModel):
    """Full NY state tax computation result."""

    it201: IT201
    it2: IT2

    ny_agi: Decimal = Decimal(0)
    ny_taxable_income: Decimal = Decimal(0)
    total_ny_tax: Decimal = Decimal(0)
    total_ny_payments: Decimal = Decimal(0)
    balance_due: Decimal = Decimal(0)
    refund: Decimal = Decimal(0)

    @computed_field
    @property
    def has_balance_due(self) -> bool:
        return self.balance_due > 0
