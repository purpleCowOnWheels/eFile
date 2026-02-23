"""pFile CLI — interactive tax filing assistant."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="pfile",
    help="Automate US federal (and NY state) paper tax filing.",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_session(session_id: str) -> "FilingSession":
    from pfile.session.store import SessionStore, SessionNotFoundError
    try:
        return SessionStore().load(session_id)
    except SessionNotFoundError:
        console.print(f"[red]Session not found:[/red] {session_id}")
        raise typer.Exit(1)


def _save(session: "FilingSession") -> None:
    from pfile.session.store import SessionStore
    SessionStore().save(session)


def _run_computation(session: "FilingSession", year: int) -> "FilingSession":
    """Run federal + NY computation, store results on session, return updated session."""
    from pfile.compute.engine import compute_federal_return
    from pfile.compute.state.engine_ny import compute_ny_return
    from pfile.models.session import SessionStatus

    with console.status("Computing federal return…"):
        federal = compute_federal_return(session, year=year)
    session.computed_federal = federal

    if session.needs_ny:
        with console.status("Computing NY IT-201…"):
            ny = compute_ny_return(session, federal, year=year)
        session.computed_ny = ny

    session.status = SessionStatus.COMPUTED
    return session


def _print_federal_summary(session: "FilingSession") -> None:
    f = session.computed_federal
    if not f:
        console.print("[dim]No federal computation yet.[/dim]")
        return

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Line", style="dim")
    t.add_column("Amount", justify="right")
    t.add_row("AGI",                  f"${f.agi:,.2f}")
    t.add_row("Taxable income",       f"${f.taxable_income:,.2f}")
    t.add_row("Total tax",            f"${f.total_tax:,.2f}")
    t.add_row("Total payments",       f"${f.total_payments:,.2f}")
    if f.balance_due > 0:
        t.add_row("[bold red]Balance due[/bold red]", f"[bold red]${f.balance_due:,.2f}[/bold red]")
    else:
        t.add_row("[bold green]Refund[/bold green]", f"[bold green]${f.refund:,.2f}[/bold green]")
    console.print(Panel(t, title="Federal 1040", border_style="blue"))


def _print_ny_summary(session: "FilingSession") -> None:
    ny = session.computed_ny
    if not ny:
        return

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Line", style="dim")
    t.add_column("Amount", justify="right")
    t.add_row("NY AGI",          f"${ny.ny_agi:,.2f}")
    t.add_row("NY taxable",      f"${ny.ny_taxable_income:,.2f}")
    t.add_row("NY total tax",    f"${ny.total_ny_tax:,.2f}")
    t.add_row("NY payments",     f"${ny.total_ny_payments:,.2f}")
    if ny.balance_due > 0:
        t.add_row("[bold red]Balance due[/bold red]", f"[bold red]${ny.balance_due:,.2f}[/bold red]")
    else:
        t.add_row("[bold green]Refund[/bold green]", f"[bold green]${ny.refund:,.2f}[/bold green]")
    console.print(Panel(t, title="NY IT-201", border_style="green"))


# ---------------------------------------------------------------------------
# pfile new
# ---------------------------------------------------------------------------

@app.command()
def new(
    year: int = typer.Option(2025, "--year", "-y", help="Tax year to file for"),
    prior: Path = typer.Option(None, "--prior", "-p", help="Path to prior-year return PDF to prefill from"),
) -> None:
    """Start a new filing session with a guided interview."""
    from pfile.interview.filer import (
        ask_filing_status,
        ask_taxpayer_profile,
        ask_spouse_profile,
        ask_dependents,
    )
    from pfile.interview.documents import ask_add_documents, show_document_summary
    from pfile.interview.overrides import ask_federal_overrides, ask_ny_overrides
    from pfile.models.session import FilingSession, SessionStatus
    from pfile.models.filer import FilingStatus

    console.print()
    console.print(Panel(
        f"[bold green]pFile[/bold green] — Tax Year [bold]{year}[/bold]",
        subtitle="Let's build your filing.",
        border_style="green",
    ))

    # --- Filing status ---
    console.print("\n[bold]Step 1 of 5 — Filing status[/bold]")
    status = ask_filing_status()

    # --- Primary filer ---
    console.print("\n[bold]Step 2 of 5 — Primary filer[/bold]")
    primary = ask_taxpayer_profile("Primary filer")

    # --- Spouse (MFJ / MFS) ---
    spouse = None
    if status in (FilingStatus.MFJ, FilingStatus.MFS):
        console.print("\n[bold]Step 2b — Spouse[/bold]")
        spouse = ask_spouse_profile()

    # --- Dependents ---
    console.print("\n[bold]Step 3 of 5 — Dependents[/bold]")
    dependents = ask_dependents()

    # --- Create session ---
    session = FilingSession(
        tax_year=year,
        filing_status=status,
        primary=primary,
        spouse=spouse,
        dependents=dependents,
    )

    # --- Prior-year prefill ---
    console.print("\n[bold]Step 4 of 5 — Prior-year return[/bold]")
    prior_path = prior
    if prior_path is None:
        import questionary
        has_prior = questionary.confirm(
            "Do you have a prior-year return PDF to prefill carry-forwards from?",
            default=False,
        ).ask()
        if has_prior:
            raw = questionary.path(
                "Path to prior-year return PDF:",
                validate=lambda p: Path(p).exists() or "File not found",
            ).ask()
            prior_path = Path(raw).expanduser().resolve()

    if prior_path and prior_path.exists():
        from pfile.parsers.prior_year import ingest_prior_year_return
        from pfile.session.prefill import prefill_from_prior_year
        from pfile.session.suggest import suggest_missing_documents, format_suggestions

        with console.status("Reading prior-year return…"):
            prior_return = ingest_prior_year_return(prior_path)

        prefill_from_prior_year(session, prior_return)
        console.print(f"  [green]✓[/green] Prefilled carry-forwards from {prior_return.tax_year} return.")

        suggestions = suggest_missing_documents(prior_return, session)
        if suggestions:
            console.print("\n  [bold yellow]Documents you may need (based on prior year):[/bold yellow]")
            urgency_style = {"required": "bold red", "likely": "yellow", "possible": "dim"}
            for s in suggestions:
                style = urgency_style.get(s.urgency, "")
                console.print(f"    [{style}][{s.urgency.upper()}][/] {s.doc_type}")

    # --- Documents ---
    console.print("\n[bold]Step 5 of 5 — Income documents[/bold]")
    ask_add_documents(session, filer="primary")
    if status == FilingStatus.MFJ and spouse:
        add_spouse = __import__("questionary").confirm(
            f"Does {spouse.first_name} have separate documents to add?", default=False
        ).ask()
        if add_spouse:
            ask_add_documents(session, filer="spouse", prompt_label="Spouse's documents")

    # --- Overrides ---
    import questionary
    if questionary.confirm("\nEnter any manual overrides (estimated payments, carryovers, NY credits)?", default=False).ask():
        ask_federal_overrides(session)
        if session.needs_ny:
            ask_ny_overrides(session)

    # --- Compute ---
    _save(session)
    show_document_summary(session)

    if questionary.confirm("\nCompute taxes now?", default=True).ask():
        session = _run_computation(session, year=year)
        _save(session)
        _print_federal_summary(session)
        _print_ny_summary(session)

    console.print(f"\n[green]✓[/green] Session saved: [bold cyan]{session.id}[/bold cyan]")
    console.print(f"  Resume with: [dim]pfile resume {session.id}[/dim]")
    console.print(f"  Add docs with: [dim]pfile add-doc {session.id} <path/to/file.pdf>[/dim]")


# ---------------------------------------------------------------------------
# pfile add-doc
# ---------------------------------------------------------------------------

@app.command("add-doc")
def add_doc(
    session_id: str = typer.Argument(..., help="Session ID"),
    pdf: Path = typer.Argument(..., help="Path to document PDF"),
    filer: str = typer.Option("primary", "--filer", "-f", help="'primary' or 'spouse'"),
    recompute: bool = typer.Option(True, help="Re-run computation after adding"),
) -> None:
    """Parse a PDF and add it to an existing session."""
    from pfile.interview.documents import add_document_from_pdf

    if not pdf.exists():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(1)

    session = _load_session(session_id)
    added = add_document_from_pdf(pdf.expanduser().resolve(), session, filer=filer)

    if not added:
        console.print("[yellow]No documents added.[/yellow]")
        return

    console.print(f"\n[green]✓[/green] Added {len(added)} document(s).")
    _save(session)

    if recompute and session.primary:
        session = _run_computation(session, year=session.tax_year)
        _save(session)
        _print_federal_summary(session)
        _print_ny_summary(session)


# ---------------------------------------------------------------------------
# pfile compute
# ---------------------------------------------------------------------------

@app.command()
def compute(
    session_id: str = typer.Argument(..., help="Session ID"),
    compare_pdf: Optional[Path] = typer.Option(None, "--compare", "-c", help="Prior-year return PDF for side-by-side comparison"),
) -> None:
    """Run (or re-run) tax computation for a session and show results."""
    session = _load_session(session_id)

    if not session.primary:
        console.print("[red]Session has no primary taxpayer. Run [bold]pfile resume[/bold] to complete the interview.[/red]")
        raise typer.Exit(1)

    session = _run_computation(session, year=session.tax_year)
    _save(session)

    _print_federal_summary(session)
    _print_ny_summary(session)

    if compare_pdf:
        _run_compare(session, compare_pdf)


def _run_compare(session: "FilingSession", prior_pdf: Path) -> None:
    from pfile.parsers.prior_year import ingest_prior_year_return
    from pfile.session.compare import print_comparison

    if not prior_pdf.exists():
        console.print(f"[yellow]Prior-year PDF not found: {prior_pdf}[/yellow]")
        return

    with console.status("Parsing prior-year return for comparison…"):
        prior = ingest_prior_year_return(prior_pdf)

    print_comparison(prior, session.computed_federal, session.computed_ny, console)


# ---------------------------------------------------------------------------
# pfile show
# ---------------------------------------------------------------------------

@app.command()
def show(
    session_id: str = typer.Argument(..., help="Session ID"),
    compare_pdf: Optional[Path] = typer.Option(None, "--compare", "-c", help="Prior-year return PDF for comparison"),
) -> None:
    """Display a summary of a filing session and computed results."""
    from pfile.interview.documents import show_document_summary

    session = _load_session(session_id)

    # Header
    name = session.display_name
    console.print(Panel(
        f"[bold]{name}[/bold]  •  Tax Year {session.tax_year}  •  {session.filing_status.value.replace('_', ' ').title()}",
        subtitle=f"ID: {session.id[:8]}…  Status: {session.status.value}",
        border_style="blue",
    ))

    show_document_summary(session)

    if session.computed_federal:
        _print_federal_summary(session)
    if session.computed_ny:
        _print_ny_summary(session)

    if compare_pdf:
        _run_compare(session, compare_pdf)

    if not session.computed_federal:
        console.print("\n[dim]Run [bold]pfile compute {session_id}[/bold] to calculate taxes.[/dim]")


# ---------------------------------------------------------------------------
# pfile resume
# ---------------------------------------------------------------------------

@app.command()
def resume(
    session_id: str = typer.Argument(..., help="Session ID to resume"),
) -> None:
    """Resume an existing session — add documents, update overrides, recompute."""
    import questionary
    from pfile.interview.documents import ask_add_documents, show_document_summary
    from pfile.interview.overrides import ask_federal_overrides, ask_ny_overrides

    session = _load_session(session_id)
    show(session_id)  # display current state

    action = questionary.select(
        "\nWhat would you like to do?",
        choices=[
            "Add more documents",
            "Update overrides (estimated payments, NY credits, etc.)",
            "Re-run computation",
            "Nothing — exit",
        ],
    ).ask()

    if action == "Add more documents":
        ask_add_documents(session, filer="primary")
        if session.is_mfj:
            if questionary.confirm("Add spouse documents too?", default=False).ask():
                ask_add_documents(session, filer="spouse")
        _save(session)
        session = _run_computation(session, year=session.tax_year)
        _save(session)
        _print_federal_summary(session)
        _print_ny_summary(session)

    elif action == "Update overrides (estimated payments, NY credits, etc.)":
        ask_federal_overrides(session)
        if session.needs_ny:
            ask_ny_overrides(session)
        _save(session)
        session = _run_computation(session, year=session.tax_year)
        _save(session)
        _print_federal_summary(session)
        _print_ny_summary(session)

    elif action == "Re-run computation":
        session = _run_computation(session, year=session.tax_year)
        _save(session)
        _print_federal_summary(session)
        _print_ny_summary(session)


# ---------------------------------------------------------------------------
# pfile list
# ---------------------------------------------------------------------------

@app.command("list")
def list_sessions() -> None:
    """List all saved filing sessions."""
    from pfile.session.store import SessionStore

    sessions = SessionStore().list()
    if not sessions:
        console.print("[dim]No sessions found. Start one with [bold]pfile new[/bold].[/dim]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("ID", style="dim", min_width=10)
    t.add_column("Name")
    t.add_column("Year", justify="right")
    t.add_column("Status")
    t.add_column("Updated")

    for s in sessions:
        updated = s.updated_at.strftime("%Y-%m-%d %H:%M")
        status_style = {
            "draft": "yellow",
            "computed": "cyan",
            "complete": "green",
        }.get(s.status.value, "")
        t.add_row(
            s.id[:8] + "…",
            s.display_name,
            str(s.tax_year),
            f"[{status_style}]{s.status.value}[/{status_style}]",
            updated,
        )

    console.print(t)


# ---------------------------------------------------------------------------
# pfile ingest  (prior-year PDF → structured data)
# ---------------------------------------------------------------------------

@app.command()
def ingest(
    pdf: Path = typer.Argument(..., help="Path to a prior-year tax return PDF"),
    year: int = typer.Option(None, "--year", "-y", help="Tax year (inferred from PDF if omitted)"),
    save: bool = typer.Option(True, help="Save extracted data as JSON"),
    output: Path = typer.Option(None, "--output", "-o", help="Output JSON path"),
) -> None:
    """
    Ingest a prior-year tax return PDF, extract structured data, and suggest
    any documents that may be missing for the current year.
    """
    from pfile.parsers.prior_year import ingest_prior_year_return
    from pfile.session.suggest import suggest_missing_documents
    from pfile.models.session import FilingSession
    from pfile.models.filer import FilingStatus

    if not pdf.exists():
        console.print(f"[red]File not found:[/red] {pdf}")
        raise typer.Exit(1)

    console.print(f"[bold green]pFile[/] — ingesting: [cyan]{pdf}[/]")
    with console.status("Extracting text and calling LLM…"):
        prior = ingest_prior_year_return(pdf, tax_year=year)

    console.print(f"\n[green]✓[/] Extracted tax year [bold]{prior.tax_year}[/]\n")

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Label", style="dim")
    t.add_column("Value", justify="right")
    f1040 = prior.form_1040
    t.add_row("AGI",              f"${f1040.line11_agi:,.2f}")
    t.add_row("Total tax",        f"${f1040.line24_total_tax:,.2f}")
    t.add_row("W-2 withheld",     f"${f1040.line25a_w2_withheld:,.2f}")
    t.add_row("Balance due",      f"${f1040.line37_balance_due:,.2f}")
    t.add_row("Refund",           f"${f1040.line35a_refund:,.2f}")
    if f1040.line13_qbi_deduction > 0:
        t.add_row("QBI deduction", f"${f1040.line13_qbi_deduction:,.2f}")
    if prior.had_ny and prior.it201:
        ny = prior.it201
        t.add_row("NY total tax",  f"${ny.total_ny_tax:,.2f}")
        t.add_row("NY withheld",   f"${ny.ny_withheld:,.2f}")
        t.add_row("NY refund",     f"${ny.ny_refund:,.2f}")
    console.print(t)

    # Missing-document suggestions against an empty session
    blank = FilingSession(tax_year=prior.tax_year + 1, filing_status=FilingStatus.MFJ)
    suggestions = suggest_missing_documents(prior, blank)

    if suggestions:
        console.print()
        urgency_style = {"required": "bold red", "likely": "yellow", "possible": "dim"}
        console.print("[bold]Documents you likely need for the current year:[/bold]")
        for s in suggestions:
            style = urgency_style.get(s.urgency, "")
            console.print(f"  [{style}][{s.urgency.upper()}][/] [bold]{s.doc_type}[/]")
            console.print(f"         {s.reason}")

    if prior.notes:
        console.print("\n[yellow]Parser notes:[/yellow]")
        for note in prior.notes:
            console.print(f"  • {note}")

    if save:
        out = output or pdf.with_suffix(".prior.json")
        out.write_text(prior.model_dump_json(indent=2))
        console.print(f"\n[green]✓[/] Saved to [cyan]{out}[/]")


# ---------------------------------------------------------------------------
# pfile generate
# ---------------------------------------------------------------------------

@app.command()
def generate(
    session_id: str = typer.Argument(..., help="Session ID"),
    out_dir: Optional[Path] = typer.Option(None, "--out", "-o", help="Output directory (default: ~/Desktop)"),
) -> None:
    """Generate the filing package ZIP (cover sheet, data sheets, vouchers)."""
    from pfile.output.package import generate_package

    session = _load_session(session_id)

    if not session.computed_federal:
        console.print("[yellow]No computed results found. Running compute first…[/yellow]")
        session = _run_computation(session, year=session.tax_year)
        _save(session)

    if not session.computed_federal:
        console.print("[red]Computation failed — cannot generate package.[/red]")
        raise typer.Exit(1)

    output_dir = out_dir or Path.home() / "Desktop"
    output_dir = output_dir.expanduser().resolve()

    with console.status("Building filing package…"):
        zip_path = generate_package(
            session=session,
            federal=session.computed_federal,
            ny=session.computed_ny,
            output_dir=output_dir,
        )

    federal = session.computed_federal
    ny = session.computed_ny

    console.print()
    console.print(Panel(
        f"[bold green]Filing package created![/bold green]\n\n"
        f"  [cyan]{zip_path}[/cyan]",
        title="pFile Generate",
        border_style="green",
    ))

    # Quick summary of what's inside
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("cover_sheet.pdf", "Filing summary, mailing addresses, checklist")
    table.add_row("1040_line_items.pdf", "Form 1040 (and IT-201 on page 2) line items")
    if federal.balance_due > 0:
        table.add_row("1040v_voucher.pdf", f"Federal payment voucher — ${federal.balance_due:,.2f}")
    if ny and ny.balance_due > 0:
        table.add_row("it201v_voucher.pdf", f"NY payment voucher — ${ny.balance_due:,.2f}")
    table.add_row("README.txt", "Instructions and notes")
    console.print(table)

    if federal.balance_due > 0 or (ny and ny.balance_due > 0):
        console.print()
        console.print("[bold yellow]Payment due April 15 — see cover_sheet.pdf for mailing details.[/bold yellow]")


if __name__ == "__main__":
    app()
