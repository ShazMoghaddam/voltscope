"""Segment 2 tests for the structured validation engine.

The frozen golden tests in ``test_validator.py`` already prove that the engine,
via ``check_bill``, reproduces the exact segment 1 flag strings and order on the
original fixtures. These tests cover the new structure and the two additive
pieces: the VAT check and the ISO-date parsing fix.
"""

from __future__ import annotations

import json
from pathlib import Path

from voltscope.engine import run_checks
from voltscope.models import Category, Finding, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_findings_are_structured() -> None:
    findings = run_checks(_load("messy_bill"))
    assert findings and all(isinstance(f, Finding) for f in findings)

    by_code = {f.code: f for f in findings}
    for code in (
        "contract_renewal_window",
        "mpan_digit_count",
        "estimated_read",
        "duplicate_charge",
        "subtotal_reconciliation",
        "low_confidence_field",
    ):
        assert code in by_code

    assert by_code["subtotal_reconciliation"].severity is Severity.ERROR
    assert by_code["mpan_digit_count"].severity is Severity.WARNING
    assert by_code["contract_renewal_window"].severity is Severity.INFO

    for f in findings:
        assert f.message
        assert isinstance(f.category, Category)
        assert isinstance(f.severity, Severity)
        assert f.recommendation


def test_clean_bill_produces_no_findings() -> None:
    assert run_checks(_load("clean_bill")) == []


def test_vat_check_fires_on_mismatch_and_unusual_rate() -> None:
    bill = {"supply_points": [], "subtotal_gbp": 1000.0, "vat_gbp": 60.0, "total_gbp": 1100.0}
    codes = {f.code for f in run_checks(bill)}
    assert "vat_total_mismatch" in codes
    assert "vat_rate_unusual" in codes


def test_vat_check_silent_on_standard_bill() -> None:
    bill = {"supply_points": [], "subtotal_gbp": 1000.0, "vat_gbp": 200.0, "total_gbp": 1200.0}
    codes = {f.code for f in run_checks(bill)}
    assert "vat_total_mismatch" not in codes
    assert "vat_rate_unusual" not in codes


def test_iso_date_renewal_now_fires() -> None:
    bill = {
        "invoice_date": "2025-09-01",
        "contract_end_date": "2025-11-01",
        "supply_points": [],
    }
    codes = {f.code for f in run_checks(bill)}
    assert "contract_renewal_window" in codes
