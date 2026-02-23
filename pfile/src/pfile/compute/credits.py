"""Federal tax credit computations."""

from __future__ import annotations

import math
from decimal import Decimal

from pfile.compute._utils import load_federal as _load
from pfile.models.filer import DependentProfile, FilingStatus


def child_tax_credit(
    dependents: list[DependentProfile],
    agi: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute the Child Tax Credit (CTC).

    $2,000 per qualifying child under 17, phased out at $50 per $1,000
    of AGI over the threshold.

    Source: IRC §24; Rev. Proc. 2024-40.
    """
    qualifying = [d for d in dependents if d.child_tax_credit_eligible]
    if not qualifying:
        return Decimal(0)

    data = _load(year)["child_tax_credit"]
    per_child = Decimal(str(data["per_child"]))
    total = per_child * len(qualifying)

    threshold_map = {
        FilingStatus.SINGLE: data["phaseout_single_hoh"],
        FilingStatus.MFJ:    data["phaseout_mfj_qss"],
        FilingStatus.MFS:    data["phaseout_mfs"],
        FilingStatus.HOH:    data["phaseout_single_hoh"],
        FilingStatus.QSS:    data["phaseout_mfj_qss"],
    }
    threshold = Decimal(str(threshold_map[status]))
    phaseout_rate = Decimal(str(data["phaseout_rate"]))

    if agi > threshold:
        # Reduce by $50 per $1,000 (or fraction thereof) over threshold
        excess_thousands = Decimal(str(math.ceil(float((agi - threshold) / 1000))))
        reduction = excess_thousands * phaseout_rate
        total = max(Decimal(0), total - reduction)

    return total


def empire_state_child_credit(
    dependents: list[DependentProfile],
    fagi: Decimal,
    status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Compute the NY Empire State Child Credit (Form IT-213).

    This is a REFUNDABLE NY credit equal to the GREATER of:
      (A) 33% of the federal child tax credit computed under pre-TCJA
          (pre-2017) rules: $1,000/child, phase-out starting at $55K/$75K/$110K
          (MFS/single+HOH/MFJ), with 5% reduction per $1,000 over threshold.
      (B) $100 per qualifying child — ONLY if FAGI ≤ the phase-out threshold
          (i.e., Form IT-213 line 3 = Yes).

    If FAGI exceeds the phase-out threshold (line 3 = No), the $100/child
    floor is skipped and the credit is solely 33% of the pre-TCJA CTC.
    For high-income filers where the pre-TCJA CTC phases out entirely, the
    credit is $0.

    Source: NY Tax Law §606(c-1); NY IT-213-I 2024 instructions.
    """
    qualifying = [d for d in dependents if d.child_tax_credit_eligible]
    if not qualifying:
        return Decimal(0)

    # Load pre-TCJA parameters from federal YAML
    data = _load(year)["empire_state_child_credit"]
    per_child = Decimal(str(data["pre_tcja_per_child"]))
    phaseout_factor = Decimal(str(data["phaseout_factor"]))
    ny_rate = Decimal(str(data["ny_credit_rate"]))
    per_child_floor = Decimal(str(data["per_child_floor"]))

    threshold_map = {
        FilingStatus.SINGLE: data["phaseout_single_hoh"],
        FilingStatus.MFJ:    data["phaseout_mfj_qss"],
        FilingStatus.MFS:    data["phaseout_mfs"],
        FilingStatus.HOH:    data["phaseout_single_hoh"],
        FilingStatus.QSS:    data["phaseout_mfj_qss"],
    }
    threshold = Decimal(str(threshold_map[status]))
    num_children = len(qualifying)

    # Pre-TCJA CTC with phase-out
    pre_tcja_total = per_child * num_children
    income_below_threshold = fagi <= threshold

    if fagi > threshold:
        excess = fagi - threshold
        excess_rounded = Decimal(str(math.ceil(float(excess / 1000)))) * 1000
        reduction = excess_rounded * phaseout_factor
        pre_tcja_total = max(Decimal(0), pre_tcja_total - reduction)

    # Form IT-213 line 8: 33% of pre-TCJA CTC
    credit_33pct = (pre_tcja_total * ny_rate).quantize(Decimal("1"))

    # Form IT-213 line 9: $100/child floor — only if line 3 = Yes (income ≤ threshold)
    if income_below_threshold:
        credit_floor = per_child_floor * num_children
        return max(credit_33pct, credit_floor)

    return credit_33pct


def dependent_care_credit(
    eligible_expenses: Decimal,
    num_qualifying_children: int,
    agi: Decimal,
    year: int = 2025,
) -> Decimal:
    """
    Compute the Child and Dependent Care Credit.

    Credit rate is 35% for AGI ≤ $15,000, reduced by 1% for each $2,000
    (or fraction) of AGI over $15,000, minimum 20%.

    Source: IRC §21; IRS Pub. 503.
    """
    if num_qualifying_children == 0 or eligible_expenses == 0:
        return Decimal(0)

    data = _load(year)["dependent_care"]
    max_exp = Decimal(str(
        data["max_expenses_1_child"] if num_qualifying_children == 1
        else data["max_expenses_2_plus"]
    ))
    capped = min(eligible_expenses, max_exp)

    agi_threshold = Decimal(str(data["phaseout_start_agi"]))
    max_rate = Decimal(str(data["max_credit_rate"]))
    min_rate = Decimal(str(data["min_credit_rate"]))

    if agi <= agi_threshold:
        rate = max_rate
    else:
        steps = Decimal(str(math.ceil(float((agi - agi_threshold) / 2000))))
        rate = max(min_rate, max_rate - Decimal("0.01") * steps)

    return (capped * rate).quantize(Decimal("0.01"))
