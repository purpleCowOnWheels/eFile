"""pfile.models — all public data model exports."""

from pfile.models.documents import (
    F1099_B,
    F1099_DIV,
    F1099_INT,
    F1099_R,
    K1_1065,
    K1_1120S,
    SSA_1099,
    W2,
    AnyDocument,
    Box12Entry,
    BrokerageTransaction,
    CoverageType,
    EntityInfo,
    ParseConfidence,
    TermType,
)
from pfile.models.filer import (
    Address,
    DependentProfile,
    FilingStatus,
    NYResidencyInfo,
    SpouseProfile,
    TaxpayerProfile,
)
from pfile.models.forms import (
    IT2,
    IT201,
    CapitalTransaction,
    ComputedFederalReturn,
    ComputedNYReturn,
    Form1040,
    IT2Entry,
    ScheduleB,
    ScheduleD,
    ScheduleE,
    ScheduleEEntry,
    ScheduleSE,
)
from pfile.models.session import (
    DocumentSet,
    FilingSession,
    SessionStatus,
)

__all__ = [
    # documents
    "AnyDocument",
    "Box12Entry",
    "BrokerageTransaction",
    "CoverageType",
    "EntityInfo",
    "F1099_B",
    "F1099_DIV",
    "F1099_INT",
    "F1099_R",
    "K1_1065",
    "K1_1120S",
    "ParseConfidence",
    "SSA_1099",
    "TermType",
    "W2",
    # filer
    "Address",
    "DependentProfile",
    "FilingStatus",
    "NYResidencyInfo",
    "SpouseProfile",
    "TaxpayerProfile",
    # forms
    "CapitalTransaction",
    "ComputedFederalReturn",
    "ComputedNYReturn",
    "Form1040",
    "IT2",
    "IT2Entry",
    "IT201",
    "ScheduleB",
    "ScheduleD",
    "ScheduleE",
    "ScheduleEEntry",
    "ScheduleSE",
    # session
    "DocumentSet",
    "FilingSession",
    "SessionStatus",
]
