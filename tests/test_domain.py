"""Tests for the non-energy (domain) detection check.

``water_bill.json`` is modelled on a real Thames Water bill pushed through the
energy schema; it also joins the golden validator suite automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

from voltscope.engine import run_checks
from voltscope.models import Category, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_water_bill_flagged_as_non_energy():
    findings = {f.code: f for f in run_checks(_load("water_bill"))}
    assert "not_energy_bill" in findings
    f = findings["not_energy_bill"]
    assert f.severity is Severity.WARNING and f.category is Category.DOMAIN


def test_energy_bills_not_flagged():
    for name in ("clean_bill", "messy_bill", "real_ovo_bill"):
        codes = {f.code for f in run_checks(_load(name))}
        assert "not_energy_bill" not in codes


def test_kwh_reading_alone_counts_as_energy():
    # No fuel type or MPAN, but a kWh reading is still an energy signal.
    bill = {"supply_points": [{"readings": [{"consumption_kwh": 500}]}]}
    codes = {f.code for f in run_checks(bill)}
    assert "not_energy_bill" not in codes


def test_empty_bill_not_flagged_here():
    # An empty bill is covered by missing_supply_points, not this check.
    codes = {f.code for f in run_checks({"supply_points": []})}
    assert "not_energy_bill" not in codes
    assert "missing_supply_points" in codes
