"""Interactive prompts for adding and reviewing parsed documents."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

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
from pfile.models.session import DocumentSet, FilingSession

console = Console()


# ---------------------------------------------------------------------------
# Document display helpers
# ---------------------------------------------------------------------------

def _fmt(d: Decimal | None) -> str:
    if d is None:
        return "—"
    return f"${d:,.2f}"


def _show_w2(doc: W2) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Field", style="dim")
    t.add_column("Value")
    t.add_row("Employer", doc.employer.name)
    t.add_row("Box 1  Wages", _fmt(doc.box1_wages))
    t.add_row("Box 2  Federal withheld", _fmt(doc.box2_federal_withheld))
    t.add_row("Box 16 NY wages", _fmt(doc.box16_state_wages))
    t.add_row("Box 17 NY withheld", _fmt(doc.box17_state_withheld))
    if doc.box12_codes:
        for code, val in doc.box12_codes.items():
            t.add_row(f"Box 12 {code}", _fmt(val))
    console.print(t)


def _show_1099_int(doc: F1099_INT) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Field", style="dim")
    t.add_column("Value")
    t.add_row("Payer", doc.payer.name)
    t.add_row("Box 1  Interest income", _fmt(doc.box1_interest_income))
    t.add_row("Box 4  Federal withheld", _fmt(doc.box4_federal_withheld))
    t.add_row("Held in IRA?", "Yes" if doc.held_in_ira else "No")
    console.print(t)


def _show_1099_div(doc: F1099_DIV) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Field", style="dim")
    t.add_column("Value")
    t.add_row("Payer", doc.payer.name)
    t.add_row("Box 1a Ordinary dividends", _fmt(doc.box1a_ordinary_dividends))
    t.add_row("Box 1b Qualified dividends", _fmt(doc.box1b_qualified_dividends))
    t.add_row("Box 2a Total capital gain", _fmt(doc.box2a_total_capital_gain))
    t.add_row("Box 4  Federal withheld", _fmt(doc.box4_federal_withheld))
    t.add_row("Held in IRA?", "Yes" if doc.held_in_ira else "No")
    console.print(t)


def _show_k1(doc: K1_1120S | K1_1065) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Field", style="dim")
    t.add_column("Value")
    t.add_row("Entity", doc.entity_name)
    t.add_row("Type", "S-Corp (1120-S)" if isinstance(doc, K1_1120S) else "Partnership (1065)")
    t.add_row("Box 1  Ordinary income", _fmt(doc.box1_ordinary_income))
    if hasattr(doc, "box8_net_stcg"):
        t.add_row("Box 8  Net STCG", _fmt(doc.box8_net_stcg))  # type: ignore[attr-defined]
    if hasattr(doc, "box8a_net_ltcg"):
        t.add_row("Box 8a Net LTCG", _fmt(doc.box8a_net_ltcg))  # type: ignore[attr-defined]
    console.print(t)


def _show_document(doc: AnyDocument) -> None:
    if isinstance(doc, W2):
        _show_w2(doc)
    elif isinstance(doc, F1099_INT):
        _show_1099_int(doc)
    elif isinstance(doc, F1099_DIV):
        _show_1099_div(doc)
    elif isinstance(doc, (K1_1120S, K1_1065)):
        _show_k1(doc)
    else:
        console.print(f"  [dim]{type(doc).__name__} parsed successfully.[/dim]")


# ---------------------------------------------------------------------------
# IRA / retirement account flag prompt
# ---------------------------------------------------------------------------

def _maybe_ask_ira(doc: AnyDocument) -> AnyDocument:
    """For 1099-INT/DIV/B, ask if the account is an IRA to exclude from income."""
    if not isinstance(doc, (F1099_INT, F1099_DIV, F1099_B)):
        return doc
    payer = getattr(doc, "payer", None)
    payer_name = payer.name if payer else "this account"
    is_ira = questionary.confirm(
        f"  Is '{payer_name}' an IRA, 401(k), or other retirement account "
        "(income not taxable)?",
        default=False,
    ).ask()
    if is_ira:
        doc = doc.model_copy(update={"held_in_ira": True})
    return doc


# ---------------------------------------------------------------------------
# Parse and add a single PDF to a session
# ---------------------------------------------------------------------------

def add_document_from_pdf(
    pdf_path: Path,
    session: FilingSession,
    filer: str = "primary",
) -> list[AnyDocument]:
    """
    Parse a PDF, display extracted fields for review, and add to the session.

    Returns the list of documents parsed (a single consolidated 1099 may
    yield multiple documents).
    """
    from pfile.parsers.dispatcher import detect, parse, DocumentType

    console.print(f"\n  [cyan]Parsing[/cyan] {pdf_path.name}…")

    doc_type = detect(pdf_path)
    console.print(f"  Detected: [bold]{doc_type.value}[/bold]")

    documents = parse(pdf_path)

    doc_set: DocumentSet = (
        session.primary_documents if filer == "primary" else session.spouse_documents
    )

    added: list[AnyDocument] = []
    for doc in documents:
        console.print()
        _show_document(doc)
        doc = _maybe_ask_ira(doc)

        # Check confidence and warn on low-confidence fields
        if hasattr(doc, "confidence"):
            low = doc.confidence.low_confidence_fields(threshold=0.75)
            if low:
                console.print(
                    f"  [yellow]⚠ Low-confidence fields: {', '.join(low)}[/yellow]"
                )
                console.print(
                    "  [dim]Review these values against the original document.[/dim]"
                )

        if questionary.confirm("  Add this document to the session?", default=True).ask():
            _add_to_doc_set(doc_set, doc)
            added.append(doc)
        else:
            console.print("  [dim]Skipped.[/dim]")

    return added


def _add_to_doc_set(doc_set: DocumentSet, doc: AnyDocument) -> None:
    """Append a document to the correct list in a DocumentSet."""
    if isinstance(doc, W2):
        doc_set.w2s.append(doc)
    elif isinstance(doc, K1_1120S):
        doc_set.k1_1120ss.append(doc)
    elif isinstance(doc, K1_1065):
        doc_set.k1_1065s.append(doc)
    elif isinstance(doc, F1099_INT):
        doc_set.f1099_ints.append(doc)
    elif isinstance(doc, F1099_DIV):
        doc_set.f1099_divs.append(doc)
    elif isinstance(doc, F1099_B):
        doc_set.f1099_bs.append(doc)
    elif isinstance(doc, F1099_R):
        doc_set.f1099_rs.append(doc)
    elif isinstance(doc, SSA_1099):
        doc_set.ssa_1099s.append(doc)
    else:
        console.print(f"  [yellow]Unknown document type {type(doc).__name__} — skipped[/yellow]")


# ---------------------------------------------------------------------------
# Document collection loop
# ---------------------------------------------------------------------------

def ask_add_documents(
    session: FilingSession,
    filer: str = "primary",
    prompt_label: str = "Add income documents",
) -> None:
    """
    Interactively loop adding documents (PDFs) to the session until the user
    is done.
    """
    label = (
        f"{session.primary.first_name}'s" if filer == "primary" and session.primary
        else "Spouse's" if filer == "spouse"
        else "Your"
    )
    console.print(f"\n[bold]{prompt_label}[/bold] — {label} documents")
    console.print(
        "[dim]You can add W-2s, K-1s, 1099-INT/DIV/B/R, and SSA-1099 PDFs.[/dim]"
    )

    while True:
        add_more = questionary.confirm("Add a document?", default=True).ask()
        if not add_more:
            break

        raw = questionary.path(
            "  Path to PDF:",
            validate=lambda p: Path(p).exists() or "File not found",
        ).ask()
        pdf = Path(raw).expanduser().resolve()

        try:
            add_document_from_pdf(pdf, session, filer=filer)
        except Exception as exc:
            console.print(f"  [red]Error parsing {pdf.name}: {exc}[/red]")
            console.print("  [dim]You can try again or skip this document.[/dim]")


def show_document_summary(session: FilingSession) -> None:
    """Print a brief summary of documents currently in the session."""
    ds = session.primary_documents
    ss = session.spouse_documents if session.is_mfj else None

    t = Table(title="Documents in session", show_header=True, header_style="bold")
    t.add_column("Type")
    t.add_column("Primary", justify="right")
    if ss:
        t.add_column("Spouse", justify="right")

    def _count(doc_set: DocumentSet | None, attr: str) -> str:
        if doc_set is None:
            return "—"
        items = getattr(doc_set, attr, [])
        return str(len(items)) if items else "—"

    rows = [
        ("W-2", "w2s"),
        ("K-1 (1120-S)", "k1_1120ss"),
        ("K-1 (1065)", "k1_1065s"),
        ("1099-INT", "f1099_ints"),
        ("1099-DIV", "f1099_divs"),
        ("1099-B", "f1099_bs"),
        ("1099-R", "f1099_rs"),
        ("SSA-1099", "ssa_1099s"),
    ]
    for label, attr in rows:
        p = _count(ds, attr)
        row = [label, p]
        if ss:
            row.append(_count(ss, attr))
        if p != "—" or (ss and _count(ss, attr) != "—"):
            t.add_row(*row)

    console.print(t)
