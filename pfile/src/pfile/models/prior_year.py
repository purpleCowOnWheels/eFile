"""Prior-year tax return data model.

Stores key line items extracted from a filed return (e.g. TurboTax PDF).
Used for:
  - Carry-forward items (capital loss, NOL, estimated tax applied)
  - Side-by-side comparison against current-year computed values
  - Pre-populating the interview (filer profile, dependents)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field


class PriorYearForm1040(BaseModel):
    """Key line items from Form 1040."""

    # Income
    line1a_wages: Decimal = Decimal(0)
    line2b_taxable_interest: Decimal = Decimal(0)
    line3a_qualified_dividends: Decimal = Decimal(0)
    line3b_ordinary_dividends: Decimal = Decimal(0)
    line4b_ira_distributions: Decimal = Decimal(0)
    line5b_pensions_annuities: Decimal = Decimal(0)
    line6b_taxable_ss: Decimal = Decimal(0)
    line7_capital_gain_loss: Decimal = Decimal(0)
    line8_other_income: Decimal = Decimal(0)       # Schedule 1 line 10
    line9_total_income: Decimal = Decimal(0)
    line10_adjustments: Decimal = Decimal(0)       # Schedule 1 line 26
    line11_agi: Decimal = Decimal(0)
    line12_deduction: Decimal = Decimal(0)         # standard or itemized
    line13_qbi_deduction: Decimal = Decimal(0)     # Form 8995/8995-A
    line15_taxable_income: Decimal = Decimal(0)
    line16_tax: Decimal = Decimal(0)
    line17_additional_tax: Decimal = Decimal(0)    # Schedule 2 Part I
    line19_ctc: Decimal = Decimal(0)
    line20_other_credits: Decimal = Decimal(0)     # Schedule 3
    line23_other_taxes: Decimal = Decimal(0)       # Sched 2: SE tax, AMT, NIIT, AMT Medicare
    line24_total_tax: Decimal = Decimal(0)
    line25a_w2_withheld: Decimal = Decimal(0)
    line25b_1099_withheld: Decimal = Decimal(0)
    line25c_other_withheld: Decimal = Decimal(0)
    line26_estimated_payments: Decimal = Decimal(0)  # prior-year estimated payments
    line33_total_payments: Decimal = Decimal(0)
    line37_balance_due: Decimal = Decimal(0)
    line35a_refund: Decimal = Decimal(0)

    # Schedule 2 detail (for carry-forward and comparison)
    additional_medicare_tax: Decimal = Decimal(0)   # Sched 2 line 11
    niit: Decimal = Decimal(0)                      # Sched 2 line 12
    se_tax: Decimal = Decimal(0)                    # Sched 2 line 4
    ev_credit_repayment: Decimal = Decimal(0)       # Sched 2 line 1b

    # Schedule 3 detail
    dependent_care_credit: Decimal = Decimal(0)
    residential_energy_credit: Decimal = Decimal(0)
    clean_vehicle_credit: Decimal = Decimal(0)


class PriorYearScheduleD(BaseModel):
    """Capital loss carryover (most important carry-forward item)."""
    net_short_term: Decimal = Decimal(0)
    net_long_term: Decimal = Decimal(0)
    carryover_to_next_year: Decimal = Decimal(0)   # negative = loss carryover


class PriorYearIT201(BaseModel):
    """Key line items from NY Form IT-201."""

    federal_agi: Decimal = Decimal(0)
    ny_additions: Decimal = Decimal(0)
    ny_subtractions: Decimal = Decimal(0)
    ny_agi: Decimal = Decimal(0)
    ny_deduction: Decimal = Decimal(0)
    ny_dependent_exemptions: Decimal = Decimal(0)
    ny_taxable_income: Decimal = Decimal(0)
    ny_state_tax: Decimal = Decimal(0)
    ny_credits: Decimal = Decimal(0)
    ny_tax_after_credits: Decimal = Decimal(0)
    nyc_tax: Decimal = Decimal(0)
    yonkers_surcharge: Decimal = Decimal(0)
    total_ny_tax: Decimal = Decimal(0)
    empire_state_ctc: Decimal = Decimal(0)          # IT-201 line 63 — refundable child credit
    ny_withheld: Decimal = Decimal(0)
    nyc_withheld: Decimal = Decimal(0)
    ny_balance_due: Decimal = Decimal(0)
    ny_refund: Decimal = Decimal(0)
    itemized: bool = False                          # True if they used IT-196


class PriorYearReturn(BaseModel):
    """Complete prior-year filed return extracted from a PDF."""

    tax_year: int
    source_file: str = ""

    form_1040: PriorYearForm1040 = Field(default_factory=PriorYearForm1040)
    schedule_d: PriorYearScheduleD = Field(default_factory=PriorYearScheduleD)
    it201: PriorYearIT201 | None = None

    # Carry-forward items for next year
    capital_loss_carryover: Decimal = Decimal(0)    # from Sched D — negative number
    estimated_tax_applied: Decimal = Decimal(0)     # applied from prior year refund

    # Raw notes / unmapped items the LLM flagged
    notes: list[str] = Field(default_factory=list)

    @property
    def had_ny(self) -> bool:
        return self.it201 is not None

    def carry_forwards(self) -> dict[str, Decimal]:
        """Return items that carry forward to next year's return."""
        return {
            "capital_loss_carryover": self.capital_loss_carryover,
            "estimated_tax_applied": self.estimated_tax_applied,
        }
