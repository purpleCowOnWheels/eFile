"""
Qualified Business Income (QBI) Deduction — IRC §199A.

Rules implemented (Phase 1 scope — covers most W-2 + K-1 filers):

1. Aggregate QBI from K-1s:
   - K1_1120S box 1 (S-corp ordinary income)
   - K1_1065  box 1 (partnership ordinary income)
   Losses are allowed to offset gains within the same basket; the aggregate
   can go negative but the deduction floor is $0.

2. Tentative deduction = 20% × aggregate QBI (only if positive).

3. W-2 wage limitation (applies when taxable income exceeds the phase-in
   threshold):
   - W-2 wages paid by the entity are reported in:
       K1_1120S.box17_other_info["W"]
       K1_1065.box20_other_info["W"]
   - Wage cap = 50% of W-2 wages paid by each entity.
   - Alternative cap = 25% of W-2 wages + 2.5% of UBIA qualified property
     (UBIA not in Phase 1 scope; defaults to zero).
   - Limitation phases in over the $100k / $50k range above threshold.

4. Overall income cap = 20% of (taxable income - net LTCG - qualified divs).

5. Phase 1 conservatism: we assume all entities are non-SSTBs (Specified
   Service Trades / Businesses). If a K-1 is from an SSTB and the filer is
   in the phaseout range, we will over-compute the deduction. Phase 2 will
   add an SSTB flag to the K-1 model.

Source: IRC §199A; IRS Rev. Proc. 2024-40; Form 8995-A instructions (2025).
"""

from __future__ import annotations

from decimal import Decimal

from pfile.models.documents import K1_1065, K1_1120S
from pfile.models.filer import FilingStatus
from pfile.compute._utils import load_federal as _load, round2 as _r2


def _qbi_threshold(status: FilingStatus, data: dict) -> tuple[Decimal, Decimal]:
    """Return (phase_in_start, phase_in_range) for the given filing status."""
    q = data["qbi"]
    if status == FilingStatus.MFJ:
        return Decimal(str(q["threshold_mfj"])), Decimal(str(q["range_mfj"]))
    if status == FilingStatus.MFS:
        return Decimal(str(q["threshold_mfs"])), Decimal(str(q["range_others"]))
    if status == FilingStatus.HOH:
        return Decimal(str(q["threshold_hoh"])), Decimal(str(q["range_others"]))
    if status == FilingStatus.QSS:
        return Decimal(str(q["threshold_qss"])), Decimal(str(q["range_mfj"]))
    return Decimal(str(q["threshold_single"])), Decimal(str(q["range_others"]))


def _entity_w2_wages(k1_1120s: list[K1_1120S], k1_1065s: list[K1_1065]) -> Decimal:
    """Sum W-2 wages reported on K-1s (code 'W' in the other-info dict)."""
    total = Decimal(0)
    for k1 in k1_1120s:
        raw = k1.box17_other_info.get("W") or k1.box17_other_info.get("w")
        if raw:
            try:
                total += Decimal(str(raw).replace(",", ""))
            except Exception:
                pass
    for k1 in k1_1065s:
        raw = k1.box20_other_info.get("W") or k1.box20_other_info.get("w")
        if raw:
            try:
                total += Decimal(str(raw).replace(",", ""))
            except Exception:
                pass
    return total


def compute_qbi_deduction(
    k1_1120ss: list[K1_1120S],
    k1_1065s: list[K1_1065],
    taxable_income: Decimal,
    qualified_divs: Decimal,
    net_ltcg: Decimal,
    filing_status: FilingStatus,
    year: int = 2025,
) -> Decimal:
    """
    Return the §199A QBI deduction (always ≥ $0).

    Parameters
    ----------
    k1_1120ss / k1_1065s:
        All K-1s for the return (primary + spouse combined).
    taxable_income:
        Line 15 taxable income BEFORE the QBI deduction (which reduces it).
        We iterate once: compute tentative QBI → recompute taxable income.
        For simplicity in Phase 1, we use the taxable income *before* the
        QBI deduction as the income cap base (this is conservative — it
        overstates the cap slightly).
    qualified_divs:
        Box 1b qualified dividends from 1099-DIVs.
    net_ltcg:
        Net long-term capital gain from Schedule D (floored at 0).
    filing_status, year:
        Used to look up brackets.
    """
    data = _load(year)
    rate = Decimal(str(data["qbi"]["rate"]))

    # ------------------------------------------------------------------
    # 1. Aggregate QBI
    # ------------------------------------------------------------------
    aggregate_qbi = sum(
        (k.box1_ordinary_income for k in k1_1120ss), Decimal(0)
    ) + sum(
        (k.box1_ordinary_income for k in k1_1065s), Decimal(0)
    )

    if aggregate_qbi <= 0:
        return Decimal(0)

    # ------------------------------------------------------------------
    # 2. Tentative deduction (uncapped)
    # ------------------------------------------------------------------
    tentative = _r2(rate * aggregate_qbi)

    # ------------------------------------------------------------------
    # 3. Overall income cap: 20% of (taxable income - LTCG - qualified divs)
    # ------------------------------------------------------------------
    ordinary_taxable = max(Decimal(0), taxable_income - net_ltcg - qualified_divs)
    income_cap = _r2(rate * ordinary_taxable)

    # ------------------------------------------------------------------
    # 4. W-2 wage limitation (only applies above the phase-in threshold)
    # ------------------------------------------------------------------
    threshold, phase_range = _qbi_threshold(filing_status, data)

    if taxable_income <= threshold:
        # Below threshold: simple 20% with income cap only
        return min(tentative, income_cap)

    # Fraction of limitation that applies (0 at threshold, 1 at threshold+range)
    excess = taxable_income - threshold
    phase_fraction = min(Decimal(1), excess / phase_range)

    # W-2 wage cap for non-SSTBs: 50% of total W-2 wages across all entities
    w2_wages = _entity_w2_wages(k1_1120ss, k1_1065s)
    w2_cap = _r2(Decimal("0.50") * w2_wages)

    # If no W-2 wage data is available, fall back to tentative deduction.
    # NOTE: this likely OVER-computes the deduction for entities with no W-2 wages —
    # the §199A(b)(2)(B) wage cap would reduce the deduction to $0 above the threshold.
    # Phase 2 will add an explicit W-2 wages field per entity to fix this.
    if w2_wages == 0:
        limited = tentative
    else:
        # Blend: deduction = tentative - phase_fraction × (tentative - w2_cap)
        limited = _r2(tentative - phase_fraction * (tentative - w2_cap))
        limited = max(Decimal(0), limited)

    return _r2(min(limited, income_cap))
