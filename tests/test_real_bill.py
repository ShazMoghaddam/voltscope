"""The real-bill anchor.

``real_ovo_bill.json`` is a genuine OVO domestic dual-fuel bill, transcribed
into the schema with personal identifiers replaced by synthetic stand-ins. It is
also picked up automatically by the golden tests in ``test_validator.py``. These
assertions document what a clean real bill produces: the money fields reconcile,
nothing spurious fires, and the one useful signal (the contract nearing its end)
is surfaced.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from voltscope.engine import run_checks
from voltscope.intelligence import compute_intelligence
from voltscope.models import BillRecord, ProcessingStatus

FIXTURE = Path(__file__).parent / "fixtures" / "real_ovo_bill.json"
BILL = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_structure():
    sps = BILL["supply_points"]
    assert [sp["fuel_type"] for sp in sps] == ["electricity", "gas"]
    mpan_digits = "".join(c for c in sps[0]["mpan"] if c.isdigit())
    assert len(mpan_digits) == 13


def test_only_renewal_fires():
    codes = {f.code for f in run_checks(BILL)}
    assert codes == {"contract_renewal_window"}
    # explicitly: the clean bill trips none of these
    for quiet in ("mpan_digit_count", "subtotal_reconciliation",
                  "vat_total_mismatch", "vat_rate_unusual", "estimated_read"):
        assert quiet not in codes


def test_intelligence_flags_the_renewal():
    now = datetime.now()
    record = BillRecord(
        id="real", filename="ovo.pdf", status=ProcessingStatus.PROCESSED,
        bill=BILL, findings=run_checks(BILL), created_at=now, updated_at=now,
    )
    report = compute_intelligence([record])
    assert any(r.bill_id == "real" for r in report.renewals)
    assert report.portfolio.total_sites == 2
