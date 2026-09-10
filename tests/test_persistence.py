"""Segment 4 tests: SQLite persistence, history, and the dashboard.

Extraction is stubbed, so these run without an Anthropic key. Persistence is
proven by reopening a fresh store on the same database file.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voltscope.api.app import create_app
from voltscope.api.dashboard import compute_dashboard
from voltscope.api.service import ReviewService
from voltscope.api.sqlite_store import SqliteBillStore
from voltscope.models import Bill, BillRecord, Finding, ProcessingStatus, Severity
from voltscope.models import Category

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = json.loads((FIXTURES / "messy_bill.json").read_text(encoding="utf-8"))


def stub(data: bytes, filename: str):
    return json.loads(json.dumps(MESSY)), None


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "voltscope_test.db"


def test_sqlite_roundtrip_and_reopen(db_path):
    store = SqliteBillStore(db_path)
    rec = ReviewService(store, stub).ingest("demo.pdf", b"x")

    # A brand-new store on the same file sees the persisted record.
    reopened = SqliteBillStore(db_path)
    got = reopened.get(rec.id)
    assert got is not None
    assert got.bill.supplier_name == "EDF Energy"
    assert len(got.findings) == len(rec.findings)
    assert len(reopened.list()) == 1


def test_delete_cascades_findings_but_keeps_history(db_path):
    store = SqliteBillStore(db_path)
    svc = ReviewService(store, stub)
    rec = svc.ingest("demo.pdf", b"x")
    assert svc.delete(rec.id) is True

    reopened = SqliteBillStore(db_path)
    assert reopened.get(rec.id) is None
    events = [h.event for h in reopened.history()]
    assert "processed" in events and "deleted" in events


def test_history_records_edit(db_path):
    store = SqliteBillStore(db_path)
    svc = ReviewService(store, stub)
    rec = svc.ingest("demo.pdf", b"x")
    svc.apply_edits(rec.id, {"supplier_name": "New", "supply_points": []})
    events = [h.event for h in store.history()]
    assert events[:2] == ["edited", "processed"]  # newest first


def _record(rid, supplier, total, contract_end, findings=None):
    now = datetime.now()
    return BillRecord(
        id=rid, filename=f"{rid}.pdf", status=ProcessingStatus.PROCESSED,
        bill=Bill(supplier_name=supplier, total_gbp=total, contract_end_date=contract_end),
        findings=findings or [], error=None, created_at=now, updated_at=now,
    )


def test_dashboard_aggregation():
    soon = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
    far = (datetime.now() + timedelta(days=900)).strftime("%d/%m/%Y")
    err = Finding(severity=Severity.ERROR, category=Category.TOTALS, code="x", message="m")
    records = [
        _record("a", "British Gas", 1000.0, soon, findings=[err]),
        _record("b", "British Gas", 500.0, far),
        _record("c", "EDF", 250.0, None),
    ]
    d = compute_dashboard(records)
    assert d.total_bills == 3
    assert d.total_spend_gbp == 1750.0
    assert d.errors == 1
    # British Gas leads with 2 bills.
    assert d.suppliers[0].supplier == "British Gas" and d.suppliers[0].count == 2
    # Only the 'soon' contract is in the renewal window.
    assert [r.id for r in d.upcoming_renewals] == ["a"]


def test_dashboard_and_history_endpoints(db_path):
    app = create_app(store=SqliteBillStore(db_path), extract_fn=stub)
    client = TestClient(app)
    client.post("/api/bills", files={"files": ("bill.pdf", b"%PDF", "application/pdf")})

    d = client.get("/api/dashboard").json()
    assert d["total_bills"] == 1
    h = client.get("/api/history").json()
    assert h[0]["event"] == "processed"
