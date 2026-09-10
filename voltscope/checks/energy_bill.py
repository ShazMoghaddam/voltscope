"""Check: does this look like a UK energy bill at all?

Voltscope is scoped to electricity and gas. A non-energy document (a water bill,
say) still runs through extraction and comes back shaped like the energy schema
but with none of the energy-specific signals: no electricity/gas fuel type, no
MPAN/MPRN, no p/kWh unit rate, no kWh reading. When every one of those is absent
across all supply points, the bill almost certainly is not an energy bill, and
the extracted fields should not be trusted.

Deterministic, and it only fires once a bill has supply points (an empty bill is
already covered by the missing-supply-points check).
"""

from __future__ import annotations

from typing import Any, List, Mapping

from ..models import Category, Finding, Severity
from .base import register


def _has_energy_signal(sp: Mapping[str, Any]) -> bool:
    if sp.get("fuel_type") in ("electricity", "gas"):
        return True
    if sp.get("mpan") or sp.get("mprn"):
        return True
    if any(isinstance(ur.get("rate_p_per_kwh"), (int, float)) for ur in sp.get("unit_rates") or []):
        return True
    if any(isinstance(rd.get("consumption_kwh"), (int, float)) for rd in sp.get("readings") or []):
        return True
    return False


@register
def check_energy_bill(bill: Mapping[str, Any]) -> List[Finding]:
    supply_points = bill.get("supply_points") or []
    if not supply_points:
        return []
    if any(_has_energy_signal(sp) for sp in supply_points):
        return []
    return [
        Finding(
            severity=Severity.WARNING,
            category=Category.DOMAIN,
            code="not_energy_bill",
            message=(
                "This does not look like a UK energy bill "
                "(no electricity/gas fuel type, MPAN/MPRN, unit rate, or kWh reading found)"
            ),
            affected_field="supply_points",
            recommendation="Voltscope handles electricity and gas bills; check the uploaded document.",
        )
    ]
