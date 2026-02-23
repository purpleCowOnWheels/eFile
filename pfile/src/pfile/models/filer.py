"""Taxpayer and filer profile models."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class FilingStatus(StrEnum):
    SINGLE = "single"
    MFJ = "married_filing_jointly"
    MFS = "married_filing_separately"
    HOH = "head_of_household"
    QSS = "qualifying_surviving_spouse"


class Address(BaseModel):
    street: str
    apt: str | None = None
    city: str
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str


class NYResidencyInfo(BaseModel):
    full_year_resident: bool = True
    county: str
    nyc_resident: bool = False
    yonkers_resident: bool = False


class TaxpayerProfile(BaseModel):
    first_name: str
    last_name: str
    ssn: str = Field(..., description="SSN in XXX-XX-XXXX format")
    dob: date
    address: Address
    occupation: str | None = None
    phone: str | None = None
    email: str | None = None
    ny_residency: NYResidencyInfo | None = None


class SpouseProfile(BaseModel):
    first_name: str
    last_name: str
    ssn: str = Field(..., description="SSN in XXX-XX-XXXX format")
    dob: date
    occupation: str | None = None


class DependentProfile(BaseModel):
    first_name: str
    last_name: str
    ssn: str
    dob: date
    relationship: str
    months_in_home: int = Field(12, ge=0, le=12)
    child_tax_credit_eligible: bool = False
