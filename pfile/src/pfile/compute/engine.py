"""
Federal tax computation engine.

Takes a FilingSession and returns a ComputedFederalReturn.
All computation is pure / side-effect free — the session is never mutated.
"""

from __future__ import annotations

from decimal import Decimal

from pfile.models.documents import F1099_B, F1099_DIV, F1099_INT, F1099_R, K1_1065, K1_1120S, SSA_1099, W2
from pfile.models.forms import (
    ComputedFederalReturn,
    Form1040,
    ScheduleB,
    ScheduleD,
    ScheduleE,
    ScheduleSE,
)
from pfile.models.session import DocumentSet, FilingSession
from pfile.compute.agi import compute_agi, compute_gross_income
from pfile.compute.credits import child_tax_credit, dependent_care_credit
from pfile.compute.deductions import standard_deduction
from pfile.compute.qbi import compute_qbi_deduction
from pfile.compute.schedules.b import compute_schedule_b
from pfile.compute.schedules.d import compute_schedule_d
from pfile.compute.schedules.e import compute_schedule_e
from pfile.compute.tax import (
    additional_medicare_tax,
    net_investment_income_tax,
    ordinary_income_tax,
    qualified_div_ltcg_tax,
)
from pfile.compute._utils import round2 as _round2


def _collect(primary: DocumentSet, spouse: DocumentSet | None, doc_type: type) -> list:
    """Collect all documents of a given type from both filers."""
    primary_docs = [d for d in primary.all_documents() if isinstance(d, doc_type)]
    spouse_docs = (
        [d for d in spouse.all_documents() if isinstance(d, doc_type)]
        if spouse else []
    )
    return primary_docs + spouse_docs


def compute_federal_return(session: FilingSession, year: int = 2025) -> ComputedFederalReturn:
    """
    Compute the full federal return for a filing session.

    Phase 1 scope:
      - Wages (W-2)
      - Interest & dividends (Schedule B)
      - K-1 pass-through (Schedule E)
      - Capital gains (Schedule D)
      - IRA/pension distributions (1099-R)
      - Social Security (SSA-1099)
      - Standard deduction only (no itemized yet)
      - Child Tax Credit + Dependent Care Credit
      - NIIT and Additional Medicare Tax
    """
    if not session.primary:
        raise ValueError("Session has no primary taxpayer profile.")

    status = session.filing_status
    spouse_docs = session.spouse_documents if session.is_mfj else None

    all_w2s: list[W2] = _collect(session.primary_documents, spouse_docs, W2)
    all_int: list[F1099_INT] = _collect(session.primary_documents, spouse_docs, F1099_INT)
    all_div: list[F1099_DIV] = _collect(session.primary_documents, spouse_docs, F1099_DIV)
    all_b: list[F1099_B] = _collect(session.primary_documents, spouse_docs, F1099_B)
    all_r: list[F1099_R] = _collect(session.primary_documents, spouse_docs, F1099_R)
    all_ssa: list[SSA_1099] = _collect(session.primary_documents, spouse_docs, SSA_1099)
    all_k1_1065: list[K1_1065] = _collect(session.primary_documents, spouse_docs, K1_1065)
    all_k1_1120s: list[K1_1120S] = _collect(session.primary_documents, spouse_docs, K1_1120S)

    # Exclude documents held in retirement accounts from schedule computations.
    taxable_int = [f for f in all_int if not f.held_in_ira]
    taxable_div = [f for f in all_div if not f.held_in_ira]
    taxable_b   = [f for f in all_b   if not f.held_in_ira]

    sched_b = compute_schedule_b(taxable_int, taxable_div)
    sched_d = compute_schedule_d(
        taxable_b, all_k1_1065, all_k1_1120s,
        capital_loss_carryover=session.capital_loss_carryover,
    )
    sched_e = compute_schedule_e(all_k1_1065, all_k1_1120s)

    # Qualified dividends (needed for preferential tax rate) — taxable accounts only
    qualified_divs = sum((f.box1b_qualified_dividends for f in taxable_div), Decimal(0))

    gross = compute_gross_income(
        w2s=all_w2s,
        schedule_b=sched_b,
        schedule_d=sched_d,
        schedule_e=sched_e,
        f1099_rs=all_r,
        ssa_1099s=all_ssa,
        filing_status=status,
        year=year,
    )

    agi, adjustments = compute_agi(gross)
    agi = _round2(agi)

    std_ded = standard_deduction(status, year)
    deduction = std_ded  # Phase 1: standard deduction only

    # QBI deduction depends on taxable income, but taxable income also depends on QBI.
    # IRS uses pre-QBI taxable income as the base for the wage-limitation, so we compute
    # it first and pass it into compute_qbi_deduction unchanged.
    taxable_income_pre_qbi = max(Decimal(0), agi - deduction)

    net_ltcg = max(Decimal(0), sched_d.net_long_term)

    qbi_deduction = compute_qbi_deduction(
        k1_1120ss=all_k1_1120s,
        k1_1065s=all_k1_1065,
        taxable_income=taxable_income_pre_qbi,
        qualified_divs=qualified_divs,
        net_ltcg=net_ltcg,
        filing_status=status,
        year=year,
    )

    taxable_income = max(Decimal(0), taxable_income_pre_qbi - qbi_deduction)

    # Ordinary income tax less preferential rate on qualified divs + LTCG:
    # compute tax as if everything were ordinary, then replace the pref-income
    # portion with the 0/15/20% rate.
    pref_tax = qualified_div_ltcg_tax(qualified_divs, net_ltcg, taxable_income, status, year)
    ordinary_pref_tax = ordinary_income_tax(
        max(Decimal(0), taxable_income - qualified_divs - net_ltcg),
        status, year,
    )
    income_tax = _round2(ordinary_pref_tax + pref_tax)

    # NIIT: investment income = interest + dividends + capital gains (§1411)
    net_investment_income = (
        sched_b.total_taxable_interest
        + sched_b.total_ordinary_dividends
        + sched_d.net_capital_gain_loss
    )
    niit = net_investment_income_tax(
        max(Decimal(0), net_investment_income), agi, status, year
    )

    # Additional Medicare Tax on wages
    total_wages = sum((w.box1_wages for w in all_w2s), Decimal(0))
    amt_tax = additional_medicare_tax(total_wages, status, year)

    total_tax = _round2(income_tax + niit + amt_tax)

    ctc = child_tax_credit(session.dependents, agi, status, year)

    # Dependent care credit (Form 2441).
    # The filer's actual out-of-pocket expenses are stored in session.dependent_care_expenses.
    # Employer FSA benefits (W-2 box 10) reduce the claimable ceiling but are not the
    # expense themselves — do NOT use box 10 as the expense amount.
    employer_fsa = sum((w.box10_dependent_care for w in all_w2s), Decimal(0))
    raw_dep_care = session.dependent_care_expenses
    n_qualifying_children = len([d for d in session.dependents if d.child_tax_credit_eligible])
    # Net expenses available for credit = actual expenses minus the FSA exclusion already used
    net_dep_care = max(Decimal(0), raw_dep_care - employer_fsa)
    dep_care_credit = dependent_care_credit(net_dep_care, n_qualifying_children, agi, year)

    total_credits = _round2(ctc + dep_care_credit)
    tax_after_credits = max(Decimal(0), total_tax - total_credits)

    w2_withheld = _round2(sum((w.box2_federal_withheld for w in all_w2s), Decimal(0)))
    other_withheld = _round2(
        sum((f.box4_federal_withheld for f in taxable_int), Decimal(0))
        + sum((f.box4_federal_withheld for f in taxable_div), Decimal(0))
        + sum((f.box4_federal_withheld for f in all_r), Decimal(0))
    )
    # Line 25c: manual override for withholding from forms not in our document model
    other_withholding_manual = _round2(session.other_withholding)
    estimated_tax = _round2(session.estimated_tax_paid)
    total_payments = _round2(
        w2_withheld + other_withheld + other_withholding_manual + estimated_tax
    )

    balance_due = max(Decimal(0), tax_after_credits - total_payments)
    refund = max(Decimal(0), total_payments - tax_after_credits)

    form_1040 = Form1040(
        line1a_w2_wages=_round2(gross["wages"]),
        line2b_taxable_interest=_round2(sched_b.total_taxable_interest),
        line3b_ordinary_dividends=_round2(sched_b.total_ordinary_dividends),
        line3a_qualified_dividends=_round2(qualified_divs),
        line4b_ira_distributions=_round2(gross["retirement_distributions"]),
        line5b_taxable_ss=_round2(gross["taxable_ss"]),
        line7_capital_gain_loss=_round2(gross["capital_gain_loss"]),  # §1211(b) cap applied
        line8_other_income=_round2(sched_e.net + gross["other_income"]),
        line9_total_income=_round2(gross["total"]),
        line10_adjustments=_round2(sum(adjustments.values())),
        line11_agi=agi,
        line12_standard_or_itemized=deduction,
        line13_qbi_deduction=qbi_deduction,
        line15_taxable_income=taxable_income,
        line16_tax=income_tax,
        line24_total_tax=total_tax,
        line19_ctc=ctc,
        line20_other_credits=dep_care_credit,
        line25a_w2_withheld=w2_withheld,
        line25b_1099_withheld=other_withheld,
        line25c_other_withheld=other_withholding_manual,
        line26_estimated_payments=estimated_tax,
        line33_total_payments=total_payments,
        line37_amount_owed=balance_due,
        line35a_refund=refund,
    )

    return ComputedFederalReturn(
        form_1040=form_1040,
        schedule_b=sched_b if sched_b.required else None,
        schedule_d=sched_d if (sched_d.short_term_transactions or sched_d.long_term_transactions) else None,
        schedule_e=sched_e if sched_e.entries else None,
        agi=agi,
        taxable_income=taxable_income,
        total_tax=total_tax,
        total_payments=total_payments,
        balance_due=balance_due,
        refund=refund,
    )
