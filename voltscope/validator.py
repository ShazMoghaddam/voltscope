"""Backwards-compatible validation facade.

Segment 2 moves the real logic into ``engine.run_checks`` and the per-rule
modules under ``checks/``. This module keeps the segment 1 surface alive:

* ``check_bill(bill) -> list[str]`` still returns the flat list of flag strings,
  now derived from the structured findings. On the segment 1 fixtures it
  reproduces the original strings in the original order, which is exactly what
  the frozen golden tests assert.
* ``parse_date`` is re-exported from its new home so any existing import keeps
  working.

Prefer ``engine.run_checks`` for new code; it returns rich ``Finding`` objects.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from .dateparsing import parse_date  # re-exported for backwards compatibility
from .engine import run_checks

__all__ = ["check_bill", "parse_date", "run_checks"]


def check_bill(bill: Mapping[str, Any]) -> List[str]:
    """Return validation findings as flat flag strings (segment 1 compatibility)."""
    return [f.message for f in run_checks(bill)]
