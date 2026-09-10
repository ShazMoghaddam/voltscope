"""Pydantic models describing the extracted bill schema.

Design notes for segment 1
---------------------------
* Every field is ``Optional`` and every model sets ``extra="allow"``. This
  preserves the spike's conservative extraction: nothing the model returns is
  dropped, and a missing field never causes a hard parse failure. The prompt
  tells Claude to return ``null`` rather than guess; the schema must not fight
  that by coercing or rejecting nulls.
* ``fuel_type`` and ``read_type`` are typed as plain strings, not strict
  ``Literal`` enums. The prompt already constrains them to a known set, and in
  a behaviour-preserving refactor we must not introduce a new failure mode, nor
  silently rewrite a value the original code passed through untouched. The
  allowed values are documented on the field and in the tuples below. Segment 2,
  where the validator owns correctness, is the place to tighten this.
* The validator does **not** consume these models. It reads the raw extracted
  dict, exactly as the original did, so its behaviour is provably identical.
  These models are used for typed serialisation of the output file and as the
  shared shape that the segment 3/4 web and persistence layers will build on.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Allowed values, enforced by the extraction prompt rather than by strict typing.
FUEL_TYPES = ("electricity", "gas", "unknown")
READ_TYPES = ("actual", "estimated", "customer", "unknown")


class Reading(BaseModel):
    """A single meter register reading.

    The JSON key is ``register``; the Python attribute is ``register_name`` to
    avoid shadowing a ``BaseModel`` member. Dumps use ``by_alias=True`` so the
    output key is unchanged from the extracted payload.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    register_name: Optional[str] = Field(default=None, alias="register")
    previous: Optional[float] = None
    current: Optional[float] = None
    read_type: Optional[str] = Field(default=None, description=f"One of {READ_TYPES}")
    consumption_kwh: Optional[float] = None


class UnitRate(BaseModel):
    """A unit rate line, in pence per kWh."""

    model_config = ConfigDict(extra="allow")

    label: Optional[str] = None
    rate_p_per_kwh: Optional[float] = None


class Charge(BaseModel):
    """A single charge line, in pounds."""

    model_config = ConfigDict(extra="allow")

    description: Optional[str] = None
    amount_gbp: Optional[float] = None


class SupplyPoint(BaseModel):
    """One site / meter point on a bill (a bill may have several)."""

    model_config = ConfigDict(extra="allow")

    fuel_type: Optional[str] = Field(default=None, description=f"One of {FUEL_TYPES}")
    supply_address: Optional[str] = None
    mpan: Optional[str] = None
    mprn: Optional[str] = None
    meter_serial: Optional[str] = None
    tariff_name: Optional[str] = None
    readings: List[Reading] = Field(default_factory=list)
    unit_rates: List[UnitRate] = Field(default_factory=list)
    standing_charge_p_per_day: Optional[float] = None
    charges: List[Charge] = Field(default_factory=list)


class Bill(BaseModel):
    """A full extracted energy bill."""

    model_config = ConfigDict(extra="allow")

    supplier_name: Optional[str] = None
    customer_name: Optional[str] = None
    account_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    billing_period_start: Optional[str] = None
    billing_period_end: Optional[str] = None
    contract_end_date: Optional[str] = None
    currency: Optional[str] = None
    supply_points: List[SupplyPoint] = Field(default_factory=list)
    subtotal_gbp: Optional[float] = None
    vat_gbp: Optional[float] = None
    total_gbp: Optional[float] = None
    low_confidence_fields: List[str] = Field(default_factory=list)
    extraction_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation findings (segment 2)
# ---------------------------------------------------------------------------
class Severity(str, Enum):
    """How much a finding should worry the reader."""

    INFO = "INFO"        # noteworthy, no action necessarily required
    WARNING = "WARNING"  # likely wrong or costing money; review
    ERROR = "ERROR"      # bill or extraction is inconsistent; must resolve


class Category(str, Enum):
    """The area of the bill a finding relates to (for grouping/filtering)."""

    COMPLETENESS = "completeness"
    EXTRACTION_QUALITY = "extraction_quality"
    CONTRACT = "contract"
    METER = "meter"
    READS = "reads"
    CHARGES = "charges"
    TOTALS = "totals"
    DOMAIN = "domain"


class Finding(BaseModel):
    """One deterministic validation result.

    ``code`` is a stable machine identifier (e.g. ``mpan_digit_count``) used by
    downstream layers to group and filter; ``message`` is the human-readable
    line and, for checks carried over from segment 1, is byte-identical to the
    original flag string so the golden tests still pass.
    """

    model_config = ConfigDict(use_enum_values=False)

    severity: Severity
    category: Category
    code: str
    message: str
    affected_field: Optional[str] = None
    recommendation: Optional[str] = None


# ---------------------------------------------------------------------------
# Application record (segments 3-4): a processed bill plus its findings.
# Shared by the review app and, in segment 4, the SQLite store.
# ---------------------------------------------------------------------------
class ProcessingStatus(str, Enum):
    """Lifecycle of a bill in the review app."""

    PROCESSED = "processed"  # extracted and validated
    EDITED = "edited"        # a human corrected fields; findings re-run
    FAILED = "failed"        # extraction failed


class BillRecord(BaseModel):
    """One uploaded bill: the extracted data, its findings, and metadata."""

    model_config = ConfigDict(
        use_enum_values=False,
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4",
                "filename": "march_invoice.pdf",
                "status": "processed",
                "bill": {"supplier_name": "British Gas Business", "total_gbp": 761.16},
                "findings": [
                    {
                        "severity": "WARNING",
                        "category": "meter",
                        "code": "mpan_digit_count",
                        "message": "site[0] MPAN has 9 digits, expected 13 (check extraction): 12 3456 789",
                        "affected_field": "supply_points[0].mpan",
                        "recommendation": "Verify the extracted MPAN against the bill; the core should be 13 digits.",
                    }
                ],
                "error": None,
                "created_at": "2026-01-15T09:30:00Z",
                "updated_at": "2026-01-15T09:30:00Z",
            }
        },
    )

    id: str
    filename: str
    status: ProcessingStatus
    bill: Optional[Bill] = None
    findings: List[Finding] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Persistence & dashboard (segment 4)
# ---------------------------------------------------------------------------
class HistoryEntry(BaseModel):
    """One processing-history event (upload, edit, delete, ...)."""

    bill_id: Optional[str] = None
    event: str
    detail: Optional[str] = None
    at: datetime


class SupplierStat(BaseModel):
    """Per-supplier rollup for the dashboard."""

    supplier: str
    count: int
    total_gbp: float


class RenewalItem(BaseModel):
    """A bill whose contract end date falls inside the switching window."""

    id: str
    filename: str
    supplier: Optional[str] = None
    contract_end_date: Optional[str] = None
    days_out: int


class DashboardStats(BaseModel):
    """Aggregate portfolio view derived from stored records."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_bills": 12,
                "by_status": {"processed": 10, "edited": 2},
                "errors": 1,
                "warnings": 5,
                "info": 8,
                "total_spend_gbp": 18422.5,
                "suppliers": [{"supplier": "British Gas Business", "count": 7, "total_gbp": 12040.0}],
                "upcoming_renewals": [
                    {"id": "a1b2c3d4", "filename": "march.pdf", "supplier": "EDF Energy",
                     "contract_end_date": "15/10/2025", "days_out": 44}
                ],
            }
        }
    )

    total_bills: int
    by_status: Dict[str, int]
    errors: int
    warnings: int
    info: int
    total_spend_gbp: float
    suppliers: List[SupplierStat]
    upcoming_renewals: List[RenewalItem]
