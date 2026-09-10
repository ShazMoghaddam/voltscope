"""Check: charge lines across all sites should sum to the subtotal."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register


@register
def check_reconciliation(bill: Mapping[str, Any]) -> List[Finding]:
    line_total = 0.0
    have_lines = False
    for sp in bill.get("supply_points") or []:
        for c in sp.get("charges") or []:
            if isinstance(c.get("amount_gbp"), (int, float)):
                line_total += c["amount_gbp"]
                have_lines = True

    sub = bill.get("subtotal_gbp")
    if have_lines and isinstance(sub, (int, float)):
        if abs(line_total - sub) > max(1.0, 0.01 * sub):
            return [
                Finding(
                    severity=Severity.ERROR,
                    category=Category.TOTALS,
                    code="subtotal_reconciliation",
                    message=(
                        f"RECONCILE: line items sum to £{line_total:,.2f} but "
                        f"subtotal says £{sub:,.2f} (diff £{line_total - sub:,.2f})"
                    ),
                    affected_field="subtotal_gbp",
                    recommendation="Line-item total and subtotal disagree; check for missing or misread charge lines.",
                )
            ]
    return []
