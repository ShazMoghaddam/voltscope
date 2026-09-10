"""Check: estimated meter reads are a common overcharge source."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register


@register
def check_estimated_reads(bill: Mapping[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    for i, sp in enumerate(bill.get("supply_points") or []):
        for r in sp.get("readings") or []:
            if r.get("read_type") == "estimated":
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        category=Category.READS,
                        code="estimated_read",
                        message=(
                            f"site[{i}] ESTIMATED read on {r.get('register') or 'meter'} "
                            f"- estimates are a common overcharge source"
                        ),
                        affected_field=f"supply_points[{i}].readings",
                        recommendation="Submit an actual meter reading; estimates frequently over- or under-charge.",
                    )
                )
    return findings
