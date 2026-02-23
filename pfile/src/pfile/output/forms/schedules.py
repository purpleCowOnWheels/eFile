"""
Fill official IRS Schedule B, D, and E PDFs using PyMuPDF AcroForm.

All field positions were verified with positional analysis (y-coordinate +
neighboring text label cross-reference).

Phase 2 scope:
  - Schedule B: up to 14 interest payers and 15 dividend payers; Part I/II totals
  - Schedule D: net short-term total (line 7), net long-term total (line 15),
                combined total (line 16 / page 2)
  - Schedule E: K-1 income/loss per entity (up to 3 per page), net total (line 32)
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any

import fitz

from pfile.models.forms import ScheduleB, ScheduleD, ScheduleE
from pfile.models.session import FilingSession
from pfile.output.forms.filler import _apply_fields, _money

# ── Schedule B ────────────────────────────────────────────────────────────────

# Part I interest rows: fields (name_field, amount_field) by row index (0-based)
_SCHED_B_INT_ROWS = [
    ("f1_03[0]", "f1_04[0]"),
    ("f1_05[0]", "f1_06[0]"),
    ("f1_07[0]", "f1_08[0]"),
    ("f1_09[0]", "f1_10[0]"),
    ("f1_11[0]", "f1_12[0]"),
    ("f1_13[0]", "f1_14[0]"),
    ("f1_15[0]", "f1_16[0]"),
    ("f1_17[0]", "f1_18[0]"),
    ("f1_19[0]", "f1_20[0]"),
    ("f1_21[0]", "f1_22[0]"),
    ("f1_23[0]", "f1_24[0]"),
    ("f1_25[0]", "f1_26[0]"),
    ("f1_27[0]", "f1_28[0]"),
    ("f1_29[0]", "f1_30[0]"),
]

# Part II dividend rows
_SCHED_B_DIV_ROWS = [
    ("f1_34[0]", "f1_35[0]"),
    ("f1_36[0]", "f1_37[0]"),
    ("f1_38[0]", "f1_39[0]"),
    ("f1_40[0]", "f1_41[0]"),
    ("f1_42[0]", "f1_43[0]"),
    ("f1_44[0]", "f1_45[0]"),
    ("f1_46[0]", "f1_47[0]"),
    ("f1_48[0]", "f1_49[0]"),
    ("f1_50[0]", "f1_51[0]"),
    ("f1_52[0]", "f1_53[0]"),
    ("f1_54[0]", "f1_55[0]"),
    ("f1_56[0]", "f1_57[0]"),
    ("f1_58[0]", "f1_59[0]"),
    ("f1_60[0]", "f1_61[0]"),
    ("f1_62[0]", "f1_63[0]"),
]


def _build_sched_b_updates(
    session: FilingSession,
    sched_b: ScheduleB,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    primary = session.primary
    if primary:
        updates["f1_01[0]"] = f"{primary.first_name} {primary.last_name}"
        updates["f1_02[0]"] = primary.ssn

    # Part I — Interest
    for i, (payer, amount) in enumerate(sched_b.interest_entries[: len(_SCHED_B_INT_ROWS)]):
        name_f, amt_f = _SCHED_B_INT_ROWS[i]
        updates[name_f] = payer
        updates[amt_f] = _money(amount)
    # Line 4 — total taxable interest
    updates["f1_33[0]"] = _money(sched_b.total_taxable_interest)

    # Part II — Dividends
    for i, (payer, amount) in enumerate(sched_b.dividend_entries[: len(_SCHED_B_DIV_ROWS)]):
        name_f, amt_f = _SCHED_B_DIV_ROWS[i]
        updates[name_f] = payer
        updates[amt_f] = _money(amount)
    # Line 6 — total ordinary dividends
    updates["f1_64[0]"] = _money(sched_b.total_ordinary_dividends)

    return updates


def fill_schedule_b(
    session: FilingSession,
    sched_b: ScheduleB,
    template_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Fill Schedule B with interest and dividend entries."""
    updates = _build_sched_b_updates(session, sched_b)
    doc = fitz.open(str(template_path))
    _apply_fields(doc, updates)
    doc.save(str(output_path))
    doc.close()


# ── Schedule D ────────────────────────────────────────────────────────────────
#
# pFile Phase 2: we do not fill individual 8949 rows (that is Phase 3 work).
# Instead we put aggregate short-term and long-term totals on the summary lines,
# following IRS instructions for filers who attach Form 8949 (checked box A/B/C).
#
# Line 7  = net short-term capital gain or loss (page 1)  → f1_22[0]
# Line 15 = net long-term capital gain or loss (page 1)   → f1_43[0]
# Line 16 = combined net capital gain or loss (page 2)    → f2_1[0]


def _build_sched_d_updates(
    session: FilingSession,
    sched_d: ScheduleD,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    primary = session.primary
    if primary:
        updates["f1_1[0]"] = f"{primary.first_name} {primary.last_name}"
        updates["f1_2[0]"] = primary.ssn

    net_st = sched_d.net_short_term
    net_lt = sched_d.net_long_term
    combined = net_st + net_lt

    # Line 7 — net short-term
    updates["f1_22[0]"] = _money(net_st)
    # Line 15 — net long-term
    updates["f1_43[0]"] = _money(net_lt)
    # Line 16 (page 2) — combined
    updates["f2_1[0]"] = _money(combined)

    return updates


def fill_schedule_d(
    session: FilingSession,
    sched_d: ScheduleD,
    template_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Fill Schedule D with net capital gain/loss summary lines."""
    updates = _build_sched_d_updates(session, sched_d)
    doc = fitz.open(str(template_path))
    _apply_fields(doc, updates)
    doc.save(str(output_path))
    doc.close()


# ── Schedule E ────────────────────────────────────────────────────────────────
#
# pFile Phase 2 scope: fill Part II (Partnerships and S Corps) only.
# Up to 3 entities per page (columns at x≈317, x≈403, x≈490).
# The column-indexed fields for income rows use this layout:
#
#   Row label   Col A (x≈317)   Col B (x≈403)   Col C (x≈490)
#   -------------------------------------------------------
#   23a         f1_77[0]        f1_78[0]        f1_79[0]   ← partnerships/S-corps active income
#   24 (total)  (single field)  f1_82[0]
#   26 (net)    (single field)  f1_84[0]
#
# Verified column offsets:
_SCHED_E_PART2_INCOME_COLS = ("f1_77[0]", "f1_78[0]", "f1_79[0]")  # line 23a
_SCHED_E_PART2_LOSS_COLS = ("f1_80[0]", "f1_81[0]", "f1_82[0]")    # line 23b/e losses


def _build_sched_e_updates(
    session: FilingSession,
    sched_e: ScheduleE,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}

    primary = session.primary
    if primary:
        updates["f1_1[0]"] = f"{primary.first_name} {primary.last_name}"
        updates["f1_2[0]"] = primary.ssn

    net_total = sched_e.net

    # Fill up to 3 entity columns on Part II
    for i, entry in enumerate(sched_e.entries[:3]):
        income = entry.ordinary_income
        if income >= Decimal(0) and i < len(_SCHED_E_PART2_INCOME_COLS):
            updates[_SCHED_E_PART2_INCOME_COLS[i]] = _money(income)
        elif income < Decimal(0) and i < len(_SCHED_E_PART2_LOSS_COLS):
            updates[_SCHED_E_PART2_LOSS_COLS[i]] = _money(abs(income))

    # Line 32 — net income or (loss) to Schedule 1
    updates["f1_84[0]"] = _money(net_total)

    return updates


def fill_schedule_e(
    session: FilingSession,
    sched_e: ScheduleE,
    template_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    """Fill Schedule E Part II with K-1 income/loss summary."""
    updates = _build_sched_e_updates(session, sched_e)
    doc = fitz.open(str(template_path))
    _apply_fields(doc, updates)
    doc.save(str(output_path))
    doc.close()
