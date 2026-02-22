"""
1099 parsers — INT, DIV, B, R.

Layout strategies per source:
  Ally 1099-INT        — tabular rows "Description  BOX#  AMOUNT"
  Standard 1099-INT    — "Box N: Label\n$amount" (Yieldstreet, Portland)
  Fidelity dots 1099   — "Label.....amount" two-column format
  Fidelity 1099-B      — detailed transaction table, regex
  Yieldstreet 1099-DIV — standard IRS multi-column grid → LLM
  1099-R               — LLM (varied layouts)
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from pfile.models.documents import (
    BrokerageTransaction,
    CoverageType,
    EntityInfo,
    F1099_B,
    F1099_DIV,
    F1099_INT,
    F1099_R,
    ParseConfidence,
    TermType,
)
from pfile.parsers.base import BaseParser
from pfile.parsers.llm import extract_structured

from pydantic import BaseModel


def _d(text: str | None) -> Decimal:
    if not text:
        return Decimal(0)
    cleaned = text.replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal(0)


def _find(text: str, *patterns: str) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _dots(text: str, label: str) -> Decimal:
    """Parse Fidelity 'Label.....amount' format."""
    m = re.search(rf"{re.escape(label)}[.\s]+([\d,]+\.\d{{2}})", text, re.IGNORECASE)
    return _d(m.group(1)) if m else Decimal(0)


# ---------------------------------------------------------------------------
# 1099-INT
# ---------------------------------------------------------------------------


class F1099_INT_Parser(BaseParser[list[F1099_INT]]):
    """
    Returns a list because some 1099-INTs (e.g. Ally) report multiple
    accounts on one statement.
    """

    def parse(self, file: Path) -> list[F1099_INT]:
        text = self.extract_text(file)
        payer_name, payer_ein = self._extract_payer(text)
        payer = EntityInfo(name=payer_name or "", ein=payer_ein)

        if self._is_ally_format(text):
            return self._parse_ally(text, payer, file)
        if self._is_box_label_format(text):
            return [self._parse_box_label(text, payer, file)]
        # Fallback: LLM
        return [self._parse_llm(text, payer, file)]

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ally_format(text: str) -> bool:
        return bool(re.search(r"IRSDESCRIPTION\s+BOX#\s+AMOUNT", text, re.IGNORECASE))

    @staticmethod
    def _is_box_label_format(text: str) -> bool:
        return bool(re.search(r"Box\s+1\s*:\s*Interest Income", text, re.IGNORECASE))

    # ------------------------------------------------------------------
    # Payer extraction (common to all formats)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_payer(text: str) -> tuple[str | None, str | None]:
        payer_name = _find(
            text,
            r"Payer[''s]*\s+Name[^:\n]*:\s*\n([^\n]+)",
            r"^([A-Z][A-Z &\-,\.]+(?:BANK|LLC|INC|CORP|FUND|TRUST)?)\s*\n",
        )
        ein = _find(text, r"PAYER[''S]*\s+TIN[^\n]*\n\s*([0-9]{2}-[0-9]{7})",
                    r"([0-9]{2}-[0-9]{7})")
        return payer_name, ein

    # ------------------------------------------------------------------
    # Ally tabular format
    # Each account is a block starting with an account number row:
    #   "ACCOUNTNUMBER  Interest income  1  425.56"
    # ------------------------------------------------------------------

    def _parse_ally(self, text: str, payer: EntityInfo, file: Path) -> list[F1099_INT]:
        results: list[F1099_INT] = []

        # Find all account blocks (each starts with a bare account number)
        account_blocks = re.split(r"\n(?=\d{10}\s+Interest income)", text)

        for block in account_blocks:
            # Must contain an interest income line to be a valid account
            if not re.search(r"Interest income\s+1\s+[\d,]+\.\d{2}", block):
                continue

            def get(label: str, box: str) -> Decimal:
                m = re.search(
                    rf"{re.escape(label)}\s+{re.escape(box)}\s+([\d,]+\.\d{{2}})", block
                )
                return _d(m.group(1)) if m else Decimal(0)

            results.append(F1099_INT(
                source_file=file,
                confidence=ParseConfidence(scores={"box1_interest_income": 1.0}),
                payer=payer,
                box1_interest_income=get("Interest income", "1"),
                box2_early_withdrawal_penalty=get("Early withdrawal penalty", "2"),
                box3_us_savings_bond_interest=get(
                    "Interest on U.S. Savings Bonds and Treasury obligations", "3"
                ),
                box4_federal_withheld=get("Federal income tax withheld", "4"),
                box8_tax_exempt_interest=get("Tax-exempt interest", "8"),
                box10_market_discount=get("Market discount", "10"),
                box11_bond_premium=get("Bond premium", "11"),
            ))

        return results or [F1099_INT(source_file=file, payer=payer)]

    # ------------------------------------------------------------------
    # Standard "Box N: Label\n$amount" format (Yieldstreet, Portland)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_box_label(text: str, payer: EntityInfo, file: Path) -> F1099_INT:
        def box(n: str) -> Decimal:
            m = re.search(
                rf"Box\s+{re.escape(n)}\s*:\s*[^\n]+\n\s*\$?\s*([\d,]+\.\d{{2}})",
                text, re.IGNORECASE,
            )
            return _d(m.group(1)) if m else Decimal(0)

        return F1099_INT(
            source_file=file,
            confidence=ParseConfidence(scores={"box1_interest_income": 1.0}),
            payer=payer,
            box1_interest_income=box("1"),
            box2_early_withdrawal_penalty=box("2"),
            box3_us_savings_bond_interest=box("3"),
            box4_federal_withheld=box("4"),
            box8_tax_exempt_interest=box("8"),
            box10_market_discount=box("10"),
            box11_bond_premium=box("11"),
        )

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    class _LLM1099INT(BaseModel):
        payer_name: str | None = None
        payer_ein: str | None = None
        box1_interest_income: str | None = None
        box2_early_withdrawal_penalty: str | None = None
        box3_us_savings_bond_interest: str | None = None
        box4_federal_withheld: str | None = None
        box8_tax_exempt_interest: str | None = None
        box10_market_discount: str | None = None
        box11_bond_premium: str | None = None

    def _parse_llm(self, text: str, payer: EntityInfo, file: Path) -> F1099_INT:
        result, confidence = extract_structured(
            text=text,
            prompt="Extract all fields from this Form 1099-INT (Interest Income).",
            model_class=self._LLM1099INT,
        )
        return F1099_INT(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            payer=EntityInfo(
                name=result.payer_name or payer.name,
                ein=result.payer_ein or payer.ein,
            ),
            box1_interest_income=_d(result.box1_interest_income),
            box2_early_withdrawal_penalty=_d(result.box2_early_withdrawal_penalty),
            box3_us_savings_bond_interest=_d(result.box3_us_savings_bond_interest),
            box4_federal_withheld=_d(result.box4_federal_withheld),
            box8_tax_exempt_interest=_d(result.box8_tax_exempt_interest),
            box10_market_discount=_d(result.box10_market_discount),
            box11_bond_premium=_d(result.box11_bond_premium),
        )


# ---------------------------------------------------------------------------
# 1099-DIV
# ---------------------------------------------------------------------------


class F1099_DIV_Parser(BaseParser[F1099_DIV]):

    def parse(self, file: Path) -> F1099_DIV:
        text = self.extract_text(file)
        payer_name = _find(
            text,
            r"PAYER[''S]*\s+name[^\n]*\n([^\n]+)",
            r"^([A-Z][A-Z &\-,\.]+(?:FUND|LLC|INC|SERVICES)?)\s*\n",
        )
        ein = _find(text, r"PAYER[''S]*\s+TIN[^\n]*\n\s*([0-9]{9})",
                    r"Payer.*?Fed ID.*?([0-9]{2}-[0-9]{7})",
                    r"([0-9]{2}-[0-9]{7})")
        payer = EntityInfo(name=payer_name or "", ein=ein)

        if self._is_fidelity_dots(text):
            return self._parse_fidelity_dots(text, payer, file)
        return self._parse_llm(text, payer, file)

    @staticmethod
    def _is_fidelity_dots(text: str) -> bool:
        return bool(re.search(r"1a\s+Total Ordinary Dividends\.{5}", text, re.IGNORECASE))

    @staticmethod
    def _parse_fidelity_dots(text: str, payer: EntityInfo, file: Path) -> F1099_DIV:
        return F1099_DIV(
            source_file=file,
            confidence=ParseConfidence(scores={
                "box1a_total_ordinary_dividends": 1.0,
                "box1b_qualified_dividends": 1.0,
            }),
            payer=payer,
            box1a_total_ordinary_dividends=_dots(text, "1a Total Ordinary Dividends"),
            box1b_qualified_dividends=_dots(text, "1b Qualified Dividends"),
            box2a_total_capital_gain_dist=_dots(text, "2a Total Capital Gain Distributions"),
            box2b_unrecap_sec1250_gain=_dots(text, "2b Unrecap. Sec 1250 Gain"),
            box2c_section_1202_gain=_dots(text, "2c Section 1202 Gain"),
            box2d_collectibles_gain=_dots(text, "2d Collectibles"),
            box3_nondividend_distributions=_dots(text, "3 Nondividend Distributions"),
            box4_federal_withheld=_dots(text, "4 Federal Income Tax Withheld"),
            box5_section_199a_dividends=_dots(text, "5 Section 199A Dividends"),
            box7_foreign_tax_paid=_dots(text, "7 Foreign Tax Paid"),
        )

    class _LLM1099DIV(BaseModel):
        payer_name: str | None = None
        payer_ein: str | None = None
        box1a_total_ordinary_dividends: str | None = None
        box1b_qualified_dividends: str | None = None
        box2a_total_capital_gain_dist: str | None = None
        box2b_unrecap_sec1250_gain: str | None = None
        box3_nondividend_distributions: str | None = None
        box4_federal_withheld: str | None = None
        box5_section_199a_dividends: str | None = None
        box7_foreign_tax_paid: str | None = None

    def _parse_llm(self, text: str, payer: EntityInfo, file: Path) -> F1099_DIV:
        result, confidence = extract_structured(
            text=text,
            prompt="Extract all fields from this Form 1099-DIV (Dividends and Distributions).",
            model_class=self._LLM1099DIV,
        )
        return F1099_DIV(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            payer=EntityInfo(
                name=result.payer_name or payer.name,
                ein=result.payer_ein or payer.ein,
            ),
            box1a_total_ordinary_dividends=_d(result.box1a_total_ordinary_dividends),
            box1b_qualified_dividends=_d(result.box1b_qualified_dividends),
            box2a_total_capital_gain_dist=_d(result.box2a_total_capital_gain_dist),
            box2b_unrecap_sec1250_gain=_d(result.box2b_unrecap_sec1250_gain),
            box3_nondividend_distributions=_d(result.box3_nondividend_distributions),
            box4_federal_withheld=_d(result.box4_federal_withheld),
            box5_section_199a_dividends=_d(result.box5_section_199a_dividends),
            box7_foreign_tax_paid=_d(result.box7_foreign_tax_paid),
        )


# ---------------------------------------------------------------------------
# 1099-B  (Fidelity consolidated format)
# ---------------------------------------------------------------------------


class F1099_B_Parser(BaseParser[F1099_B]):

    def parse(self, file: Path) -> F1099_B:
        text = self.extract_text(file)
        ein = _find(text, r"Payer.*?Fed ID.*?([0-9]{2}-[0-9]{7})", r"([0-9]{2}-[0-9]{7})")
        payer_name = _find(
            text,
            r"Payer[''s]*\s+Name[^\n]*\n([^\n]+)",
            r"(NATIONAL FINANCIAL SERVICES|FIDELITY [A-Z ]+)",
        )
        payer = EntityInfo(name=payer_name or "", ein=ein)

        transactions = self._parse_transactions(text)
        agg_withheld = sum(t.federal_withheld for t in transactions)

        # Aggregate proceeds / basis from the summary table
        agg_proceeds = self._summary_column(text, 0)
        agg_basis = self._summary_column(text, 1)

        return F1099_B(
            source_file=file,
            confidence=ParseConfidence(scores={"aggregate_proceeds": 1.0}),
            payer=payer,
            transactions=transactions,
            aggregate_proceeds=agg_proceeds if agg_proceeds else None,
            aggregate_cost_basis=agg_basis if agg_basis else None,
            aggregate_federal_withheld=agg_withheld,
        )

    @staticmethod
    def _summary_column(text: str, col_idx: int) -> Decimal:
        """Extract a total from the 1099-B summary table footer row."""
        # The footer is a row of totals: "29,362.95 13,007.46 0.00 0.00 16,355.49 0.00"
        # preceded by the per-section rows.
        # We find the last row that has 6 space-separated numbers.
        totals_match = re.findall(
            r"^([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([-\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$",
            text, re.MULTILINE,
        )
        if not totals_match:
            return Decimal(0)
        last = totals_match[-1]
        return _d(last[col_idx]) if col_idx < len(last) else Decimal(0)

    @staticmethod
    def _parse_transactions(text: str) -> list[BrokerageTransaction]:
        """
        Parse Fidelity's detailed 1099-B transaction lines.

        Each transaction is two lines:
          Line 1: "DESCRIPTION,SYMBOL,CUSIP"
          Line 2: "Sale QUANTITY DATE_ACQ DATE_SOLD PROCEEDS BASIS GAIN_LOSS"

        We also detect term (short/long) from the section header.
        """
        transactions: list[BrokerageTransaction] = []
        current_term = TermType.UNKNOWN
        current_coverage = CoverageType.COVERED
        current_desc: str | None = None

        for line in text.splitlines():
            line = line.strip()

            # Section headers set term + coverage context
            if re.search(r"Short-term.*basis is reported", line, re.IGNORECASE):
                current_term, current_coverage = TermType.SHORT, CoverageType.COVERED
            elif re.search(r"Short-term.*basis is not reported", line, re.IGNORECASE):
                current_term, current_coverage = TermType.SHORT, CoverageType.UNCOVERED
            elif re.search(r"Long-term.*basis is reported", line, re.IGNORECASE):
                current_term, current_coverage = TermType.LONG, CoverageType.COVERED
            elif re.search(r"Long-term.*basis is not reported", line, re.IGNORECASE):
                current_term, current_coverage = TermType.LONG, CoverageType.UNCOVERED

            # Description line: "NAME,SYMBOL,CUSIP"
            desc_m = re.match(r"^([A-Z][^,]+),([A-Z0-9]+),(\d{9})$", line)
            if desc_m:
                current_desc = desc_m.group(1).strip()
                continue

            # Sale line: "Sale QTY DATE DATE PROCEEDS BASIS GAIN_LOSS [WITHHELD]"
            sale_m = re.match(
                r"^Sale\s+[\d.]+\s+\S+\s+\S+\s+"
                r"([\d,]+\.\d{2})\s+"   # proceeds
                r"([\d,]+\.\d{2})\s+"   # basis
                r"([-\d,]+\.\d{2})"     # gain/loss
                r"(?:\s+([\d,]+\.\d{2}))?",  # optional withheld
                line,
            )
            if sale_m and current_desc:
                transactions.append(BrokerageTransaction(
                    description=current_desc,
                    proceeds=_d(sale_m.group(1)),
                    cost_basis=_d(sale_m.group(2)),
                    term=current_term,
                    coverage=current_coverage,
                    federal_withheld=_d(sale_m.group(4)),
                ))
                current_desc = None

        return transactions


# ---------------------------------------------------------------------------
# 1099-R  (LLM — varied layouts)
# ---------------------------------------------------------------------------


class F1099_R_Parser(BaseParser[F1099_R]):

    class _LLM1099R(BaseModel):
        payer_name: str | None = None
        payer_ein: str | None = None
        box1_gross_distribution: str | None = None
        box2a_taxable_amount: str | None = None
        box2b_taxable_amount_not_determined: bool = False
        box4_federal_withheld: str | None = None
        box7_distribution_code: str | None = None
        box9b_total_employee_contributions: str | None = None
        box14_state_withheld: str | None = None

    def parse(self, file: Path) -> F1099_R:
        text = self.extract_text(file)
        result, confidence = extract_structured(
            text=text,
            prompt=(
                "Extract all fields from this Form 1099-R "
                "(Distributions from Pensions, Annuities, Retirement Plans, etc.)."
            ),
            model_class=self._LLM1099R,
        )
        return F1099_R(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            payer=EntityInfo(name=result.payer_name or "", ein=result.payer_ein),
            box1_gross_distribution=_d(result.box1_gross_distribution),
            box2a_taxable_amount=_d(result.box2a_taxable_amount),
            box2b_taxable_amount_not_determined=result.box2b_taxable_amount_not_determined,
            box4_federal_withheld=_d(result.box4_federal_withheld),
            box7_distribution_code=result.box7_distribution_code or "",
            box9b_total_employee_contributions=_d(result.box9b_total_employee_contributions) or None,
            box14_state_withheld=_d(result.box14_state_withheld),
        )


# ---------------------------------------------------------------------------
# Fidelity consolidated statement  (returns multiple docs)
# ---------------------------------------------------------------------------


class FidelityConsolidatedParser(BaseParser[tuple[F1099_DIV, F1099_B]]):
    """
    Parses a Fidelity consolidated 1099 statement into a (1099-DIV, 1099-B) pair.
    Uses regex throughout — Fidelity's format is consistent.
    """

    def parse(self, file: Path) -> tuple[F1099_DIV, F1099_B]:
        text = self.extract_text(file)
        div = F1099_DIV_Parser().parse(file)
        b = F1099_B_Parser().parse(file)
        return div, b
