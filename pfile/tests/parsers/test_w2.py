"""Tests for the W-2 parser."""

from __future__ import annotations

from decimal import Decimal

from pfile.parsers.w2 import W2Parser


# Representative W-2 text — matches ADP / standard IRS layout
_W2_TEXT = """\
a Employee's social security number
111-22-3333
b Employer identification number (EIN)
47-2003394
c Employer's name, address, and ZIP code
ACME CORPORATION
123 BUSINESS AVE
NEW YORK NY 10001
d Control number
e Employee's first name and initial   Last name
John                                  Smith
1 Wages, tips, other compensation     2 Federal income tax withheld
370211.05                             81987.66
3 Social security wages               4 Social security tax withheld
160200.00                             9932.40
5 Medicare wages and tips             6 Medicare tax withheld
370211.05                             7005.36
9                                     10 Dependent care benefits
                                      0.00
12a Code                              12b Code
DD                                    34797.96
15 State    Employer's state ID number 16 State wages, tips, etc.  17 State income tax
NY         XX-XXXXXXX                 370211.05                    16250.00
18 Local wages, tips, etc.            19 Local income tax          20 Locality name
370211.05                             0.00                         NYC
"""


def test_wages_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box1_wages == Decimal("370211.05")


def test_federal_withheld_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box2_federal_withheld == Decimal("81987.66")


def test_ss_wages_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box3_ss_wages == Decimal("160200.00")


def test_medicare_wages_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box5_medicare_wages == Decimal("370211.05")


def test_state_withheld_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box17_state_withheld == Decimal("16250.00")


def test_state_code_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box15_state == "NY"


def test_box12_dd_health_parsed():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    dd_entries = [e for e in w2.box12 if e.code == "DD"]
    assert len(dd_entries) == 1
    assert dd_entries[0].amount == Decimal("34797.96")


def test_box12_rejects_state_abbreviations():
    """State abbreviations near dollar amounts must not become box 12 entries."""
    text = _W2_TEXT + "\nNY 12345.00\nCA 5000.00\n"
    parser = W2Parser()
    w2 = parser._parse_text(text)
    codes = [e.code for e in w2.box12]
    assert "NY" not in codes
    assert "CA" not in codes


def test_box12_rejects_unknown_codes():
    """Only IRS-defined codes should appear in box 12."""
    text = _W2_TEXT + "\nZZ 999.00\n"
    parser = W2Parser()
    w2 = parser._parse_text(text)
    codes = [e.code for e in w2.box12]
    assert "ZZ" not in codes


def test_dependent_care_zero_is_zero():
    parser = W2Parser()
    w2 = parser._parse_text(_W2_TEXT)
    assert w2.box10_dependent_care == Decimal("0")
