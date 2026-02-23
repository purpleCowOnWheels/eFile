"""
Parser dispatcher — given any PDF, detect its type and return parsed document(s).

Detection is based on text fingerprints in the first 3 pages. The dispatcher
returns a list of documents (usually one, but Fidelity consolidated returns two).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

from pfile.models.documents import (
    AnyDocument,
    F1099_B,
    F1099_DIV,
    F1099_INT,
    F1099_R,
    K1_1065,
    K1_1120S,
    SSA_1099,
    W2,
)
from pfile.parsers.base import BaseParser
from pfile.parsers.f1099 import (
    F1099_B_Parser,
    F1099_DIV_Parser,
    F1099_INT_Parser,
    F1099_R_Parser,
    FidelityConsolidatedParser,
)
from pfile.parsers.k1 import K1Parser
from pfile.parsers.ssa1099 import SSA1099Parser
from pfile.parsers.w2 import W2Parser


class UnknownDocumentError(Exception):
    pass


class DocumentType:
    W2 = "W-2"
    K1_1120S = "K-1 (1120S)"
    K1_1065 = "K-1 (1065)"
    F1099_INT = "1099-INT"
    F1099_DIV = "1099-DIV"
    F1099_B = "1099-B"
    F1099_R = "1099-R"
    SSA_1099 = "SSA-1099"
    FIDELITY_CONSOLIDATED = "Fidelity Consolidated 1099"
    UNKNOWN = "Unknown"


def detect(text: str) -> str:
    """
    Identify the document type from extracted PDF text.
    Returns a DocumentType constant.
    """
    # Fidelity consolidated must be checked before individual 1099 types
    if re.search(r"TAX REPORTING STATEMENT", text) and re.search(
        r"FIDELITY|NATIONAL FINANCIAL SERVICES", text, re.IGNORECASE
    ):
        return DocumentType.FIDELITY_CONSOLIDATED

    if re.search(r"Wage and Tax Statement|W-2\b", text) and re.search(
        r"Wages, tips, other compensation", text, re.IGNORECASE
    ):
        return DocumentType.W2

    if re.search(r"Schedule K-1", text) and re.search(r"1120-S|S corporation|Shareholder", text):
        return DocumentType.K1_1120S

    if re.search(r"Schedule K-1", text) and re.search(r"Form 1065|partnership|Partner", text):
        return DocumentType.K1_1065

    if re.search(r"1099-R", text) or re.search(
        r"Distributions from Pensions.*Annuities.*Retirement", text, re.IGNORECASE
    ):
        return DocumentType.F1099_R

    if re.search(r"SSA-1099|Social Security Benefit Statement", text, re.IGNORECASE):
        return DocumentType.SSA_1099

    if re.search(r"1099-INT|Interest Income", text) and re.search(
        r"OMB No\. 1545-0112|Interest income.*BOX|Box 1.*Interest", text, re.IGNORECASE
    ):
        return DocumentType.F1099_INT

    if re.search(r"1099-DIV|Dividends and Distributions", text) and re.search(
        r"OMB No\. 1545-0110|1a.*[Tt]otal.*[Dd]ividend", text
    ):
        return DocumentType.F1099_DIV

    if re.search(r"1099-B|Proceeds from Broker", text):
        return DocumentType.F1099_B

    return DocumentType.UNKNOWN


def parse(file: Path) -> list[AnyDocument]:
    """
    Parse a PDF into one or more document models.

    Returns a list — usually a single item, but Fidelity consolidated
    returns [F1099_DIV, F1099_B].

    Raises UnknownDocumentError if the file type cannot be determined.
    """
    if not file.exists():
        raise FileNotFoundError(f"File not found: {file}")

    text = BaseParser.extract_text(file)  # type: ignore[arg-type]
    doc_type = detect(text)

    if doc_type == DocumentType.W2:
        return [W2Parser().parse(file)]

    if doc_type == DocumentType.K1_1120S:
        return [K1Parser().parse(file)]

    if doc_type == DocumentType.K1_1065:
        return [K1Parser().parse(file)]

    if doc_type == DocumentType.FIDELITY_CONSOLIDATED:
        div, b = FidelityConsolidatedParser().parse(file)
        docs: list[AnyDocument] = [div]
        # Only include 1099-B if there are actual transactions or non-zero proceeds
        if b.transactions or (b.aggregate_proceeds and b.aggregate_proceeds > 0):
            docs.append(b)
        return docs

    if doc_type == DocumentType.F1099_INT:
        return F1099_INT_Parser().parse(file)  # type: ignore[return-value]

    if doc_type == DocumentType.F1099_DIV:
        return [F1099_DIV_Parser().parse(file)]

    if doc_type == DocumentType.F1099_B:
        return [F1099_B_Parser().parse(file)]

    if doc_type == DocumentType.F1099_R:
        return [F1099_R_Parser().parse(file)]

    if doc_type == DocumentType.SSA_1099:
        return [SSA1099Parser().parse(file)]

    raise UnknownDocumentError(
        f"Could not determine document type for: {file.name}\n"
        "Supported types: W-2, K-1 (1065/1120S), 1099-INT/DIV/B/R, SSA-1099, "
        "Fidelity Consolidated 1099"
    )
