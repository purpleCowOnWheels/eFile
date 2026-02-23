"""K-1 parser — handles both Form 1065 (partnership) and Form 1120S (S-corp)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pfile.models.documents import K1_1065, K1_1120S, EntityInfo, ParseConfidence
from pfile.parsers.base import BaseParser
from pfile.parsers.llm import extract_structured

# ---------------------------------------------------------------------------
# Intermediate LLM output schemas
# These are flat, LLM-friendly versions that map to our domain models.
# Using str for amounts so the LLM doesn't have to worry about Decimal.
# ---------------------------------------------------------------------------


class _LLM_K1_1120S(BaseModel):
    """LLM extraction target for Schedule K-1 (Form 1120S)."""

    # Entity info
    corporation_name: str | None = None
    corporation_ein: str | None = None
    corporation_address: str | None = None
    shareholder_ssn_or_ein: str | None = None
    tax_year: int | None = None
    final_k1: bool = False
    amended_k1: bool = False
    ownership_pct: str | None = None  # e.g. "100.000000"

    # Income / loss boxes
    box1_ordinary_income: str | None = None
    box2_net_rental_re_income: str | None = None
    box3_other_rental_income: str | None = None
    box4_interest_income: str | None = None
    box5a_ordinary_dividends: str | None = None
    box5b_qualified_dividends: str | None = None
    box6_royalties: str | None = None
    box7_net_stcg: str | None = None
    box8a_net_ltcg: str | None = None
    box9_section_1231_gain: str | None = None
    box10_other_income: dict[str, str] | str | None = None  # plain amount or {code: amount}

    # Deductions
    box11_section_179: str | None = None
    box12_other_deductions: dict[str, str] = Field(default_factory=dict)  # code → amount

    # Credits
    box13_credits: dict[str, str] = Field(default_factory=dict)

    # AMT
    box15_amt_items: dict[str, str] = Field(default_factory=dict)

    # Basis items
    box16_basis_items: dict[str, str] = Field(default_factory=dict)  # code → amount

    # Other info (QBI, gross receipts, etc.)
    box17_other_info: dict[str, str] = Field(default_factory=dict)  # code → value


class _LLM_K1_1065(BaseModel):
    """LLM extraction target for Schedule K-1 (Form 1065)."""

    # Entity info
    partnership_name: str | None = None
    partnership_ein: str | None = None
    partnership_address: str | None = None
    partner_ssn_or_ein: str | None = None
    tax_year: int | None = None
    final_k1: bool = False
    amended_k1: bool = False
    profit_share_pct: str | None = None
    loss_share_pct: str | None = None
    capital_share_pct: str | None = None

    # Income / loss boxes
    box1_ordinary_income: str | None = None
    box2_net_rental_re_income: str | None = None
    box3_other_rental_income: str | None = None
    box4_guaranteed_payments_services: str | None = None
    box5_guaranteed_payments_capital: str | None = None
    box6a_net_ltcg: str | None = None
    box7_net_stcg: str | None = None
    box8_collectibles_gain: str | None = None
    box9a_section_1231_gain: str | None = None
    box10_other_income: dict[str, str] | str | None = None  # plain amount or {code: amount}

    # Deductions
    box11_section_179: str | None = None
    box12_other_deductions: dict[str, str] = Field(default_factory=dict)

    # Credits
    box13_credits: dict[str, str] = Field(default_factory=dict)

    # Self-employment
    box14_self_employment: str | None = None

    # AMT
    box15_amt_items: dict[str, str] = Field(default_factory=dict)

    # Tax-exempt / nondeductible
    box16_tax_exempt_income: dict[str, str] = Field(default_factory=dict)

    # Distributions
    box19_distributions: str | None = None

    # Other info
    box20_other_info: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_decimal(value: dict[str, str] | str | None) -> Decimal:
    if not value:
        return Decimal(0)
    # If the LLM returned a coded dict (e.g. {"E": "66,500"}), sum all values.
    if isinstance(value, dict):
        return sum((_to_decimal(v) for v in value.values()), Decimal(0))
    cleaned = value.replace(",", "").replace("$", "").replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal(0)


def _to_decimal_dict(d: dict[str, str]) -> dict[str, Decimal]:
    return {k: _to_decimal(v) for k, v in d.items()}


def _detect_form_type(text: str) -> Literal["1120S", "1065"]:
    if "1120-S" in text or "1120S" in text or "S corporation" in text.lower():
        return "1120S"
    if "Form 1065" in text or "partnership" in text.lower():
        return "1065"
    # Default guess based on common K-1 language
    if "shareholder" in text.lower():
        return "1120S"
    return "1065"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


_K1_1120S_PROMPT = """\
Extract all fields from this Schedule K-1 (Form 1120S) tax document.
The document may be embedded in a larger S-corporation tax return (Form 1120-S).
Focus on the Schedule K-1 section titled "Shareholder's Share of Current Year Income,
Deductions, Credits, and Other Items".

Key things to extract:
- Corporation name, EIN, address (Part I)
- Shareholder SSN/EIN, ownership percentage (Part II)
- All box values in Part III (boxes 1-17)
- For coded boxes (e.g. box 10 code E, box 12 code A, box 16 code C), return as
  a dict with the code as key and amount as value string, e.g. {"E": "66500", "A": "1250"}
- Negative numbers may appear in parentheses, e.g. (1,234) means -1234
- Amounts may have commas as thousands separators
- If a box is blank or zero, use null or omit it
"""

_K1_1065_PROMPT = """\
Extract all fields from this Schedule K-1 (Form 1065) tax document.
The document may be embedded in a larger partnership tax return (Form 1065).
Focus on the Schedule K-1 section titled "Partner's Share of Income, Deductions,
Credits, and Other Items".

Key things to extract:
- Partnership name, EIN, address (Part I)
- Partner SSN/EIN, profit/loss/capital share percentages (Part II)
- All box values in Part III (boxes 1-20)
- For coded boxes, return as a dict with code as key and amount as value string
- Negative numbers may appear in parentheses
- Amounts may have commas as thousands separators
- If a box is blank or zero, use null or omit it
"""


class K1Parser(BaseParser[K1_1120S | K1_1065]):
    """Parse Schedule K-1 from either Form 1065 or Form 1120S."""

    def parse(self, file: Path) -> K1_1120S | K1_1065:
        text = self.extract_text(file)
        form_type = _detect_form_type(text)

        if form_type == "1120S":
            return self._parse_1120s(text, file)
        return self._parse_1065(text, file)

    def _parse_1120s(self, text: str, file: Path) -> K1_1120S:
        llm_result, confidence = extract_structured(
            text=text,
            prompt=_K1_1120S_PROMPT,
            model_class=_LLM_K1_1120S,
        )

        return K1_1120S(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            corporation=EntityInfo(
                name=llm_result.corporation_name or "",
                ein=llm_result.corporation_ein,
                address=llm_result.corporation_address,
            ),
            shareholder_ssn_or_ein=llm_result.shareholder_ssn_or_ein,
            tax_year=llm_result.tax_year,
            final_k1=llm_result.final_k1,
            amended_k1=llm_result.amended_k1,
            ownership_pct=Decimal(llm_result.ownership_pct) if llm_result.ownership_pct else None,
            box1_ordinary_income=_to_decimal(llm_result.box1_ordinary_income),
            box2_net_rental_re_income=_to_decimal(llm_result.box2_net_rental_re_income),
            box3_other_rental_income=_to_decimal(llm_result.box3_other_rental_income),
            box4_interest_income=_to_decimal(llm_result.box4_interest_income),
            box5a_ordinary_dividends=_to_decimal(llm_result.box5a_ordinary_dividends),
            box5b_qualified_dividends=_to_decimal(llm_result.box5b_qualified_dividends),
            box6_royalties=_to_decimal(llm_result.box6_royalties),
            box7_net_stcg=_to_decimal(llm_result.box7_net_stcg),
            box8a_net_ltcg=_to_decimal(llm_result.box8a_net_ltcg),
            box9_section_1231_gain=_to_decimal(llm_result.box9_section_1231_gain),
            box10_other_income=_to_decimal(llm_result.box10_other_income),
            box11_section_179=_to_decimal(llm_result.box11_section_179),
            box12_other_deductions=_to_decimal_dict(llm_result.box12_other_deductions),
            box13_credits=_to_decimal_dict(llm_result.box13_credits),
            box15_amt_items=_to_decimal_dict(llm_result.box15_amt_items),
            box16_basis_items=_to_decimal_dict(llm_result.box16_basis_items),
            box17_other_info=llm_result.box17_other_info,
        )

    def _parse_1065(self, text: str, file: Path) -> K1_1065:
        llm_result, confidence = extract_structured(
            text=text,
            prompt=_K1_1065_PROMPT,
            model_class=_LLM_K1_1065,
        )

        return K1_1065(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            partnership=EntityInfo(
                name=llm_result.partnership_name or "",
                ein=llm_result.partnership_ein,
                address=llm_result.partnership_address,
            ),
            partner_ssn_or_ein=llm_result.partner_ssn_or_ein,
            tax_year=llm_result.tax_year,
            final_k1=llm_result.final_k1,
            amended_k1=llm_result.amended_k1,
            profit_share_pct=Decimal(llm_result.profit_share_pct) if llm_result.profit_share_pct else None,
            loss_share_pct=Decimal(llm_result.loss_share_pct) if llm_result.loss_share_pct else None,
            capital_share_pct=Decimal(llm_result.capital_share_pct) if llm_result.capital_share_pct else None,
            box1_ordinary_income=_to_decimal(llm_result.box1_ordinary_income),
            box2_net_rental_re_income=_to_decimal(llm_result.box2_net_rental_re_income),
            box3_other_rental_income=_to_decimal(llm_result.box3_other_rental_income),
            box4_guaranteed_payments_services=_to_decimal(llm_result.box4_guaranteed_payments_services),
            box5_guaranteed_payments_capital=_to_decimal(llm_result.box5_guaranteed_payments_capital),
            box6a_net_ltcg=_to_decimal(llm_result.box6a_net_ltcg),
            box7_net_stcg=_to_decimal(llm_result.box7_net_stcg),
            box8_collectibles_gain=_to_decimal(llm_result.box8_collectibles_gain),
            box9a_section_1231_gain=_to_decimal(llm_result.box9a_section_1231_gain),
            box10_other_income=_to_decimal(llm_result.box10_other_income),
            box11_section_179=_to_decimal(llm_result.box11_section_179),
            box12_other_deductions=_to_decimal_dict(llm_result.box12_other_deductions),
            box13_credits=_to_decimal_dict(llm_result.box13_credits),
            box14_self_employment=_to_decimal(llm_result.box14_self_employment),
            box15_amt_items=_to_decimal_dict(llm_result.box15_amt_items),
            box16_tax_exempt_income=_to_decimal_dict(llm_result.box16_tax_exempt_income),
            box19_distributions=_to_decimal(llm_result.box19_distributions),
            box20_other_info=llm_result.box20_other_info,
        )
