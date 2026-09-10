"""Validation engine: run every registered check over a bill.

The engine has no knowledge of individual rules. It asks the registry for the
checks and concatenates their findings in registration order. New rules appear
here automatically once their module is imported in ``checks/__init__``.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from . import checks
from .models import Finding


def run_checks(bill: Mapping[str, Any]) -> List[Finding]:
    """Run all registered checks and return their findings, in order."""
    findings: List[Finding] = []
    for check in checks.all_checks():
        findings.extend(check(bill))
    return findings
