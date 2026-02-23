"""SSA-1099 Social Security Benefit Statement parser."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from pfile.models.documents import ParseConfidence, SSA_1099
from pfile.parsers.base import BaseParser


def _parse_amount(text: str) -> Decimal:
    cleaned = re.sub(r"[,$\s]", "", text)
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal(0)


def _find_amount(text: str, pattern: str) -> Decimal:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return Decimal(0)
    return _parse_amount(m.group(1))


class SSA1099Parser(BaseParser[SSA_1099]):
    """
    Parse SSA-1099 (Social Security Benefit Statement).

    The SSA issues this form in two layouts:
      - Standard letter format: "Box 3: Benefits paid ... $X,XXX.XX"
      - Table format: labeled columns with amounts

    We use regex for all fields since the layout is deterministic.
    """

    def parse(self, file: Path) -> SSA_1099:
        text = self.extract_text(file)
        return self._parse_text(text, file)

    def _parse_text(self, text: str, file: Path | None = None) -> SSA_1099:
        confidence: dict[str, float] = {}

        def scored(field: str, val: Decimal) -> Decimal:
            confidence[field] = 1.0 if val != Decimal(0) else 0.3
            return val

        # Box 3: Total benefits paid (gross)
        # Patterns: "Box 3 $X,XXX.XX", "Box 3\n$24,000.00", "Benefits paid...X,XXX.XX"
        box3 = _find_amount(
            text,
            r"(?:Box\s*3|Total benefits paid)[\s\S]{0,60}?\$?\s*([\d,]+\.\d{2})",
        )
        if not box3:
            box3 = _find_amount(
                text,
                r"\bBox\s+3\b[\s\S]{0,40}?\$?\s*([\d,]+\.\d{2})",
            )
        box3 = scored("box3_benefits_paid", box3)

        # Box 4: Benefits repaid (if any — most returns have $0)
        box4 = _find_amount(
            text,
            r"(?:Box\s*4|Benefits repaid|Medicare premium)[\s\S]{0,60}?\$?\s*([\d,]+\.\d{2})",
        )
        box4 = scored("box4_benefits_repaid", box4)

        # Box 6: Voluntary federal income tax withheld
        box6 = _find_amount(
            text,
            r"(?:Box\s*6|Voluntary federal income tax withheld|Federal income tax withheld)"
            r"[\s\S]{0,60}?\$?\s*([\d,]+\.\d{2})",
        )
        box6 = scored("box6_voluntary_federal_withheld", box6)

        return SSA_1099(
            source_file=file,
            confidence=ParseConfidence(scores=confidence),
            box3_benefits_paid=box3,
            box4_benefits_repaid=box4,
            box6_voluntary_federal_withheld=box6,
        )
