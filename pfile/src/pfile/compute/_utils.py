"""Shared utilities for compute modules."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import yaml

from pfile.models.filer import FilingStatus

_FEDERAL_DATA = Path(__file__).parents[3] / "data" / "brackets" / "federal"
_NY_DATA = Path(__file__).parents[3] / "data" / "brackets" / "ny"


@lru_cache(maxsize=8)
def load_federal(year: int) -> dict:
    """Load (and cache) the federal bracket YAML for a given tax year."""
    with (_FEDERAL_DATA / f"{year}.yaml").open() as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=8)
def load_ny(year: int) -> dict:
    """Load (and cache) the NY bracket YAML for a given tax year."""
    with (_NY_DATA / f"{year}.yaml").open() as f:
        return yaml.safe_load(f)


def status_key(status: FilingStatus) -> str:
    """Map FilingStatus to the YAML key used in bracket files."""
    return {
        FilingStatus.SINGLE: "single",
        FilingStatus.MFJ:    "mfj",
        FilingStatus.MFS:    "mfs",
        FilingStatus.HOH:    "hoh",
        FilingStatus.QSS:    "qss",
    }[status]


def round2(d: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP (IRS standard)."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
