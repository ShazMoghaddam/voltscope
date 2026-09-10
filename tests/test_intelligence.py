"""Segment 6 tests: the deterministic intelligence layer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from voltscope.api.app import create_app
from voltscope.api.store import InMemoryBillStore
from voltscope.intelligence import compute_intelligence
from voltscope.models import (
    Bill, BillRecord, Category, Charge, Finding, ProcessingStatus,
    Reading, Severity, SupplyPoint, UnitRate,
)

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = json.loads((FIXTURES / "messy_bill.json").read_text(encoding="utf-8"))


def _sp(fuel, rate, standing=45.0, estimated=False, charges=None):
    return SupplyPoint(
        fuel_type=fuel,
        unit_rates=[UnitRate(label="Day", rate_p_per_kwh=rate)],
        standing_charge_p_per_day=standing,
        readings=[Reading(read_type="estimated" if estimated else "actual", consumption_kwh=1000)],
        charges=charges or [],
    )


def _rec(rid, supplier, total, contract_end, invoice, sps, findings=None):
    now = datetime.now()
    return BillRecord(
        id=rid, filename=f"{rid}.pdf", status=ProcessingStatus.PROCESSED,
        bill=Bill(supplier_name=supplier, total_gbp=total, contract_end_date=contract_end,
                  invoice_date=invoice, supply_points=sps),
        findings=findings or [], error=None, created_at=now, updated_at=now,
    )


def _portfolio():
    soon = (datetime.now() + timedelta(days=20)).strftime("%d/%m/%Y")
    mid = (datetime.now() + timedelta(days=100)).strftime("%d/%m/%Y")
    return [
        _rec("a", "British Gas", 1000.0, soon, "01/06/2025",
             [_sp("electricity", 25.0, estimated=True,
                  charges=[Charge(description="Energy", amount_gbp=300.0),
                           Charge(description="Energy", amount_gbp=300.0)])],
             findings=[Finding(severity=Severity.ERROR, category=Category.TOTALS,
                               code="subtotal_reconciliation", message="m")]),
        _rec("b", "British Gas", 500.0, mid, "01/07/2025", [_sp("electricity", 26.0)]),
        _rec("c", "EDF", 800.0, None, "01/07/2025", [_sp("electricity", 80.0)]),
        _rec("d", "EDF", 400.0, None, "01/08/2025", [_sp("gas", 7.0)]),
    ]


def test_renewals_urgency():
    rep = compute_intelligence(_portfolio())
    urg = {r.bill_id: r.urgency for r in rep.renewals}
    assert urg["a"] is Severity.ERROR   # 20 days out
    assert urg["b"] is Severity.INFO    # 100 days out


def test_estimated_and_duplicates():
    rep = compute_intelligence(_portfolio())
    assert [e.bill_id for e in rep.estimated_reads] == ["a"]
    dup = rep.duplicate_charges[0]
    assert dup.count == 2 and dup.suspected_overcharge_gbp == 300.0


def test_high_unit_rate_relative_to_median():
    rep = compute_intelligence(_portfolio(), multiplier=1.3)
    # median of elec rates {25, 26, 80} is 26; 80 > 1.3*26 -> flagged, 25/26 not.
    assert len(rep.high_unit_rates) == 1
    flag = rep.high_unit_rates[0]
    assert flag.supplier == "EDF" and flag.baseline_p_per_kwh == 26.0 and flag.ratio > 3


def test_spend_and_supplier_comparison():
    rep = compute_intelligence(_portfolio())
    assert rep.spend.total_gbp == 2700.0
    assert rep.spend.by_supplier[0].supplier == "British Gas"
    months = {m.month for m in rep.spend.by_month}
    assert months == {"2025-06", "2025-07", "2025-08"}
    bg = next(s for s in rep.supplier_comparison if s.supplier == "British Gas")
    assert bg.avg_unit_rate_elec_p == 25.5 and bg.estimated_read_bills == 1 and bg.error_findings == 1


def test_portfolio_stats():
    rep = compute_intelligence(_portfolio())
    p = rep.portfolio
    assert p.total_bills == 4 and p.total_sites == 4 and p.suppliers == 2
    assert p.total_spend_gbp == 2700.0 and p.total_consumption_kwh == 4000.0
    assert p.invoice_date_range == ["2025-06-01", "2025-08-01"]


def test_alerts_ordered_by_severity():
    rep = compute_intelligence(_portfolio())
    severities = [a.severity for a in rep.alerts]
    assert severities == sorted(severities, key=lambda s: {"ERROR": 0, "WARNING": 1, "INFO": 2}[s.value])
    assert severities[0] is Severity.ERROR


def test_intelligence_endpoint():
    def stub(data, filename):
        return json.loads(json.dumps(MESSY)), None
    app = create_app(store=InMemoryBillStore(), extract_fn=stub)
    client = TestClient(app)
    client.post("/api/bills", files={"files": ("bill.pdf", b"%PDF", "application/pdf")})
    r = client.get("/api/intelligence")
    assert r.status_code == 200
    body = r.json()
    for key in ("alerts", "renewals", "estimated_reads", "duplicate_charges",
                "high_unit_rates", "spend", "supplier_comparison", "portfolio"):
        assert key in body
