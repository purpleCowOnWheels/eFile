"""Prompts for session-level overrides: carry-forwards, NY credits, etc."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import questionary
from rich.console import Console

from pfile.models.session import FilingSession

console = Console()


def _ask_decimal(prompt: str, default: Decimal = Decimal(0)) -> Decimal:
    """Ask for a dollar amount; returns Decimal."""
    default_str = str(default) if default != 0 else "0"
    raw = questionary.text(
        prompt,
        default=default_str,
        validate=lambda v: _valid_decimal(v),
    ).ask()
    try:
        return Decimal(raw.strip().replace(",", "").lstrip("$"))
    except InvalidOperation:
        return default


def _valid_decimal(val: str) -> bool | str:
    try:
        Decimal(val.strip().replace(",", "").lstrip("$"))
        return True
    except InvalidOperation:
        return "Enter a dollar amount (e.g. 1500 or 1500.00)"


def ask_federal_overrides(session: FilingSession) -> None:
    """Ask about federal-level carry-forwards and manual entries."""
    console.print("\n[bold]Federal overrides[/bold]")
    console.print("[dim]Press Enter to keep the current value (or 0 to skip).[/dim]")

    session.estimated_tax_paid = _ask_decimal(
        "  Estimated tax payments made during the year (line 26):",
        default=session.estimated_tax_paid,
    )
    session.capital_loss_carryover = _ask_decimal(
        "  Capital loss carryover from prior year (enter as negative, e.g. -3000):",
        default=session.capital_loss_carryover,
    )
    session.other_withholding = _ask_decimal(
        "  Other withholding not on a W-2 or 1099 (line 25c, e.g. gambling):",
        default=session.other_withholding,
    )

    if any(d.child_tax_credit_eligible for d in session.dependents):
        console.print(
            "\n  [dim]Dependent/child care expenses (Form 2441).[/dim]\n"
            "  [dim]Enter the total you paid out-of-pocket to a care provider.[/dim]\n"
            "  [dim]Employer FSA benefits (W-2 box 10) are subtracted automatically.[/dim]"
        )
        session.dependent_care_expenses = _ask_decimal(
            "  Total dependent care expenses paid (0 if none):",
            default=session.dependent_care_expenses,
        )


def ask_ny_overrides(session: FilingSession) -> None:
    """Ask about NY-specific overrides: itemized deduction and credits."""
    console.print("\n[bold]New York State overrides[/bold]")

    itemize = questionary.confirm(
        "  Are you using NY itemized deductions (Form IT-196) instead of the standard?",
        default=session.ny_itemized_deduction is not None,
    ).ask()
    if itemize:
        session.ny_itemized_deduction = _ask_decimal(
            "  NY itemized deduction amount (from IT-196 line 45):",
            default=session.ny_itemized_deduction or Decimal(0),
        )
    else:
        session.ny_itemized_deduction = None

    # NY credits
    console.print(
        "\n  [dim]NY credits (non-refundable, reduce NY tax).[/dim]\n"
        "  [dim]Empire State CTC is computed automatically — do not enter it here.[/dim]"
    )
    _ask_ny_credit(session, "ptet_credit",
                   "  NY Pass-Through Entity Tax credit (Form IT-653):")
    _ask_ny_credit(session, "solar_it255",
                   "  Solar energy system equipment credit (Form IT-255):")
    _ask_ny_credit(session, "college_tuition",
                   "  College tuition credit (Form IT-272):")


def _ask_ny_credit(session: FilingSession, key: str, prompt: str) -> None:
    current = session.ny_credits.get(key, Decimal(0))
    val = _ask_decimal(prompt, default=current)
    if val > 0:
        session.ny_credits[key] = val
    elif key in session.ny_credits:
        del session.ny_credits[key]
