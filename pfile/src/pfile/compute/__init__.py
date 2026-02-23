"""Federal + NY state tax computation engine."""

from pfile.compute.agi import compute_agi, compute_gross_income
from pfile.compute.credits import child_tax_credit, dependent_care_credit
from pfile.compute.deductions import standard_deduction
from pfile.compute.engine import compute_federal_return
from pfile.compute.tax import (
    additional_medicare_tax,
    net_investment_income_tax,
    ordinary_income_tax,
    qualified_div_ltcg_tax,
    taxable_social_security,
)

__all__ = [
    "compute_federal_return",
    "compute_agi",
    "compute_gross_income",
    "standard_deduction",
    "child_tax_credit",
    "dependent_care_credit",
    "ordinary_income_tax",
    "qualified_div_ltcg_tax",
    "net_investment_income_tax",
    "additional_medicare_tax",
    "taxable_social_security",
]
