"""Dashboard aggregation.

Pure function over a list of records, so it produces the same result whatever
store the records came from and is trivial to test. The renewal window reuses
the same date parsing and -30..120 day window as the contract-dates check, and
uses a naive ``now`` to match ``parse_date`` (which returns naive datetimes).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from ..dateparsing import parse_date
from ..models import BillRecord, DashboardStats, RenewalItem, SupplierStat, Severity

RENEWAL_MIN_DAYS = -30
RENEWAL_MAX_DAYS = 120


def compute_dashboard(records: List[BillRecord], now: Optional[datetime] = None) -> DashboardStats:
    now = now or datetime.now()

    by_status: Counter[str] = Counter()
    sev = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    total_spend = 0.0
    supplier_map: Dict[str, List[float]] = {}  # supplier -> [count, total]
    renewals: List[RenewalItem] = []

    for r in records:
        by_status[r.status.value] += 1
        for f in r.findings:
            sev[f.severity.value] = sev.get(f.severity.value, 0) + 1

        bill = r.bill
        if bill is None:
            continue

        total = getattr(bill, "total_gbp", None)
        if isinstance(total, (int, float)):
            total_spend += total

        supplier = getattr(bill, "supplier_name", None) or "(unknown)"
        entry = supplier_map.setdefault(supplier, [0.0, 0.0])
        entry[0] += 1
        if isinstance(total, (int, float)):
            entry[1] += total

        end = parse_date(getattr(bill, "contract_end_date", None))
        if end:
            days = (end - now).days
            if RENEWAL_MIN_DAYS <= days <= RENEWAL_MAX_DAYS:
                renewals.append(
                    RenewalItem(
                        id=r.id,
                        filename=r.filename,
                        supplier=getattr(bill, "supplier_name", None),
                        contract_end_date=getattr(bill, "contract_end_date", None),
                        days_out=days,
                    )
                )

    suppliers = [
        SupplierStat(supplier=s, count=int(v[0]), total_gbp=round(v[1], 2))
        for s, v in supplier_map.items()
    ]
    suppliers.sort(key=lambda s: (-s.count, s.supplier))
    renewals.sort(key=lambda x: x.days_out)

    return DashboardStats(
        total_bills=len(records),
        by_status=dict(by_status),
        errors=sev["ERROR"],
        warnings=sev["WARNING"],
        info=sev["INFO"],
        total_spend_gbp=round(total_spend, 2),
        suppliers=suppliers,
        upcoming_renewals=renewals,
    )
