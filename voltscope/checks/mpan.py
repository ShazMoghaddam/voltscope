"""Check: a UK electricity MPAN core should be 13 digits."""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register

MPAN_CORE_DIGITS = 13


@register
def check_mpan(bill: Mapping[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    for i, sp in enumerate(bill.get("supply_points") or []):
        mpan = sp.get("mpan")
        if sp.get("fuel_type") == "electricity" and mpan:
            digits = "".join(ch for ch in str(mpan) if ch.isdigit())
            if len(digits) != MPAN_CORE_DIGITS:
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        category=Category.METER,
                        code="mpan_digit_count",
                        message=(
                            f"site[{i}] MPAN has {len(digits)} digits, expected 13 "
                            f"(check extraction): {mpan}"
                        ),
                        affected_field=f"supply_points[{i}].mpan",
                        recommendation="Verify the extracted MPAN against the bill; the core should be 13 digits.",
                    )
                )
    return findings
