"""Interactive prompts for collecting filer profile information."""

from __future__ import annotations

import re
from datetime import date, datetime

import questionary
from rich.console import Console

from pfile.models.filer import (
    Address,
    DependentProfile,
    FilingStatus,
    NYResidencyInfo,
    SpouseProfile,
    TaxpayerProfile,
)

console = Console()

_SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def _validate_ssn(val: str) -> bool | str:
    if _SSN_RE.match(val.strip()):
        return True
    return "Enter SSN in XXX-XX-XXXX format"


def _validate_dob(val: str) -> bool | str:
    try:
        datetime.strptime(val.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return "Enter date as YYYY-MM-DD"


def _validate_zip(val: str) -> bool | str:
    if _ZIP_RE.match(val.strip()):
        return True
    return "Enter a valid ZIP code (e.g. 10522 or 10522-1234)"


def _validate_state(val: str) -> bool | str:
    if _STATE_RE.match(val.strip().upper()):
        return True
    return "Enter a 2-letter state abbreviation (e.g. NY)"


def _validate_nonempty(val: str) -> bool | str:
    return True if val.strip() else "This field is required"


def ask_filing_status() -> FilingStatus:
    choices = {
        "Single": FilingStatus.SINGLE,
        "Married filing jointly (MFJ)": FilingStatus.MFJ,
        "Married filing separately (MFS)": FilingStatus.MFS,
        "Head of household (HOH)": FilingStatus.HOH,
        "Qualifying surviving spouse (QSS)": FilingStatus.QSS,
    }
    answer = questionary.select(
        "Filing status:",
        choices=list(choices.keys()),
    ).ask()
    return choices[answer]


def _ask_address() -> Address:
    console.print("\n[dim]Mailing address[/dim]")
    street = questionary.text("  Street:", validate=_validate_nonempty).ask()
    apt = questionary.text("  Apt / unit (leave blank if none):").ask()
    city = questionary.text("  City:", validate=_validate_nonempty).ask()
    state = questionary.text("  State (2-letter):", validate=_validate_state).ask()
    zip_code = questionary.text("  ZIP:", validate=_validate_zip).ask()
    return Address(
        street=street.strip(),
        apt=apt.strip() or None,
        city=city.strip(),
        state=state.strip().upper(),
        zip_code=zip_code.strip(),
    )


def _ask_ny_residency() -> NYResidencyInfo | None:
    is_ny = questionary.confirm(
        "Is the primary filer a New York State resident?", default=True
    ).ask()
    if not is_ny:
        return None

    full_year = questionary.confirm(
        "Full-year NY resident (lived in NY all of 2025)?", default=True
    ).ask()
    county = questionary.text(
        "County of residence (e.g. Westchester, Kings):",
        validate=_validate_nonempty,
    ).ask()
    nyc = questionary.confirm(
        "NYC resident (Manhattan, Brooklyn, Queens, Bronx, or Staten Island)?",
        default=False,
    ).ask()
    yonkers = False
    if not nyc:
        yonkers = questionary.confirm("Yonkers resident?", default=False).ask()

    return NYResidencyInfo(
        full_year_resident=full_year,
        county=county.strip(),
        nyc_resident=nyc,
        yonkers_resident=yonkers,
    )


def ask_taxpayer_profile(label: str = "Primary filer") -> TaxpayerProfile:
    console.print(f"\n[bold]{label}[/bold]")
    first = questionary.text("  First name:", validate=_validate_nonempty).ask()
    last = questionary.text("  Last name:", validate=_validate_nonempty).ask()
    ssn = questionary.text(
        "  SSN (XXX-XX-XXXX):", validate=_validate_ssn
    ).ask()
    dob_str = questionary.text(
        "  Date of birth (YYYY-MM-DD):", validate=_validate_dob
    ).ask()
    dob = datetime.strptime(dob_str.strip(), "%Y-%m-%d").date()
    occupation = questionary.text("  Occupation (optional, press Enter to skip):").ask()

    address = _ask_address()
    ny_residency = _ask_ny_residency()

    return TaxpayerProfile(
        first_name=first.strip(),
        last_name=last.strip(),
        ssn=ssn.strip(),
        dob=dob,
        occupation=occupation.strip() or None,
        address=address,
        ny_residency=ny_residency,
    )


def ask_spouse_profile() -> SpouseProfile:
    console.print("\n[bold]Spouse[/bold]")
    first = questionary.text("  First name:", validate=_validate_nonempty).ask()
    last = questionary.text("  Last name:", validate=_validate_nonempty).ask()
    ssn = questionary.text(
        "  SSN (XXX-XX-XXXX):", validate=_validate_ssn
    ).ask()
    dob_str = questionary.text(
        "  Date of birth (YYYY-MM-DD):", validate=_validate_dob
    ).ask()
    dob = datetime.strptime(dob_str.strip(), "%Y-%m-%d").date()
    occupation = questionary.text("  Occupation (optional):").ask()

    return SpouseProfile(
        first_name=first.strip(),
        last_name=last.strip(),
        ssn=ssn.strip(),
        dob=dob,
        occupation=occupation.strip() or None,
    )


def _ask_one_dependent(index: int) -> DependentProfile:
    console.print(f"\n[bold]Dependent {index}[/bold]")
    first = questionary.text("  First name:", validate=_validate_nonempty).ask()
    last = questionary.text("  Last name:", validate=_validate_nonempty).ask()
    ssn = questionary.text(
        "  SSN or ITIN (XXX-XX-XXXX):", validate=_validate_ssn
    ).ask()
    dob_str = questionary.text(
        "  Date of birth (YYYY-MM-DD):", validate=_validate_dob
    ).ask()
    dob = datetime.strptime(dob_str.strip(), "%Y-%m-%d").date()
    relationship = questionary.select(
        "  Relationship:",
        choices=["child", "stepchild", "foster child", "sibling", "grandchild", "other"],
    ).ask()

    # Auto-determine CTC eligibility: under 17 at Dec 31 of the tax year
    # (caller can override via the session if needed)
    this_year = date.today().year
    ctc_eligible = dob > date(this_year - 17, 12, 31)

    return DependentProfile(
        first_name=first.strip(),
        last_name=last.strip(),
        ssn=ssn.strip(),
        dob=dob,
        relationship=relationship,
        child_tax_credit_eligible=ctc_eligible,
    )


def ask_dependents() -> list[DependentProfile]:
    has_deps = questionary.confirm(
        "Do you have any dependents to claim?", default=False
    ).ask()
    if not has_deps:
        return []

    deps: list[DependentProfile] = []
    index = 1
    while True:
        deps.append(_ask_one_dependent(index))
        index += 1
        more = questionary.confirm("Add another dependent?", default=False).ask()
        if not more:
            break
    return deps
