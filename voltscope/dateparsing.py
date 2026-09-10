"""Date parsing shared by validation checks.

Segment 2 note (the one deliberate behaviour change in this segment)
-------------------------------------------------------------------
The original spike parsed every date with
``dateutil.parser.parse(..., dayfirst=True, fuzzy=True)``. On an ISO date such
as ``2025-09-01`` whose day component is <= 12, dateutil's day-first heuristic
swapped month and day (reading it as 9 January), so the contract-renewal check
silently misfired on ISO-formatted contract dates. We now try a strict ISO parse
first and fall back to the day-first heuristic only for other formats.

DD/MM/YYYY parsing is unaffected, so the frozen segment 1 golden fixtures do not
change. A dedicated test (``test_iso_date_renewal_now_fires``) locks in the fix.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

try:
    from dateutil import parser as dateparser
except ImportError:
    dateparser = None  # type: ignore[assignment]


def parse_date(value: Any) -> Optional[datetime]:
    """Best-effort date parsing. Returns ``None`` if nothing parses.

    Order: strict ISO (``YYYY-MM-DD``) first, then day-first fuzzy parsing via
    ``python-dateutil`` if available, then a small set of explicit UK formats.
    """
    if not value:
        return None
    s = str(value).strip()

    # ISO first, to avoid the day-first mis-swap on yyyy-mm-dd.
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        pass

    if dateparser:
        try:
            return dateparser.parse(s, dayfirst=True, fuzzy=True)
        except (ValueError, OverflowError):
            return None

    for fmt in ("%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
