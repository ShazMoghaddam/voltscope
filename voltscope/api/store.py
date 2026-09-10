"""Storage abstraction for bill records and processing history.

The review app depends only on the :class:`BillStore` interface, never on a
concrete backend. Segment 3 shipped :class:`InMemoryBillStore`; segment 4 adds
:class:`~voltscope.api.sqlite_store.SqliteBillStore`, an implementation of the
same interface, so persistence slots in by swapping the store passed to
``create_app`` with no change to the API, service, or frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models import BillRecord, HistoryEntry


class BillStore(ABC):
    """Interface every storage backend implements."""

    # --- record CRUD ---
    @abstractmethod
    def add(self, record: BillRecord) -> BillRecord:
        """Persist a new record and return it."""

    @abstractmethod
    def get(self, record_id: str) -> Optional[BillRecord]:
        """Return the record with this id, or ``None``."""

    @abstractmethod
    def list(self) -> List[BillRecord]:
        """Return all records, newest first."""

    @abstractmethod
    def update(self, record: BillRecord) -> BillRecord:
        """Persist changes to an existing record and return it."""

    @abstractmethod
    def delete(self, record_id: str) -> bool:
        """Remove a record. Return ``True`` if it existed."""

    # --- processing history ---
    @abstractmethod
    def record_event(self, bill_id: Optional[str], event: str, detail: Optional[str] = None) -> None:
        """Append a processing-history event."""

    @abstractmethod
    def history(self, limit: int = 100) -> List[HistoryEntry]:
        """Return recent history events, newest first."""


class InMemoryBillStore(BillStore):
    """A process-lifetime store backed by dicts. Not persistent."""

    def __init__(self) -> None:
        self._records: Dict[str, BillRecord] = {}
        self._history: List[HistoryEntry] = []

    def add(self, record: BillRecord) -> BillRecord:
        self._records[record.id] = record
        return record

    def get(self, record_id: str) -> Optional[BillRecord]:
        return self._records.get(record_id)

    def list(self) -> List[BillRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def update(self, record: BillRecord) -> BillRecord:
        self._records[record.id] = record
        return record

    def delete(self, record_id: str) -> bool:
        return self._records.pop(record_id, None) is not None

    def record_event(self, bill_id: Optional[str], event: str, detail: Optional[str] = None) -> None:
        self._history.append(
            HistoryEntry(bill_id=bill_id, event=event, detail=detail, at=datetime.now(timezone.utc))
        )

    def history(self, limit: int = 100) -> List[HistoryEntry]:
        return list(reversed(self._history))[:limit]
