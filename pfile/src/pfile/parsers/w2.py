"""W-2 parser — deterministic extraction using PyMuPDF + regex."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from pfile.models.documents import Box12Entry, EntityInfo, ParseConfidence, W2
from pfile.parsers.base import BaseParser


def _parse_amount(text: str) -> Decimal:
    cleaned = text.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal(0)


def _amounts_on_next_line(text: str, label_pattern: str) -> list[Decimal]:
    """
    W-2 layout: a combined label line (containing multiple box names) is
    followed by a values line with space-separated amounts.

    This function finds the label line matching label_pattern, then extracts
    ALL decimal numbers from the NEXT line, skipping any leading non-numeric
    tokens (e.g. employer name, street address, EIN).
    """
    m = re.search(label_pattern, text, re.IGNORECASE)
    if not m:
        return []
    # Find start of the next line after the match
    newline_pos = text.find("\n", m.start())
    if newline_pos == -1:
        return []
    next_line_end = text.find("\n", newline_pos + 1)
    next_line = text[newline_pos + 1 : next_line_end if next_line_end != -1 else None]
    return [_parse_amount(a) for a in re.findall(r"[\d,]+\.\d{2}", next_line)]


def _find_str(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


class W2Parser(BaseParser[W2]):
    """
    Parse IRS Form W-2 from a PDF.

    W-2 layout: label rows contain multiple box names side-by-side;
    the following line contains the corresponding values in the same order.
    Example:
      "b EIN  1 Wages...  2 Federal income tax withheld"
      "47-2003394  370211.05  81987.66"

    Tested against:
      - ADP-generated W-2 (Daniel_Costanza_2024_W2.pdf)
      - BKRCO LLC W-2 (2024-W2-Becca.pdf)
    """

    def parse(self, file: Path) -> W2:
        text = self.extract_text(file)
        return self._parse_text(text, file)

    def _parse_text(self, text: str, file: Path | None = None) -> W2:
        confidence: dict[str, float] = {}

        def got(field: str, val: Decimal | str | None) -> None:
            confidence[field] = 1.0 if val and val != Decimal(0) else 0.4

        # ---------------------------------------------------------------
        # Employer EIN — appears directly after the "b EIN" label line
        # ---------------------------------------------------------------
        ein = _find_str(text, r"(?:Employer identification number|EIN)[^\n]*\n\s*(\d{2}-\d{7})")
        got("employer_ein", ein)

        # ---------------------------------------------------------------
        # Boxes 1 + 2 — values follow the "1 Wages ... 2 Federal" label line
        # Label line: "b Employer... 1 Wages, tips, other compensation 2 Federal income tax withheld"
        # Value line:  "<EIN>  <wages>  <withheld>"
        # ---------------------------------------------------------------
        b1_b2 = _amounts_on_next_line(text, r"1\s+Wages,\s+tips.*?2\s+Federal income tax withheld")
        box1 = b1_b2[0] if len(b1_b2) >= 1 else Decimal(0)
        box2 = b1_b2[1] if len(b1_b2) >= 2 else Decimal(0)
        got("box1_wages", box1)
        got("box2_federal_withheld", box2)

        # ---------------------------------------------------------------
        # Boxes 3 + 4 — values follow the "3 SS wages ... 4 SS withheld" label line
        # Value line: "<employer_name>  <ss_wages>  <ss_withheld>"
        # ---------------------------------------------------------------
        b3_b4 = _amounts_on_next_line(text, r"3\s+Social security wages\s+4\s+Social security tax withheld")
        box3 = b3_b4[0] if len(b3_b4) >= 1 else Decimal(0)
        box4 = b3_b4[1] if len(b3_b4) >= 2 else Decimal(0)
        got("box3_ss_wages", box3)
        got("box4_ss_withheld", box4)

        # ---------------------------------------------------------------
        # Boxes 5 + 6 — values follow "5 Medicare wages ... 6 Medicare tax withheld"
        # Value line: "<address_line>  <medicare_wages>  <medicare_withheld>"
        # ---------------------------------------------------------------
        b5_b6 = _amounts_on_next_line(text, r"5\s+Medicare wages and tips\s+6\s+Medicare tax withheld")
        box5 = b5_b6[0] if len(b5_b6) >= 1 else Decimal(0)
        box6 = b5_b6[1] if len(b5_b6) >= 2 else Decimal(0)
        got("box5_medicare_wages", box5)
        got("box6_medicare_withheld", box6)

        # ---------------------------------------------------------------
        # Box 10 — dependent care benefits
        # Appears on its own or inline; look for it near "10 Dependent care"
        # ---------------------------------------------------------------
        b10_vals = _amounts_on_next_line(text, r"9\s+10\s+Dependent care benefits")
        box10 = b10_vals[0] if b10_vals else Decimal(0)
        # Fallback: inline match
        if not box10:
            m = re.search(r"10\s+Dependent care benefits\s*\n.*?([\d,]+\.\d{2})", text)
            box10 = _parse_amount(m.group(1)) if m else Decimal(0)
        got("box10_dependent_care", box10)

        # ---------------------------------------------------------------
        # Employer name — first non-numeric token on the line after box c label.
        # Stop before any sequence of digits (the SS wages value that follows).
        # ---------------------------------------------------------------
        employer_name = _find_str(
            text,
            r"c\s+Employer[^\n]+\n([A-Z][A-Za-z0-9 &',.\-]+?)\s+\d[\d,]+\.\d{2}",
        )
        got("employer_name", employer_name)

        # ---------------------------------------------------------------
        # Box 12 — coded entries like "AA 3430.00", "C 162.00", "DD 34797.96"
        # Only IRS-defined box 12 codes are valid.  This prevents false
        # positives from state abbreviations, EINs, and other nearby text.
        # Source: IRS W-2 instructions (Publication 15-A).
        # ---------------------------------------------------------------
        _VALID_BOX12_CODES: frozenset[str] = frozenset({
            "A", "B", "C", "D", "E", "F", "G", "H",
            "J", "K", "L", "M", "N", "P", "Q", "R",
            "S", "T", "V", "W", "Y", "Z",
            "AA", "BB", "DD", "EE", "FF", "GG", "HH",
        })
        seen_box12: set[tuple[str, str]] = set()
        box12_entries: list[Box12Entry] = []
        for m in re.finditer(r"\b([A-Z]{1,2})\s+([\d,]+\.\d{2})\b", text):
            code, amt_str = m.group(1), m.group(2)
            key = (code, amt_str)
            if code in _VALID_BOX12_CODES and key not in seen_box12:
                seen_box12.add(key)
                box12_entries.append(Box12Entry(code=code, amount=_parse_amount(amt_str)))
        got("box12", box12_entries or None)

        # ---------------------------------------------------------------
        # Box 13 — Retirement plan checkbox (look for "X" near the label)
        # ---------------------------------------------------------------
        retirement_plan = bool(re.search(
            r"Retirement\s+plan[^\n]*\n[^\n]*\bX\b|\bX\b[^\n]*Retirement\s+plan",
            text, re.IGNORECASE,
        ))
        got("box13_retirement_plan", retirement_plan or None)

        # ---------------------------------------------------------------
        # Box 14 — Other (NYPFL, NYSDI, union dues, etc.)
        # Pattern: "LABEL  amount" on same line, label is 3–8 uppercase letters
        # ---------------------------------------------------------------
        _EXCLUDED_14 = _EXCLUDED_CODES | {"FAST", "USE", "IRS", "COPY", "FORM", "SAFE"}
        box14: dict[str, str] = {}
        for m in re.finditer(r"\b([A-Z]{3,8})\s+([\d,]+\.\d{2})\b", text):
            label, amt = m.group(1), m.group(2)
            # Skip zero amounts and codes that look like names/addresses
            if label not in _EXCLUDED_14 and amt != "0.00":
                box14[label] = amt
        got("box14", box14 or None)

        # ---------------------------------------------------------------
        # State / local boxes (15–20)
        # Label line: "15 State  Employer's state ID  16 State wages  17 State income tax ..."
        # Value line: "NY  <state_id>  <wages>  <withheld>"
        # ---------------------------------------------------------------
        state = _find_str(text, r"15\s+State[^\n]+\n([A-Z]{2})\b")
        got("box15_state", state)

        state_id = _find_str(text, r"15\s+State[^\n]+\n[A-Z]{2}\s+(\d{6,12})\b")
        got("employer_state_id", state_id)

        state_vals = _amounts_on_next_line(
            text, r"15\s+State.*?16\s+State wages.*?17\s+State income tax"
        )
        box16 = state_vals[0] if len(state_vals) >= 1 else Decimal(0)
        box17 = state_vals[1] if len(state_vals) >= 2 else Decimal(0)
        box18 = state_vals[2] if len(state_vals) >= 3 else Decimal(0)
        box19 = state_vals[3] if len(state_vals) >= 4 else Decimal(0)
        got("box16_state_wages", box16)
        got("box17_state_withheld", box17)
        got("box18_local_wages", box18)
        got("box19_local_withheld", box19)

        return W2(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            employer=EntityInfo(name=employer_name or "", ein=ein),
            box1_wages=box1,
            box2_federal_withheld=box2,
            box3_ss_wages=box3,
            box4_ss_withheld=box4,
            box5_medicare_wages=box5,
            box6_medicare_withheld=box6,
            box10_dependent_care=box10,
            box12=box12_entries,
            box13_retirement_plan=retirement_plan,
            box14=box14,
            box15_state=state,
            box15_employer_state_id=state_id,
            box16_state_wages=box16,
            box17_state_withheld=box17,
            box18_local_wages=box18,
            box19_local_withheld=box19,
        )
