"""Check: surface the fields the extractor itself flagged as low confidence."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register


@register
def check_low_confidence(bill: Mapping[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    for path in bill.get("low_confidence_fields") or []:
        findings.append(
            Finding(
                severity=Severity.INFO,
                category=Category.EXTRACTION_QUALITY,
                code="low_confidence_field",
                message=f"LOW CONFIDENCE: {path}",
                affected_field=path,
                recommendation="The extractor flagged this field as uncertain; verify it against the source bill.",
            )
        )
    return findings
