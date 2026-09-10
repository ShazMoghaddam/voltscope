"""Check: required top-level fields are present."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register

REQUIRED_FIELDS = ["supplier_name", "billing_period_start", "billing_period_end", "total_gbp"]


@register
def check_missing_required(bill: Mapping[str, Any]) -> List[Finding]:
    missing = [f for f in REQUIRED_FIELDS if not bill.get(f)]
    if not missing:
        return []
    return [
        Finding(
            severity=Severity.ERROR,
            category=Category.COMPLETENESS,
            code="missing_required_fields",
            message=f"MISSING required fields: {', '.join(missing)}",
            affected_field=None,
            recommendation="Re-extract or check the source bill; these fields are needed to audit it.",
        )
    ]
