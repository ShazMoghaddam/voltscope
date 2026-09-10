"""Validation checks, one module per rule, auto-registered on import.

The import order below defines execution order. For the checks carried over
from segment 1, this order reproduces the original flag sequence on
single-site bills, so the frozen golden tests still pass. ``vat`` is new and
additive; ``low_confidence`` runs last, mirroring the original.
"""

from .base import all_checks, register  # noqa: F401

from . import missing_required       # noqa: F401,E402
from . import missing_supply_points  # noqa: F401,E402
from . import energy_bill            # noqa: F401,E402
from . import contract_dates         # noqa: F401,E402
from . import mpan                   # noqa: F401,E402
from . import estimated_reads        # noqa: F401,E402
from . import duplicate_charges      # noqa: F401,E402
from . import reconciliation         # noqa: F401,E402
from . import vat                    # noqa: F401,E402
from . import low_confidence         # noqa: F401,E402
