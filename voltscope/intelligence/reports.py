"""Deterministic portfolio intelligence over stored records.

Everything here is computed from the already-extracted, already-validated
structured data. No LLM calls. The per-bill validation findings remain the
source of truth for correctness; this layer turns the structured data into
cross-portfolio insight (renewals, estimated reads, duplicate charges, spend,
supplier comparison, high unit rates, portfolio statistics).
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import datetime
from statistics import mean, median
from typing import Any, Dict, List, Optional

from ..dateparsing import parse_date
from ..models import BillRecord, Severity
from .models import (
    DuplicateChargeItem,
    EstimatedReadItem,
    HighRateFlag,
    Insight,
    IntelligenceReport,
    MonthSpend,
    PortfolioStats,
    RenewalAlert,
    SpendSummary,
    SupplierComparison,
    SupplierSpend,
)

RENEWAL_MIN_DAYS = -30
RENEWAL_MAX_DAYS = 120
URGENT_DAYS = 30
SOON_DAYS = 60
MIN_BASELINE_SAMPLES = 3
_UNKNOWN = "(unknown)"
_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float))


def _bill_dict(record: BillRecord) -> Optional[Dict[str, Any]]:
    return record.bill.model_dump(by_alias=True) if record.bill is not None else None


def _supplier(bill: Dict[str, Any]) -> Optional[str]:
    return bill.get("supplier_name")


def _dedupe(ids: List[str]) -> List[str]:
    return list(OrderedDict.fromkeys(ids))


# --- individual reports ---
def renewals(records: List[BillRecord], now: datetime) -> List[RenewalAlert]:
    out: List[RenewalAlert] = []
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        end = parse_date(bill.get("contract_end_date"))
        if not end:
            continue
        days = (end - now).days
        if not (RENEWAL_MIN_DAYS <= days <= RENEWAL_MAX_DAYS):
            continue
        urgency = Severity.ERROR if days <= URGENT_DAYS else Severity.WARNING if days <= SOON_DAYS else Severity.INFO
        out.append(RenewalAlert(
            bill_id=r.id, filename=r.filename, supplier=_supplier(bill),
            contract_end_date=bill.get("contract_end_date"), days_out=days, urgency=urgency,
        ))
    out.sort(key=lambda x: x.days_out)
    return out


def estimated_reads(records: List[BillRecord]) -> List[EstimatedReadItem]:
    out: List[EstimatedReadItem] = []
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        for i, sp in enumerate(bill.get("supply_points") or []):
            for reading in sp.get("readings") or []:
                if reading.get("read_type") == "estimated":
                    out.append(EstimatedReadItem(
                        bill_id=r.id, filename=r.filename, supplier=_supplier(bill),
                        site_index=i, register_label=reading.get("register"),
                    ))
    return out


def duplicate_charges(records: List[BillRecord]) -> List[DuplicateChargeItem]:
    out: List[DuplicateChargeItem] = []
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        for i, sp in enumerate(bill.get("supply_points") or []):
            counts: "Counter[tuple]" = Counter()
            first_desc: Dict[tuple, Optional[str]] = {}
            for c in sp.get("charges") or []:
                key = (str(c.get("description")).strip().lower(), c.get("amount_gbp"))
                counts[key] += 1
                first_desc.setdefault(key, c.get("description"))
            for (desc, amt), n in counts.items():
                if n > 1 and desc not in ("none", ""):
                    overcharge = round(amt * (n - 1), 2) if _num(amt) else None
                    out.append(DuplicateChargeItem(
                        bill_id=r.id, filename=r.filename, supplier=_supplier(bill),
                        site_index=i, description=first_desc[(desc, amt)],
                        amount_gbp=amt if _num(amt) else None, count=n,
                        suspected_overcharge_gbp=overcharge,
                    ))
    out.sort(key=lambda x: x.suspected_overcharge_gbp or 0, reverse=True)
    return out


def _rates_by_fuel(records: List[BillRecord]) -> Dict[str, List[float]]:
    buckets: Dict[str, List[float]] = {"electricity": [], "gas": []}
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        for sp in bill.get("supply_points") or []:
            fuel = sp.get("fuel_type")
            if fuel not in buckets:
                continue
            for ur in sp.get("unit_rates") or []:
                rate = ur.get("rate_p_per_kwh")
                if _num(rate):
                    buckets[fuel].append(rate)
    return buckets


def high_unit_rates(records: List[BillRecord], multiplier: float) -> List[HighRateFlag]:
    buckets = _rates_by_fuel(records)
    baselines = {
        fuel: (median(vals) if len(vals) >= MIN_BASELINE_SAMPLES else None)
        for fuel, vals in buckets.items()
    }
    out: List[HighRateFlag] = []
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        for i, sp in enumerate(bill.get("supply_points") or []):
            fuel = sp.get("fuel_type")
            base = baselines.get(fuel)
            if not base:
                continue
            for ur in sp.get("unit_rates") or []:
                rate = ur.get("rate_p_per_kwh")
                if _num(rate) and rate > multiplier * base:
                    out.append(HighRateFlag(
                        bill_id=r.id, filename=r.filename, supplier=_supplier(bill),
                        site_index=i, fuel_type=fuel, label=ur.get("label"),
                        rate_p_per_kwh=round(rate, 2), baseline_p_per_kwh=round(base, 2),
                        ratio=round(rate / base, 2),
                        reason=f"above {multiplier}x portfolio median for {fuel}",
                    ))
    out.sort(key=lambda x: x.ratio, reverse=True)
    return out


def spend_summary(records: List[BillRecord]) -> SpendSummary:
    total = 0.0
    counted = 0
    by_supplier: Dict[str, List[float]] = {}
    by_month: Dict[str, List[float]] = {}
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        amount = bill.get("total_gbp")
        if not _num(amount):
            continue
        total += amount
        counted += 1
        sup = _supplier(bill) or _UNKNOWN
        by_supplier.setdefault(sup, [0.0, 0.0])
        by_supplier[sup][0] += 1
        by_supplier[sup][1] += amount
        inv = parse_date(bill.get("invoice_date"))
        if inv:
            key = inv.strftime("%Y-%m")
            by_month.setdefault(key, [0.0, 0.0])
            by_month[key][0] += 1
            by_month[key][1] += amount

    suppliers = [
        SupplierSpend(supplier=s, bills=int(v[0]), total_gbp=round(v[1], 2),
                      avg_bill_gbp=round(v[1] / v[0], 2) if v[0] else 0.0)
        for s, v in by_supplier.items()
    ]
    suppliers.sort(key=lambda s: s.total_gbp, reverse=True)
    months = [
        MonthSpend(month=m, bills=int(v[0]), total_gbp=round(v[1], 2))
        for m, v in by_month.items()
    ]
    months.sort(key=lambda m: m.month)
    return SpendSummary(
        total_gbp=round(total, 2),
        avg_bill_gbp=round(total / counted, 2) if counted else 0.0,
        by_supplier=suppliers, by_month=months,
    )


def supplier_comparison(records: List[BillRecord]) -> List[SupplierComparison]:
    agg: Dict[str, Dict[str, Any]] = {}
    for r in records:
        bill = _bill_dict(r)
        if not bill:
            continue
        sup = _supplier(bill) or _UNKNOWN
        a = agg.setdefault(sup, {
            "bills": 0, "total": 0.0, "electricity": [], "gas": [], "standing": [],
            "est_bills": 0, "errors": 0,
        })
        a["bills"] += 1
        if _num(bill.get("total_gbp")):
            a["total"] += bill["total_gbp"]
        a["errors"] += sum(1 for f in r.findings if f.severity is Severity.ERROR)
        has_estimate = False
        for sp in bill.get("supply_points") or []:
            fuel = sp.get("fuel_type")
            for ur in sp.get("unit_rates") or []:
                rate = ur.get("rate_p_per_kwh")
                if _num(rate) and fuel in ("electricity", "gas"):
                    a[fuel].append(rate)
            sc = sp.get("standing_charge_p_per_day")
            if _num(sc):
                a["standing"].append(sc)
            if any(rd.get("read_type") == "estimated" for rd in sp.get("readings") or []):
                has_estimate = True
        if has_estimate:
            a["est_bills"] += 1

    out = [
        SupplierComparison(
            supplier=s, bills=a["bills"], total_gbp=round(a["total"], 2),
            avg_unit_rate_elec_p=round(mean(a["electricity"]), 2) if a["electricity"] else None,
            avg_unit_rate_gas_p=round(mean(a["gas"]), 2) if a["gas"] else None,
            avg_standing_charge_p=round(mean(a["standing"]), 2) if a["standing"] else None,
            estimated_read_bills=a["est_bills"], error_findings=a["errors"],
        )
        for s, a in agg.items()
    ]
    out.sort(key=lambda s: s.total_gbp, reverse=True)
    return out


def portfolio_stats(records: List[BillRecord]) -> PortfolioStats:
    sites = 0
    consumption = 0.0
    elec: List[float] = []
    gas: List[float] = []
    suppliers = set()
    inv_dates: List[datetime] = []
    by_status: Counter = Counter()
    sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}

    for r in records:
        by_status[r.status.value] += 1
        for f in r.findings:
            sev[f.severity.value] = sev.get(f.severity.value, 0) + 1
        bill = _bill_dict(r)
        if not bill:
            continue
        if bill.get("supplier_name"):
            suppliers.add(bill["supplier_name"])
        inv = parse_date(bill.get("invoice_date"))
        if inv:
            inv_dates.append(inv)
        for sp in bill.get("supply_points") or []:
            sites += 1
            fuel = sp.get("fuel_type")
            for ur in sp.get("unit_rates") or []:
                rate = ur.get("rate_p_per_kwh")
                if _num(rate) and fuel == "electricity":
                    elec.append(rate)
                elif _num(rate) and fuel == "gas":
                    gas.append(rate)
            for rd in sp.get("readings") or []:
                if _num(rd.get("consumption_kwh")):
                    consumption += rd["consumption_kwh"]

    date_range = None
    if inv_dates:
        date_range = [min(inv_dates).date().isoformat(), max(inv_dates).date().isoformat()]

    return PortfolioStats(
        total_bills=len(records), total_sites=sites, suppliers=len(suppliers),
        total_spend_gbp=round(sum(r.bill.total_gbp for r in records
                                  if r.bill and _num(r.bill.total_gbp)), 2),
        total_consumption_kwh=round(consumption, 2),
        avg_unit_rate_elec_p=round(mean(elec), 2) if elec else None,
        avg_unit_rate_gas_p=round(mean(gas), 2) if gas else None,
        by_status=dict(by_status), errors=sev["ERROR"], warnings=sev["WARNING"],
        info=sev["INFO"], invoice_date_range=date_range,
    )


def _alerts(
    renewal_items: List[RenewalAlert],
    estimated_items: List[EstimatedReadItem],
    duplicate_items: List[DuplicateChargeItem],
    high_rate_items: List[HighRateFlag],
    records: List[BillRecord],
) -> List[Insight]:
    alerts: List[Insight] = []

    error_bills = _dedupe([r.id for r in records
                           if any(f.severity is Severity.ERROR for f in r.findings)])
    if error_bills:
        alerts.append(Insight(
            severity=Severity.ERROR, code="validation_errors",
            title=f"{len(error_bills)} bill(s) with error-level findings",
            detail="Totals or required fields are inconsistent on these bills.",
            bill_ids=error_bills,
            recommendation="Resolve the ERROR findings before trusting these bills.",
        ))

    if renewal_items:
        within_60 = [r for r in renewal_items if r.days_out <= SOON_DAYS]
        sev = (Severity.ERROR if any(r.days_out <= URGENT_DAYS for r in renewal_items)
               else Severity.WARNING if within_60 else Severity.INFO)
        alerts.append(Insight(
            severity=sev, code="renewals_due",
            title=f"{len(renewal_items)} contract(s) in the switching window",
            detail=f"{len(within_60)} within {SOON_DAYS} days.",
            bill_ids=_dedupe([r.bill_id for r in renewal_items]),
            recommendation="Start renewal/switching before contracts roll to out-of-contract rates.",
        ))

    if estimated_items:
        bills = _dedupe([e.bill_id for e in estimated_items])
        alerts.append(Insight(
            severity=Severity.WARNING, code="estimated_reads",
            title=f"{len(estimated_items)} estimated read(s) across {len(bills)} bill(s)",
            detail="Estimated reads commonly over- or under-charge.",
            bill_ids=bills,
            recommendation="Submit actual meter readings to correct billing.",
        ))

    if duplicate_items:
        total = round(sum(d.suspected_overcharge_gbp or 0 for d in duplicate_items), 2)
        alerts.append(Insight(
            severity=Severity.WARNING, code="duplicate_charges",
            title=f"{len(duplicate_items)} duplicate charge line(s)",
            detail=f"~£{total:,.2f} suspected double-billing.",
            bill_ids=_dedupe([d.bill_id for d in duplicate_items]),
            value_gbp=total,
            recommendation="Review repeated charge lines with the supplier.",
        ))

    if high_rate_items:
        alerts.append(Insight(
            severity=Severity.WARNING, code="high_unit_rates",
            title=f"{len(high_rate_items)} rate line(s) well above your portfolio median",
            detail="These tariffs are high relative to the rest of the portfolio.",
            bill_ids=_dedupe([h.bill_id for h in high_rate_items]),
            recommendation="Compare these tariffs; they may be candidates for switching.",
        ))

    alerts.sort(key=lambda a: _SEVERITY_ORDER[a.severity])
    return alerts


def compute_intelligence(
    records: List[BillRecord],
    multiplier: float = 1.3,
    now: Optional[datetime] = None,
) -> IntelligenceReport:
    now = now or datetime.now()
    renewal_items = renewals(records, now)
    estimated_items = estimated_reads(records)
    duplicate_items = duplicate_charges(records)
    high_rate_items = high_unit_rates(records, multiplier)
    return IntelligenceReport(
        generated_at=datetime.now(),
        alerts=_alerts(renewal_items, estimated_items, duplicate_items, high_rate_items, records),
        renewals=renewal_items,
        estimated_reads=estimated_items,
        duplicate_charges=duplicate_items,
        high_unit_rates=high_rate_items,
        spend=spend_summary(records),
        supplier_comparison=supplier_comparison(records),
        portfolio=portfolio_stats(records),
    )
