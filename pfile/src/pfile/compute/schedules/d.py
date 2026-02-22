"""Schedule D — Capital Gains and Losses."""

from __future__ import annotations

from decimal import Decimal

from pfile.models.documents import F1099_B, K1_1065, K1_1120S, TermType
from pfile.models.forms import CapitalTransaction, ScheduleD


def compute_schedule_d(
    f1099_bs: list[F1099_B],
    k1_1065s: list[K1_1065] | None = None,
    k1_1120ss: list[K1_1120S] | None = None,
    capital_loss_carryover: Decimal = Decimal(0),
) -> ScheduleD:
    """
    Compute Schedule D from brokerage 1099-Bs, K-1 capital gain/loss items,
    and any prior-year capital loss carryover.

    Capital loss carryover convention: negative value = loss available to use.
    It is added to short-term transactions as a separate line item (per
    Schedule D Part I, line 6).

    Source: Schedule D instructions; IRC §1222; IRC §1211; IRC §1212.
    """
    short_term: list[CapitalTransaction] = []
    long_term: list[CapitalTransaction] = []

    # 1099-B transactions
    for form in f1099_bs:
        for txn in form.transactions:
            gain_loss = txn.proceeds - (txn.cost_basis or Decimal(0)) - txn.wash_sale_disallowed
            ct = CapitalTransaction(
                description=txn.description,
                proceeds=txn.proceeds,
                cost_basis=txn.cost_basis or Decimal(0),
                gain_loss=gain_loss,
                term=txn.term.value,
            )
            if txn.term == TermType.LONG:
                long_term.append(ct)
            else:
                short_term.append(ct)

    # K-1 (1065) capital items
    for k1 in (k1_1065s or []):
        if k1.box7_net_stcg:
            short_term.append(CapitalTransaction(
                description=f"{k1.partnership.name} (K-1 Box 7)",
                proceeds=max(Decimal(0), k1.box7_net_stcg),
                cost_basis=Decimal(0),
                gain_loss=k1.box7_net_stcg,
                term="short",
            ))
        if k1.box6a_net_ltcg:
            long_term.append(CapitalTransaction(
                description=f"{k1.partnership.name} (K-1 Box 6a)",
                proceeds=max(Decimal(0), k1.box6a_net_ltcg),
                cost_basis=Decimal(0),
                gain_loss=k1.box6a_net_ltcg,
                term="long",
            ))

    # K-1 (1120S) capital items
    for k1 in (k1_1120ss or []):
        if k1.box7_net_stcg:
            short_term.append(CapitalTransaction(
                description=f"{k1.corporation.name} (K-1 Box 7)",
                proceeds=max(Decimal(0), k1.box7_net_stcg),
                cost_basis=Decimal(0),
                gain_loss=k1.box7_net_stcg,
                term="short",
            ))
        if k1.box8a_net_ltcg:
            long_term.append(CapitalTransaction(
                description=f"{k1.corporation.name} (K-1 Box 8a)",
                proceeds=max(Decimal(0), k1.box8a_net_ltcg),
                cost_basis=Decimal(0),
                gain_loss=k1.box8a_net_ltcg,
                term="long",
            ))

    # Prior-year capital loss carryover (Schedule D Part I, line 6).
    # Convention: negative value = loss.  We apply it to short-term by default,
    # which is the more conservative treatment (reduces gains first).
    if capital_loss_carryover < 0:
        short_term.append(CapitalTransaction(
            description="Capital loss carryover from prior year",
            proceeds=Decimal(0),
            cost_basis=abs(capital_loss_carryover),
            gain_loss=capital_loss_carryover,   # negative
            term="short",
        ))

    net_short = sum((t.gain_loss for t in short_term), Decimal(0))
    net_long = sum((t.gain_loss for t in long_term), Decimal(0))

    # Store raw (pre-limit) values — the §1211(b) $3,000 loss limit is applied
    # in agi.py when computing 1040 Line 7, not here. Schedule D lines 16/17
    # always show the actual gain or loss before the annual deduction cap.

    return ScheduleD(
        short_term_transactions=short_term,
        long_term_transactions=long_term,
        net_short_term=net_short,
        net_long_term=net_long,
    )
