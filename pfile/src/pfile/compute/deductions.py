"""Standard and itemized deduction computations."""

from __future__ import annotations

from decimal import Decimal

from pfile.compute._utils import load_federal as _load
from pfile.compute._utils import status_key as _status_key
from pfile.models.filer import FilingStatus


def standard_deduction(
    status: FilingStatus,
    year: int = 2025,
    primary_age_65_or_blind: int = 0,
    spouse_age_65_or_blind: int = 0,
) -> Decimal:
    """
    Return the standard deduction for the given filing status and year.

    The additional deduction for age 65+ or blindness is applied per
    qualifying condition per person (primary and spouse for MFJ).

    Source: IRC §63(c); Rev. Proc. 2024-40.
    """
    data = _load(year)["standard_deduction"]
    key = _status_key(status)
    base = Decimal(str(data[key]))

    additional = Decimal(0)
    if status == FilingStatus.MFJ:
        per = Decimal(str(data["additional_mfj_per_spouse"]))
        additional = per * (primary_age_65_or_blind + spouse_age_65_or_blind)
    else:
        per = Decimal(str(data["additional_single"]))
        additional = per * primary_age_65_or_blind

    return base + additional
