"""Check: duplicate charge lines within a site (same description + amount)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from ..models import Category, Finding, Severity
from .base import register


@register
def check_duplicate_charges(bill: Mapping[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    for i, sp in enumerate(bill.get("supply_points") or []):
        seen: Dict[Tuple[str, Any], int] = {}
        for c in sp.get("charges") or []:
            key = (str(c.get("description")).strip().lower(), c.get("amount_gbp"))
            seen[key] = seen.get(key, 0) + 1
        for (desc, amt), n in seen.items():
            if n > 1 and desc not in ("none", ""):
                findings.append(
                    Finding(
                        severity=Severity.WARNING,
                        category=Category.CHARGES,
                        code="duplicate_charge",
                        message=(
                            f"site[{i}] DUPLICATE charge x{n}: '{desc}' at "
                            f"£{amt} each - possible double-billing"
                        ),
                        affected_field=f"supply_points[{i}].charges",
                        recommendation="Confirm whether the repeated line is genuinely separate or a double-bill.",
                    )
                )
    return findings
