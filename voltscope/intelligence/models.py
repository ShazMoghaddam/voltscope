"""Typed models for the intelligence layer.

These are derived, read-only views over the stored records (never persisted), so
they live here rather than in the core ``models`` module. Urgency reuses the
validation :class:`Severity` scale.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

from ..models import Severity


class Insight(BaseModel):
    """A headline, actionable item for the 'what needs attention' summary."""

    severity: Severity
    code: str
    title: str
    detail: str
    bill_ids: List[str] = []
    value_gbp: Optional[float] = None
    recommendation: Optional[str] = None


class RenewalAlert(BaseModel):
    bill_id: str
    filename: str
    supplier: Optional[str] = None
    contract_end_date: Optional[str] = None
    days_out: int
    urgency: Severity


class EstimatedReadItem(BaseModel):
    bill_id: str
    filename: str
    supplier: Optional[str] = None
    site_index: int
    register_label: Optional[str] = None


class DuplicateChargeItem(BaseModel):
    bill_id: str
    filename: str
    supplier: Optional[str] = None
    site_index: int
    description: Optional[str] = None
    amount_gbp: Optional[float] = None
    count: int
    suspected_overcharge_gbp: Optional[float] = None


class SupplierSpend(BaseModel):
    supplier: str
    bills: int
    total_gbp: float
    avg_bill_gbp: float


class MonthSpend(BaseModel):
    month: str
    total_gbp: float
    bills: int


class SpendSummary(BaseModel):
    total_gbp: float
    avg_bill_gbp: float
    by_supplier: List[SupplierSpend]
    by_month: List[MonthSpend]


class SupplierComparison(BaseModel):
    supplier: str
    bills: int
    total_gbp: float
    avg_unit_rate_elec_p: Optional[float] = None
    avg_unit_rate_gas_p: Optional[float] = None
    avg_standing_charge_p: Optional[float] = None
    estimated_read_bills: int = 0
    error_findings: int = 0


class HighRateFlag(BaseModel):
    bill_id: str
    filename: str
    supplier: Optional[str] = None
    site_index: int
    fuel_type: Optional[str] = None
    label: Optional[str] = None
    rate_p_per_kwh: float
    baseline_p_per_kwh: float
    ratio: float
    reason: str


class PortfolioStats(BaseModel):
    total_bills: int
    total_sites: int
    suppliers: int
    total_spend_gbp: float
    total_consumption_kwh: float
    avg_unit_rate_elec_p: Optional[float] = None
    avg_unit_rate_gas_p: Optional[float] = None
    by_status: Dict[str, int]
    errors: int
    warnings: int
    info: int
    invoice_date_range: Optional[List[str]] = None


class IntelligenceReport(BaseModel):
    generated_at: datetime
    alerts: List[Insight]
    renewals: List[RenewalAlert]
    estimated_reads: List[EstimatedReadItem]
    duplicate_charges: List[DuplicateChargeItem]
    high_unit_rates: List[HighRateFlag]
    spend: SpendSummary
    supplier_comparison: List[SupplierComparison]
    portfolio: PortfolioStats
