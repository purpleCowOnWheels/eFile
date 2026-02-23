"""Tests for the SSA-1099 parser."""

from __future__ import annotations

from decimal import Decimal

from pfile.parsers.ssa1099 import SSA1099Parser


_SSA_TEXT_BOX_FORMAT = """\
SOCIAL SECURITY BENEFIT STATEMENT
2024 Benefits Statement
Box 3   Total benefits paid in 2024
$24,000.00
Box 4   Benefits repaid to SSA in 2024
$0.00
Box 6   Voluntary federal income tax withheld
$2,400.00
"""

_SSA_TEXT_LETTER_FORMAT = """\
Social Security Administration
Benefit Statement for 2024

Your net benefits this year (Box 5) totaled $21,600.00.

Box 3. Benefits paid                  $24,000.00
Box 4. Benefits repaid                     $0.00
Box 6. Federal income tax withheld     $2,400.00
"""


def test_box3_box_format():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_BOX_FORMAT)
    assert doc.box3_benefits_paid == Decimal("24000.00")


def test_box6_box_format():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_BOX_FORMAT)
    assert doc.box6_voluntary_federal_withheld == Decimal("2400.00")


def test_box4_zero():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_BOX_FORMAT)
    assert doc.box4_benefits_repaid == Decimal("0.00")


def test_net_benefits_property():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_BOX_FORMAT)
    assert doc.net_benefits == Decimal("24000.00")


def test_letter_format_box3():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_LETTER_FORMAT)
    assert doc.box3_benefits_paid == Decimal("24000.00")


def test_letter_format_box6():
    p = SSA1099Parser()
    doc = p._parse_text(_SSA_TEXT_LETTER_FORMAT)
    assert doc.box6_voluntary_federal_withheld == Decimal("2400.00")
