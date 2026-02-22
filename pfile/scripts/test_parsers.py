"""
Quick smoke-test of all parsers against the real test documents.
Run from the pfile/ directory:

    poetry run python scripts/test_parsers.py

Requires OPENAI_API_KEY to be set for K-1 parsing.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
DOCS = Path(__file__).parent.parent / "data" / "test_docs"


def show_result(title: str, data: dict, confidence: dict | None = None) -> None:
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    if confidence:
        table.add_column("Confidence", justify="right")

    for k, v in data.items():
        if v in (None, 0, "0", {}, []):
            continue
        conf_str = ""
        if confidence:
            score = confidence.get(k, 1.0)
            color = "green" if score >= 0.8 else "yellow" if score >= 0.5 else "red"
            conf_str = f"[{color}]{score:.2f}[/{color}]"
        table.add_row(str(k), str(v), conf_str if confidence else "")

    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))


# ---------------------------------------------------------------------------
# W-2 tests (deterministic — no API key needed)
# ---------------------------------------------------------------------------

def test_w2(filename: str, label: str) -> None:
    from pfile.parsers.w2 import W2Parser

    path = DOCS / filename
    if not path.exists():
        console.print(f"[yellow]SKIP[/yellow] {filename} not found")
        return

    console.print(f"\n[bold green]Parsing W-2:[/bold green] {filename}")
    parser = W2Parser()
    result = parser.parse(path)

    data = {
        "employer": result.employer.name,
        "ein": result.employer.ein,
        "box1_wages": result.box1_wages,
        "box2_federal_withheld": result.box2_federal_withheld,
        "box3_ss_wages": result.box3_ss_wages,
        "box4_ss_withheld": result.box4_ss_withheld,
        "box5_medicare_wages": result.box5_medicare_wages,
        "box6_medicare_withheld": result.box6_medicare_withheld,
        "box10_dependent_care": result.box10_dependent_care,
        "box12": [(e.code, e.amount) for e in result.box12],
        "box13_retirement_plan": result.box13_retirement_plan,
        "box14": result.box14,
        "box15_state": result.box15_state,
        "box16_state_wages": result.box16_state_wages,
        "box17_state_withheld": result.box17_state_withheld,
    }
    show_result(label, data, result.confidence.scores)

    low = result.confidence.low_confidence_fields()
    if low:
        console.print(f"  [yellow]⚠ Low confidence fields:[/yellow] {', '.join(low)}")
    else:
        console.print("  [green]✓ All fields high confidence[/green]")


# ---------------------------------------------------------------------------
# K-1 test (LLM-assisted — needs OPENAI_API_KEY)
# ---------------------------------------------------------------------------

def test_k1(filename: str, label: str) -> None:
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        console.print(f"[yellow]SKIP K-1[/yellow] {filename} — OPENAI_API_KEY not set")
        return

    from pfile.parsers.k1 import K1Parser

    path = DOCS / filename
    if not path.exists():
        console.print(f"[yellow]SKIP[/yellow] {filename} not found")
        return

    console.print(f"\n[bold green]Parsing K-1:[/bold green] {filename}")
    parser = K1Parser()
    result = parser.parse(path)

    # Show entity + key income fields
    if hasattr(result, "corporation"):
        entity = result.corporation
        entity_label = "Corporation"
    else:
        entity = result.partnership
        entity_label = "Partnership"

    data = {
        f"{entity_label}_name": entity.name,
        f"{entity_label}_ein": entity.ein,
        "tax_year": result.tax_year,
        "ownership_or_share_pct": getattr(result, "ownership_pct", None) or getattr(result, "profit_share_pct", None),
        "box1_ordinary_income": result.box1_ordinary_income,
        "box2_net_rental_re_income": result.box2_net_rental_re_income,
    }

    # Add any non-zero deductions / credits / other info
    for attr in ("box12_other_deductions", "box13_credits", "box16_basis_items", "box17_other_info",
                 "box20_other_info", "box16_tax_exempt_income"):
        val = getattr(result, attr, {})
        if val:
            data[attr] = val

    show_result(label, data, result.confidence.scores)

    low = result.confidence.low_confidence_fields()
    if low:
        console.print(f"  [yellow]⚠ Low confidence fields:[/yellow] {', '.join(low)}")
    else:
        console.print("  [green]✓ All fields high confidence[/green]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def test_dispatch(filename: str, label: str) -> None:
    """Test the dispatcher against a file and show all parsed documents."""
    from pfile.parsers.dispatcher import parse, UnknownDocumentError

    path = DOCS / filename
    if not path.exists():
        console.print(f"[yellow]SKIP[/yellow] {filename} not found")
        return

    import os
    if not os.environ.get("OPENAI_API_KEY"):
        # Check if LLM is needed for this file
        from pfile.parsers.base import BaseParser
        text = BaseParser.extract_text(path)  # type: ignore
        from pfile.parsers.dispatcher import detect, DocumentType
        doc_type = detect(text)
        if doc_type in (DocumentType.K1_1120S, DocumentType.K1_1065, DocumentType.F1099_R):
            console.print(f"[yellow]SKIP[/yellow] {filename} — needs OPENAI_API_KEY ({doc_type})")
            return

    console.print(f"\n[bold green]Dispatching:[/bold green] {filename}")
    try:
        docs = parse(path)
        for doc in docs:
            dtype = type(doc).__name__
            # Build a display dict of non-zero fields
            data = {
                k: v for k, v in doc.model_dump().items()
                if v and v != 0 and v != [] and v != {} and k not in ("source_file", "confidence")
            }
            conf = getattr(doc, "confidence", None)
            show_result(f"{label} → {dtype}", data, conf.scores if conf else None)
            low = conf.low_confidence_fields() if conf else []
            if low:
                console.print(f"  [yellow]⚠ Low confidence:[/yellow] {', '.join(low)}")
    except Exception as e:
        console.print(f"  [red]ERROR:[/red] {e}")


if __name__ == "__main__":
    console.print("\n[bold]pFile — Parser Test Suite[/bold]\n")

    # W-2s (deterministic)
    test_w2("Daniel_Costanza_2024_W2.pdf", "W-2: Daniel Costanza (Yieldstreet)")
    test_w2("2024-W2-Becca.pdf", "W-2: Rebecca Licht (BKRCO)")

    # K-1 (LLM)
    test_k1("2024 1120S BKRCO LLC.pdf", "K-1 (1120S): BKRCO LLC — Rebecca Licht")

    # 1099s via dispatcher
    test_dispatch("ally-1099-INT.pdf", "1099-INT: Ally (Daniel)")
    test_dispatch("Becca ally 1099 int.pdf", "1099-INT: Ally (Becca)")
    test_dispatch(
        "167713_Daniel_Costanza_1099-INT_Portland Multi-Family Debt_2024.pdf",
        "1099-INT: Portland Multi-Family Debt",
    )
    test_dispatch(
        "D Costanza Yieldstreet Alternative Income Fund 2024 1099-DIV.pdf",
        "1099-DIV: Yieldstreet (Daniel)",
    )
    test_dispatch(
        "2024-Individual-2503-Consolidated-Form-1099.pdf",
        "Fidelity Consolidated: Rebecca (individual)",
    )
    test_dispatch(
        "2024-Joint-WROS-6709-Consolidated-Form-1099 (1).pdf",
        "Fidelity Consolidated: Joint WROS",
    )
