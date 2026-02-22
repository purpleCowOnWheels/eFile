"""
Side-by-side comparison of a computed return vs. a prior-year filed return.

Produces a Rich table showing each key line item, the prior-year actual,
our computed value, and the difference. Differences are flagged by severity.
"""

from __future__ import annotations

from decimal import Decimal

from rich.console import Console
from rich.table import Table
from rich.text import Text

from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn
from pfile.models.prior_year import PriorYearReturn


def _fmt(d: Decimal) -> str:
    return f"${d:,.2f}" if d >= 0 else f"(${abs(d):,.2f})"


def _diff_cell(prior: Decimal, computed: Decimal) -> Text:
    diff = computed - prior
    pct = (abs(diff) / prior * 100) if prior != 0 else Decimal(0)
    s = _fmt(diff)
    if abs(diff) < Decimal("1"):
        return Text(s, style="dim")
    if abs(diff) < Decimal("100") or pct < 1:
        return Text(s, style="yellow")
    return Text(s, style="bold red")


_ROWS: list[tuple[str, str, str]] = [
    # (label, prior_attr, computed_attr)
    ("1a  W-2 wages",           "line1a_wages",              "line1a_w2_wages"),
    ("2b  Taxable interest",     "line2b_taxable_interest",   "line2b_taxable_interest"),
    ("3a  Qualified dividends",  "line3a_qualified_dividends","line3a_qualified_dividends"),
    ("3b  Ordinary dividends",   "line3b_ordinary_dividends", "line3b_ordinary_dividends"),
    ("7   Capital gain/(loss)",  "line7_capital_gain_loss",   "line7_capital_gain_loss"),
    ("8   Other income (K-1/SE)","line8_other_income",        "line8_other_income"),
    ("9   Total income",         "line9_total_income",        "line9_total_income"),
    ("11  AGI",                  "line11_agi",                "line11_agi"),
    ("12  Deduction",            "line12_deduction",          "line12_standard_or_itemized"),
    ("13  QBI deduction",        "line13_qbi_deduction",      "line13_qbi_deduction"),
    ("15  Taxable income",       "line15_taxable_income",     "line15_taxable_income"),
    ("16  Income tax",           "line16_tax",                "line16_tax"),
    ("24  Total tax",            "line24_total_tax",          "line24_total_tax"),
    ("25a W-2 withheld",         "line25a_w2_withheld",       "line25a_w2_withheld"),
    ("25b 1099 withheld",        "line25b_1099_withheld",     "line25b_1099_withheld"),
    ("25c Other withholding",    "line25c_other_withheld",    "line25c_other_withheld"),
    ("26  Est. tax payments",    "line26_estimated_payments", "line26_estimated_payments"),
    ("33  Total payments",       "line33_total_payments",     "line33_total_payments"),
    ("37  Balance due",          "line37_balance_due",        "line37_amount_owed"),
    ("35a Refund",               "line35a_refund",            "line35a_refund"),
]


def compare_federal(
    prior: PriorYearReturn,
    computed: ComputedFederalReturn,
    console: Console | None = None,
) -> Table:
    """Build a Rich comparison table for the federal return."""
    if console is None:
        console = Console()

    t = Table(
        title=f"Federal 1040 — Prior Year {prior.tax_year} vs. Computed",
        show_header=True,
        header_style="bold",
    )
    t.add_column("Line", style="dim", min_width=26)
    t.add_column(f"Actual {prior.tax_year}", justify="right", min_width=14)
    t.add_column("Computed", justify="right", min_width=14)
    t.add_column("Diff", justify="right", min_width=12)
    t.add_column("Note", min_width=30)

    pf = prior.form_1040
    cf = computed.form_1040

    notes_map = {
        "12  Deduction": "Standard only; prior year may be itemized",
        "13  QBI deduction": "Phase 1: non-SSTB assumed; UBIA not included",
        "7   Capital gain/(loss)": "Includes carryover if set on session",
        "25c Other withholding": "Set session.other_withholding if applicable",
        "26  Est. tax payments": "Set session.estimated_tax_paid if applicable",
    }

    for label, prior_attr, computed_attr in _ROWS:
        prior_val = getattr(pf, prior_attr, Decimal(0))
        computed_val = (
            getattr(cf, computed_attr, Decimal(0))
            if computed_attr else Decimal(0)
        )
        note = notes_map.get(label, "")
        t.add_row(
            label,
            _fmt(prior_val),
            _fmt(computed_val) if computed_attr else Text("N/A", style="dim"),
            _diff_cell(prior_val, computed_val) if computed_attr else Text("—", style="dim"),
            note,
        )

    return t


_NY_ROWS: list[tuple[str, str, str]] = [
    ("Federal AGI",             "federal_agi",         "federal_agi"),
    ("NY additions",            "ny_additions",         "ny_additions"),
    ("NY subtractions",         "ny_subtractions",      "ny_subtractions"),
    ("NY AGI",                  "ny_agi",               "ny_agi"),
    ("NY deduction",            "ny_deduction",         "ny_deduction_used"),
    ("NY taxable income",       "ny_taxable_income",    "ny_taxable_income"),
    ("NY state tax",            "ny_state_tax",         "ny_tax"),
    ("NY credits",              "ny_credits",           "ny_credits"),
    ("Total NY tax",            "total_ny_tax",         "total_ny_tax"),
    ("NY withheld",             "ny_withheld",          "ny_withheld"),
    ("Empire State CTC (L63)",  "empire_state_ctc",     "empire_state_ctc"),
    ("NY balance due",          "ny_balance_due",       "ny_amount_owed"),
    ("NY refund",               "ny_refund",            "ny_refund"),
]


def compare_ny(
    prior: PriorYearReturn,
    computed: ComputedNYReturn,
    console: Console | None = None,
) -> Table | None:
    """Build a Rich comparison table for the NY IT-201 return."""
    if prior.it201 is None:
        return None

    t = Table(
        title=f"NY IT-201 — Prior Year {prior.tax_year} vs. Computed",
        show_header=True,
        header_style="bold",
    )
    t.add_column("Line", style="dim", min_width=22)
    t.add_column(f"Actual {prior.tax_year}", justify="right", min_width=14)
    t.add_column("Computed", justify="right", min_width=14)
    t.add_column("Diff", justify="right", min_width=12)
    t.add_column("Note", min_width=30)

    py = prior.it201
    cy = computed.it201

    notes_map = {
        "NY credits": (
            "session.ny_credits: solar_it255, ptet_credit, college_tuition … "
            "(Empire State CTC is auto-computed; do NOT put it here)"
        ),
        "NY deduction": "Itemized (IT-196) — set session.ny_itemized_deduction" if py.itemized else "",
        "Empire State CTC (L63)": (
            "Auto-computed via IT-213 using pre-2017 CTC rules. "
            "$0 when FAGI > $110K (MFJ) and pre-TCJA CTC phases out."
        ),
    }

    for label, prior_attr, computed_attr in _NY_ROWS:
        prior_val = getattr(py, prior_attr, Decimal(0))
        computed_val = (
            getattr(cy, computed_attr, Decimal(0))
            if computed_attr else Decimal(0)
        )
        note = notes_map.get(label, "")
        t.add_row(
            label,
            _fmt(prior_val),
            _fmt(computed_val) if computed_attr else Text("N/A", style="dim"),
            _diff_cell(prior_val, computed_val) if computed_attr else Text("—", style="dim"),
            note,
        )

    return t


def print_comparison(
    prior: PriorYearReturn,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None = None,
    console: Console | None = None,
) -> None:
    """Print the full side-by-side comparison to the console."""
    if console is None:
        console = Console()

    console.print()
    console.print(compare_federal(prior, federal, console))

    if ny and prior.had_ny:
        ny_table = compare_ny(prior, ny, console)
        if ny_table:
            console.print()
            console.print(ny_table)

    if prior.notes:
        console.print()
        console.print("[bold yellow]Parser notes from prior-year return:[/bold yellow]")
        for note in prior.notes:
            console.print(f"  • {note}")

    console.print()
    console.print("[dim]Legend: red = large diff, yellow = small diff, dim = <$1[/dim]")
