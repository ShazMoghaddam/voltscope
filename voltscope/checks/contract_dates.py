"""Check: contract end date falls inside the switching window.

Behaviour is carried over from segment 1 (same message, same -30..120 day
window). Severity is INFO because this is an opportunity alert, not a
correctness problem. Segment 6 builds portfolio-wide renewal alerts on the same
signal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Mapping

from ..dateparsing import parse_date
from ..models import Category, Finding, Severity
from .base import register

WINDOW_MIN_DAYS = -30
WINDOW_MAX_DAYS = 120


@register
def check_contract_dates(bill: Mapping[str, Any]) -> List[Finding]:
    end_date = parse_date(bill.get("contract_end_date"))
    if not end_date:
        return []
    ref = parse_date(bill.get("invoice_date")) or datetime.now()
    days = (end_date - ref).days
    if not (WINDOW_MIN_DAYS <= days <= WINDOW_MAX_DAYS):
        return []
    return [
        Finding(
            severity=Severity.INFO,
            category=Category.CONTRACT,
            code="contract_renewal_window",
            message=(
                f"RENEWAL: contract ends ~{days} days out "
                f"({bill.get('contract_end_date')}) - switching window open"
            ),
            affected_field="contract_end_date",
            recommendation="Start the renewal/switching process now to avoid rolling onto out-of-contract rates.",
        )
    ]
