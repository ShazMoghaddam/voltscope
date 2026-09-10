"""Check (new in segment 2): VAT consistency and rate plausibility.

Two independent signals:
  * ``vat_total_mismatch`` (WARNING): subtotal + VAT does not equal the stated
    total, within tolerance. A real inconsistency worth resolving.
  * ``vat_rate_unusual`` (INFO): the implied VAT rate is not a standard UK rate
    (0 / 5 / 20 percent). Advisory only.

This is additive: it does not fire on a well-formed bill, so the segment 1
golden fixtures (which have consistent 20 percent VAT) are unaffected.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register

STANDARD_VAT_RATES = (0.0, 5.0, 20.0)
RATE_TOLERANCE = 0.5  # percentage points


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float))


@register
def check_vat(bill: Mapping[str, Any]) -> List[Finding]:
    findings: List[Finding] = []
    sub = bill.get("subtotal_gbp")
    vat = bill.get("vat_gbp")
    total = bill.get("total_gbp")

    if _is_number(sub) and _is_number(vat) and _is_number(total):
        if abs((sub + vat) - total) > max(1.0, 0.01 * total):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    category=Category.TOTALS,
                    code="vat_total_mismatch",
                    message=(
                        f"VAT: subtotal £{sub:,.2f} + VAT £{vat:,.2f} = £{sub + vat:,.2f}, "
                        f"but total says £{total:,.2f}"
                    ),
                    affected_field="total_gbp",
                    recommendation="Subtotal plus VAT does not equal the stated total; verify the figures.",
                )
            )

    if _is_number(sub) and _is_number(vat) and sub > 0:
        rate = round(vat / sub * 100, 1)
        if all(abs(rate - r) > RATE_TOLERANCE for r in STANDARD_VAT_RATES):
            findings.append(
                Finding(
                    severity=Severity.INFO,
                    category=Category.TOTALS,
                    code="vat_rate_unusual",
                    message=(
                        f"VAT: implied rate is {rate:.1f}% "
                        f"(not a standard 0/5/20% rate) - worth checking"
                    ),
                    affected_field="vat_gbp",
                    recommendation="UK energy VAT is normally 20% (or 5% for qualifying low usage); confirm the rate.",
                )
            )
    return findings
