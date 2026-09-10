"""Review service: ingest uploads, re-validate edits, coordinate the store.

Extraction is injected as ``extract_fn`` so the service (and its tests) do not
depend on a live Anthropic client. Production wires in an Anthropic-backed
function via :func:`make_anthropic_extract_fn`; tests pass a stub.

Validation always runs on the plain extracted/edited dict, exactly as the CLI
does, so findings are identical to those produced elsewhere. Editing re-runs
validation, so a corrected field immediately updates the findings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Settings
from ..engine import run_checks
from ..intelligence import IntelligenceReport, compute_intelligence
from ..logging_config import get_logger
from ..models import Bill, BillRecord, DashboardStats, HistoryEntry, ProcessingStatus
from .dashboard import compute_dashboard
from .store import BillStore

logger = get_logger(__name__)

# (data, filename) -> (extracted_dict | None, error | None)
ExtractFn = Callable[[bytes, str], Tuple[Optional[Dict[str, Any]], Optional[str]]]
# [(data, filename), ...] (pages of one bill) -> (extracted_dict | None, error | None)
ExtractPagesFn = Callable[[List[Tuple[bytes, str]]], Tuple[Optional[Dict[str, Any]], Optional[str]]]


def _anthropic_client_box(settings: Settings):
    """A lazily-initialised client holder shared by the extract functions."""
    box: Dict[str, Any] = {}

    def get():
        if "client" not in box:
            import anthropic
            box["client"] = anthropic.Anthropic()
        return box["client"]

    return get


def make_anthropic_extract_fn(settings: Settings) -> ExtractFn:
    """Build a single-file extract function backed by the Anthropic API.

    The client is constructed lazily on first use so importing the app does not
    require an API key; only an actual upload does.
    """
    from ..extractor import extract_document

    get_client = _anthropic_client_box(settings)

    def _extract(data: bytes, filename: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not settings.has_api_key:
            return None, "ANTHROPIC_API_KEY is not set; cannot extract."
        return extract_document(get_client(), settings, data=data, filename=filename)

    return _extract


def make_anthropic_pages_fn(settings: Settings) -> ExtractPagesFn:
    """Build a multi-page extract function backed by the Anthropic API."""
    from ..extractor import extract_pages

    get_client = _anthropic_client_box(settings)

    def _extract(pages: List[Tuple[bytes, str]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        if not settings.has_api_key:
            return None, "ANTHROPIC_API_KEY is not set; cannot extract."
        label = pages[0][1] if pages else "merged bill"
        return extract_pages(get_client(), settings, pages=pages, label=label)

    return _extract


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_bill(data: Dict[str, Any]) -> Optional[Bill]:
    """Validate a dict into a Bill, tolerating an imperfect payload.

    Findings are computed from the dict regardless, so this only affects the
    typed view returned to the client, never validation correctness.
    """
    try:
        return Bill.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bill did not validate into schema, keeping raw values: %s", exc)
        try:
            return Bill.model_construct(**data)
        except Exception:  # noqa: BLE001
            return None


class ReviewService:
    """Coordinates extraction, validation, storage, and edits."""

    def __init__(
        self,
        store: BillStore,
        extract_fn: ExtractFn,
        high_rate_multiplier: float = 1.3,
        extract_pages_fn: Optional[ExtractPagesFn] = None,
    ) -> None:
        self._store = store
        self._extract_fn = extract_fn
        self._extract_pages_fn = extract_pages_fn
        self._high_rate_multiplier = high_rate_multiplier

    def _store_result(
        self,
        filename: str,
        raw: Optional[Dict[str, Any]],
        err: Optional[str],
    ) -> BillRecord:
        """Build, store, and log a record from an extraction result."""
        now = _now()
        if err or raw is None:
            record = BillRecord(
                id=uuid.uuid4().hex, filename=filename, status=ProcessingStatus.FAILED,
                bill=None, findings=[], error=err or "extraction returned no data",
                created_at=now, updated_at=now,
            )
            logger.warning("ingest failed for %s: %s", filename, record.error)
            self._store.add(record)
            self._store.record_event(record.id, "failed", record.error)
            return record

        record = BillRecord(
            id=uuid.uuid4().hex, filename=filename, status=ProcessingStatus.PROCESSED,
            bill=_to_bill(raw), findings=run_checks(raw), error=None,
            created_at=now, updated_at=now,
        )
        self._store.add(record)
        self._store.record_event(record.id, "processed", f"{len(record.findings)} findings")
        return record

    def ingest(self, filename: str, data: bytes) -> BillRecord:
        """Extract and validate one uploaded file, storing the result."""
        raw, err = self._extract_fn(data, filename)
        return self._store_result(filename, raw, err)

    def ingest_many(self, files: List[Tuple[str, bytes]]) -> List[BillRecord]:
        """Ingest several files, one record each. One failure never blocks the rest."""
        return [self.ingest(name, data) for name, data in files]

    def ingest_merged(self, files: List[Tuple[str, bytes]]) -> BillRecord:
        """Treat several uploaded files as the pages of ONE bill -> one record."""
        if self._extract_pages_fn is None:
            first = files[0][0] if files else "merged bill"
            return self._store_result(first, None, "multi-page extraction is not configured.")
        pages = [(data, name) for name, data in files]
        raw, err = self._extract_pages_fn(pages)
        first = files[0][0] if files else "merged bill"
        display = first if len(files) <= 1 else f"{first} (+{len(files) - 1} pages)"
        return self._store_result(display, raw, err)

    def get(self, record_id: str) -> Optional[BillRecord]:
        return self._store.get(record_id)

    def list(self) -> List[BillRecord]:
        return self._store.list()

    def delete(self, record_id: str) -> bool:
        deleted = self._store.delete(record_id)
        if deleted:
            self._store.record_event(record_id, "deleted", None)
        return deleted

    def history(self, limit: int = 100) -> List[HistoryEntry]:
        return self._store.history(limit)

    def dashboard(self) -> DashboardStats:
        return compute_dashboard(self._store.list())

    def intelligence(self) -> IntelligenceReport:
        return compute_intelligence(self._store.list(), multiplier=self._high_rate_multiplier)

    def apply_edits(self, record_id: str, bill_data: Dict[str, Any]) -> Optional[BillRecord]:
        """Replace a record's bill fields with edited values and re-validate."""
        record = self._store.get(record_id)
        if record is None:
            return None
        record.bill = _to_bill(bill_data)
        record.findings = run_checks(bill_data)
        record.status = ProcessingStatus.EDITED
        record.updated_at = _now()
        self._store.update(record)
        self._store.record_event(record_id, "edited", f"{len(record.findings)} findings")
        return record
