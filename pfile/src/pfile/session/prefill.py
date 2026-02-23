"""
Pre-fill a FilingSession with carry-forward items from a prior-year return.

Call this after ingesting the prior-year PDF, before the user starts uploading
current-year documents.  It sets:
  - session.estimated_tax_paid  (prior year line 26)
  - session.capital_loss_carryover  (Schedule D carryover)
  - session.ny_itemized_deduction  (if prior year used IT-196)
  - session.ny_credits  (prior year NY credits, offered as starting point)

The user can review and adjust each value via the CLI interview before computing.
"""

from __future__ import annotations

from pfile.models.prior_year import PriorYearReturn
from pfile.models.session import FilingSession


def prefill_from_prior_year(
    session: FilingSession,
    prior: PriorYearReturn,
    *,
    apply_estimated_tax: bool = True,
    apply_capital_loss: bool = True,
    apply_ny_itemized: bool = True,
    apply_ny_credits: bool = True,
) -> dict[str, str]:
    """
    Copy carry-forward items from a prior-year return into the session.

    Returns a dict of {field: description} for all values that were set,
    so the CLI can display a confirmation summary to the user.
    """
    applied: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Federal: line 25c other withholding (W-2G, backup withholding, etc.)
    # This is NOT carry-forward — we surface it so the user can confirm
    # whether the same sources exist in the current year.
    # ------------------------------------------------------------------
    if apply_estimated_tax:
        other_wh = prior.form_1040.line25c_other_withheld
        if other_wh > 0:
            session.other_withholding = other_wh
            applied["other_withholding"] = (
                f"${other_wh:,.2f} from prior-year line 25c (other forms withholding); "
                "verify same sources exist this year"
            )

    # ------------------------------------------------------------------
    # Federal: estimated tax payments (prior-year line 26)
    # ------------------------------------------------------------------
    if apply_estimated_tax:
        est = prior.form_1040.line26_estimated_payments
        if est > 0:
            session.estimated_tax_paid = est
            applied["estimated_tax_paid"] = f"${est:,.2f} from prior-year line 26"

    # ------------------------------------------------------------------
    # Federal: capital loss carryover from Schedule D
    # ------------------------------------------------------------------
    if apply_capital_loss:
        carryover = prior.capital_loss_carryover
        if carryover < 0:
            session.capital_loss_carryover = carryover
            applied["capital_loss_carryover"] = f"${abs(carryover):,.2f} capital loss available"

    # ------------------------------------------------------------------
    # NY: itemized deduction (IT-196)
    # Only apply if prior year used itemized AND itemized > NY standard
    # (i.e. it was genuinely beneficial — don't default to itemized if
    # the prior year would have been the same as standard)
    # ------------------------------------------------------------------
    if apply_ny_itemized and prior.it201 and prior.it201.itemized:
        ny_itemized = prior.it201.ny_deduction
        if ny_itemized > 0:
            session.ny_itemized_deduction = ny_itemized
            applied["ny_itemized_deduction"] = (
                f"${ny_itemized:,.2f} — prior year used IT-196 itemized deduction; "
                "review IT-196 items for current year before accepting"
            )

    # ------------------------------------------------------------------
    # NY: credits from prior year (offered as starting point — user should
    # confirm each credit is still applicable for the current year)
    # ------------------------------------------------------------------
    if apply_ny_credits and prior.it201:
        ny_credits = prior.it201.ny_credits
        if ny_credits > 0:
            # We can't decompose the lump sum from the extracted IT-201,
            # so we store it under a generic key. Phase 2 will parse
            # individual credit schedules.
            session.ny_credits["prior_year_credits"] = ny_credits
            applied["ny_credits"] = (
                f"${ny_credits:,.2f} — set from prior-year IT-201 line 46 total; "
                "verify each credit (solar IT-255, Empire State CTC, etc.) "
                "applies to the current year"
            )

    session.touch()
    return applied
