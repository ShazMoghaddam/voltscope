"""Segment 5 tests: authentication, CSV export, and OpenAPI docs."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from voltscope.api.app import create_app
from voltscope.api.store import InMemoryBillStore
from voltscope.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = json.loads((FIXTURES / "messy_bill.json").read_text(encoding="utf-8"))


def stub(data: bytes, filename: str):
    return json.loads(json.dumps(MESSY)), None


def _client(settings=None):
    app = create_app(store=InMemoryBillStore(), extract_fn=stub, settings=settings)
    return TestClient(app)


def _upload(client, headers=None):
    return client.post(
        "/api/bills",
        files={"files": ("bill.pdf", b"%PDF", "application/pdf")},
        headers=headers or {},
    )


# --- auth ---
def test_auth_required_when_keys_set(monkeypatch, tmp_path):
    monkeypatch.setenv("VOLTSCOPE_API_KEYS", "secret1, secret2")
    monkeypatch.setenv("VOLTSCOPE_DB", str(tmp_path / "a.db"))
    client = _client(Settings.from_env())

    assert client.get("/api/health").status_code == 200         # health stays open
    assert client.get("/api/health").json()["auth_required"] is True
    assert client.get("/api/bills").status_code == 401           # no key
    assert client.get("/api/bills", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/api/bills", headers={"X-API-Key": "secret2"}).status_code == 200


def test_auth_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("VOLTSCOPE_API_KEYS", raising=False)
    monkeypatch.setenv("VOLTSCOPE_DB", str(tmp_path / "b.db"))
    client = _client(Settings.from_env())
    assert client.get("/api/bills").status_code == 200
    assert client.get("/api/health").json()["auth_required"] is False


# --- CSV export ---
def test_export_csv_bills_and_findings():
    client = _client()
    _upload(client)

    r = client.get("/api/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "Bill ID" and len(rows) == 2  # header + one bill

    rf = client.get("/api/export.csv", params={"sheet": "findings"})
    assert rf.status_code == 200
    frows = list(csv.reader(io.StringIO(rf.text)))
    assert frows[0][2] == "Severity" and len(frows) >= 2  # messy fixture has findings


def test_export_csv_single_and_bad_sheet():
    client = _client()
    rid = _upload(client).json()[0]["id"]
    assert client.get(f"/api/bills/{rid}/export.csv").status_code == 200
    assert client.get("/api/export.csv", params={"sheet": "bogus"}).status_code == 400


# --- OpenAPI ---
def test_openapi_and_docs():
    client = _client()
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    # security scheme advertised
    assert "APIKeyHeader" in spec.get("components", {}).get("securitySchemes", {})
    # example present on the BillRecord schema
    assert "BillRecord" in spec["components"]["schemas"]
