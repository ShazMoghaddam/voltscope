"""Check: at least one supply point / meter was extracted."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register


@register
def check_missing_supply_points(bill: Mapping[str, Any]) -> List[Finding]:
    if bill.get("supply_points"):
        return []
    return [
        Finding(
            severity=Severity.ERROR,
            category=Category.COMPLETENESS,
            code="missing_supply_points",
            message="MISSING supply_points (no site/meter data extracted)",
            affected_field="supply_points",
            recommendation="Confirm the bill contains meter/site data and re-extract.",
        )
    ]
