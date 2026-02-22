"""pFile CLI — entry point for all commands."""

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="pfile",
    help="Automate US federal tax preparation and paper filing.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def ingest(
    pdf: Path = typer.Argument(..., help="Path to a prior-year tax return PDF"),
    year: int = typer.Option(None, "--year", "-y", help="Tax year (inferred from filename if omitted)"),
    session_id: str = typer.Option(None, "--session", "-s", help="Session ID to check against for missing docs"),
    save: bool = typer.Option(True, "--save/--no-save", help="Save extracted data as JSON"),
    output: Path = typer.Option(None, "--output", "-o", help="Output JSON path (default: <pdf>.prior.json)"),
) -> None:
    """
    Ingest a prior-year tax return PDF, extract structured data, and suggest
    any documents that may be missing for the current year.
    """
    from pfile.parsers.prior_year import ingest_prior_year_return
    from pfile.session.suggest import suggest_missing_documents, format_suggestions
    from rich.table import Table
    from rich.panel import Panel

    console.print(f"[bold green]pFile[/] — ingesting prior year return: [cyan]{pdf}[/]")
    if not pdf.exists():
        console.print(f"[red]File not found: {pdf}[/]")
        raise typer.Exit(1)

    with console.status("Extracting text and calling LLM…"):
        prior = ingest_prior_year_return(pdf, tax_year=year)

    console.print(f"\n[green]✓[/] Extracted tax year [bold]{prior.tax_year}[/] return\n")

    # Summary table
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Label", style="dim")
    t.add_column("Value", justify="right")
    f = prior.form_1040
    t.add_row("AGI",          f"${f.line11_agi:,.2f}")
    t.add_row("Total tax",    f"${f.line24_total_tax:,.2f}")
    t.add_row("W-2 withheld", f"${f.line25a_w2_withheld:,.2f}")
    t.add_row("Balance due",  f"${f.line37_balance_due:,.2f}")
    t.add_row("Refund",       f"${f.line35a_refund:,.2f}")
    if f.line13_qbi_deduction > 0:
        t.add_row("QBI deduction", f"${f.line13_qbi_deduction:,.2f}")
    if prior.had_ny:
        ny = prior.it201
        t.add_row("NY total tax",  f"${ny.total_ny_tax:,.2f}")
        t.add_row("NY withheld",   f"${ny.ny_withheld:,.2f}")
        t.add_row("NY refund",     f"${ny.ny_refund:,.2f}")
    console.print(t)

    # Missing-document suggestions (uses an empty session if no session_id given)
    if session_id:
        from pfile.session.store import SessionStore
        store = SessionStore()
        if store.exists(session_id):
            session = store.load(session_id)
            suggestions = suggest_missing_documents(prior, session)
        else:
            console.print(f"[yellow]Session {session_id!r} not found — showing suggestions for a blank session.[/]")
            suggestions = _suggest_from_prior_alone(prior, prior.tax_year + 1)
    else:
        suggestions = _suggest_from_prior_alone(prior, prior.tax_year + 1)

    if suggestions:
        console.print()
        urgency_style = {"required": "bold red", "likely": "yellow", "possible": "dim"}
        for s in suggestions:
            style = urgency_style.get(s.urgency, "")
            console.print(f"  [{style}][{s.urgency.upper()}][/] [bold]{s.doc_type}[/]")
            console.print(f"         {s.reason}")
    else:
        console.print("\n[green]✓ No missing documents detected.[/]")

    if prior.notes:
        console.print("\n[yellow]Parser notes:[/]")
        for note in prior.notes:
            console.print(f"  • {note}")

    if save:
        out = output or pdf.with_suffix(".prior.json")
        out.write_text(prior.model_dump_json(indent=2))
        console.print(f"\n[green]✓[/] Saved to [cyan]{out}[/]")


def _suggest_from_prior_alone(
    prior: "PriorYearReturn", current_year: int
) -> list:
    """
    When no current session exists, return suggestions based purely on what
    non-zero income items appeared in the prior year.  We build a blank
    FilingSession so suggest_missing_documents sees everything as absent.
    """
    from pfile.session.suggest import suggest_missing_documents
    from pfile.models.session import FilingSession
    from pfile.models.filer import FilingStatus

    blank = FilingSession(tax_year=current_year, filing_status=FilingStatus.MFJ)
    return suggest_missing_documents(prior, blank)


@app.command()
def new() -> None:
    """Start a new filing session."""
    console.print("[bold green]pFile[/] — starting new session...")
    raise NotImplementedError("Coming soon")


@app.command()
def resume(session_id: str = typer.Argument(..., help="Session ID to resume")) -> None:
    """Resume an existing filing session."""
    console.print(f"[bold green]pFile[/] — resuming session [cyan]{session_id}[/]...")
    raise NotImplementedError("Coming soon")


@app.command("list")
def list_sessions() -> None:
    """List all saved filing sessions."""
    console.print("[bold green]pFile[/] — sessions:")
    raise NotImplementedError("Coming soon")


@app.command()
def generate(session_id: str = typer.Argument(..., help="Session ID to generate output for")) -> None:
    """Generate the output filing package for a completed session."""
    console.print(f"[bold green]pFile[/] — generating package for [cyan]{session_id}[/]...")
    raise NotImplementedError("Coming soon")


@app.command()
def show(session_id: str = typer.Argument(..., help="Session ID to display")) -> None:
    """Show a summary of a filing session."""
    console.print(f"[bold green]pFile[/] — session [cyan]{session_id}[/]:")
    raise NotImplementedError("Coming soon")


if __name__ == "__main__":
    app()
