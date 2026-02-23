"""Assemble the full filing package as a ZIP archive."""

from __future__ import annotations

import importlib.resources
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from pfile.models.forms import ComputedFederalReturn, ComputedNYReturn
from pfile.models.session import FilingSession
from pfile.output import cover_sheet, data_sheet, vouchers
from pfile.output.forms import filler


_FORMS_DATA = Path(__file__).parent.parent.parent.parent / "data" / "forms"


def generate_package(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None,
    output_dir: Path,
    fill_forms: bool = False,
) -> Path:
    """
    Build the filing package ZIP and return its path.

    The archive contains:
        cover_sheet.pdf         — filing instructions, mailing addresses, checklist
        1040_line_items.pdf     — Form 1040 line-by-line data sheet
        it201_line_items.pdf    — NY IT-201 data sheet (if NY return present)
        1040v_voucher.pdf       — Form 1040-V payment voucher (if balance due)
        it201v_voucher.pdf      — NY IT-201-V voucher (if NY balance due)
        f1040_filled.pdf        — Filled IRS Form 1040 (if fill_forms=True)
        it201_filled.pdf        — Filled NY IT-201 (if fill_forms=True and NY return)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_name(session)
    zip_path = output_dir / f"pfile_{session.tax_year}_{safe_name}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        files: list[tuple[Path, str]] = []

        # Cover sheet
        cs = tmp_path / "cover_sheet.pdf"
        cover_sheet.generate(session, federal, ny, cs)
        files.append((cs, "cover_sheet.pdf"))

        # Data sheets
        ds = tmp_path / "1040_line_items.pdf"
        data_sheet.generate(session, federal, ny, ds)
        files.append((ds, "1040_line_items.pdf"))

        # Payment vouchers
        if federal.balance_due > 0:
            v1 = tmp_path / "1040v_voucher.pdf"
            vouchers.generate_1040v(session, federal.balance_due, v1)
            files.append((v1, "1040v_voucher.pdf"))

        if ny and ny.balance_due > 0:
            v2 = tmp_path / "it201v_voucher.pdf"
            vouchers.generate_it201v(session, ny.balance_due, v2)
            files.append((v2, "it201v_voucher.pdf"))

        # Filled official forms (Phase 2)
        if fill_forms:
            year = str(session.tax_year)
            f1040_tmpl = _FORMS_DATA / "federal" / year / "f1040.pdf"
            it201_tmpl = _FORMS_DATA / "ny" / year / "it201_fill_in.pdf"

            if f1040_tmpl.exists():
                f1040_out = tmp_path / "f1040_filled.pdf"
                filler.fill_1040(session, federal, f1040_tmpl, f1040_out)
                files.append((f1040_out, "f1040_filled.pdf"))

            if ny and it201_tmpl.exists():
                it201_out = tmp_path / "it201_filled.pdf"
                filler.fill_it201(session, federal, ny, it201_tmpl, it201_out)
                files.append((it201_out, "it201_filled.pdf"))

        # README
        readme = tmp_path / "README.txt"
        readme.write_text(_readme_text(session, federal, ny, fill_forms=fill_forms))
        files.append((readme, "README.txt"))

        # Pack into ZIP
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src, arc_name in files:
                zf.write(src, arc_name)

    return zip_path


def _safe_name(session: FilingSession) -> str:
    primary = session.primary
    if primary:
        last = primary.last_name.replace(" ", "_").lower()
        return last
    return "taxpayer"


def _readme_text(
    session: FilingSession,
    federal: ComputedFederalReturn,
    ny: ComputedNYReturn | None,
    fill_forms: bool = False,
) -> str:
    today = date.today().strftime("%B %d, %Y")
    lines = [
        "pFile — Tax Filing Package",
        "=" * 40,
        f"Generated: {today}",
        f"Taxpayer:  {session.display_name}",
        f"Tax Year:  {session.tax_year}",
        "",
        "FILES IN THIS PACKAGE",
        "-" * 40,
        "cover_sheet.pdf      — Start here. Filing summary, mailing addresses, checklist.",
        "1040_line_items.pdf  — Federal Form 1040 and schedule line-item data.",
    ]
    if ny:
        lines.append("  (NY IT-201 data is on page 2 of 1040_line_items.pdf)")
    if federal.balance_due > 0:
        lines.append(f"1040v_voucher.pdf    — Form 1040-V. Enclose with federal payment of ${federal.balance_due:,.2f}.")
    if ny and ny.balance_due > 0:
        lines.append(f"it201v_voucher.pdf   — Form IT-201-V. Enclose with NY payment of ${ny.balance_due:,.2f}.")
    if fill_forms:
        lines.append("f1040_filled.pdf     — IRS Form 1040 filled with computed values.")
        if ny:
            lines.append("it201_filled.pdf     — NY IT-201 filled with computed values.")
    lines += [
        "",
        "IMPORTANT NOTES",
        "-" * 40,
    ]
    if fill_forms:
        lines += [
            "• Filled forms (f1040_filled.pdf, it201_filled.pdf) are pre-populated with",
            "  computed values. VERIFY every line before signing and mailing.",
        ]
    else:
        lines += [
            "• pFile generated data summaries. Transfer line items to the official IRS/DTF",
            "  forms before mailing. Use --fill-forms to auto-populate official PDFs.",
        ]
    lines += [
        "• Sign and date all forms before mailing.",
        "• Keep a copy of everything for your records.",
        "• Mail via USPS Certified Mail with Return Receipt.",
        "",
        "pFile is open-source software. Always verify computed amounts against",
        "your original source documents and consult a tax professional if unsure.",
    ]
    return "\n".join(lines)
