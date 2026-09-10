"""Registry for validation checks.

Each check is a function ``(bill: Mapping) -> list[Finding]`` decorated with
``@register``. Importing a check module registers it; the package ``__init__``
imports them in a fixed order, and :func:`all_checks` returns them in that
order. The engine runs them all and concatenates the results, so adding a rule
is a one-file change with no edits to the engine.
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping

from ..models import Finding

CheckFn = Callable[[Mapping[str, Any]], List[Finding]]

_REGISTRY: List[CheckFn] = []


def register(fn: CheckFn) -> CheckFn:
    """Decorator: add a check to the registry, preserving import order."""
    _REGISTRY.append(fn)
    return fn


def all_checks() -> List[CheckFn]:
    """Return the registered checks in execution order."""
    return list(_REGISTRY)
