"""FastAPI review application.

``create_app`` builds an app around an injectable store and extract function, so
tests can pass an in-memory store and a stub extractor, and deployment can pass
a SQLite store, all without touching the routes. Use the ``get_app`` factory for
``uvicorn --factory voltscope.api.app:get_app``.

The public API is documented via OpenAPI at ``/docs`` (Swagger) and ``/redoc``.
Authentication, when enabled, is an ``X-API-Key`` header (see ``auth.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from ..config import Settings
from ..intelligence import IntelligenceReport
from ..logging_config import configure_logging, get_logger
from ..models import BillRecord, DashboardStats, HistoryEntry
from .auth import make_require_api_key
from .exporters import record_to_json, records_to_csv, records_to_xlsx_bytes
from .service import (
    ExtractFn, ExtractPagesFn, ReviewService,
    make_anthropic_extract_fn, make_anthropic_pages_fn,
)
from .sqlite_store import SqliteBillStore
from .store import BillStore

logger = get_logger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CSV_SHEETS = ("bills", "supply_points", "charges", "findings")

_DESCRIPTION = """
Voltscope extracts structured data from UK commercial energy bills, validates it
with deterministic checks, and lets you review, correct, and export the results.

* **Upload** one or more PDFs or images to extract and validate them.
* **Review & edit** extracted fields; saving re-runs validation.
* **Export** as JSON, Excel, or CSV.
* **Dashboard** aggregates suppliers, spend, status, and upcoming renewals.

Authentication (when enabled) uses an `X-API-Key` header.
""".strip()

_TAGS = [
    {"name": "bills", "description": "Upload, list, fetch, edit, and delete bills."},
    {"name": "export", "description": "Export records as JSON, Excel, or CSV."},
    {"name": "dashboard", "description": "Portfolio aggregates and processing history."},
    {"name": "system", "description": "Health and readiness."},
]


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_download(payload: Dict[str, Any], filename: str) -> Response:
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def create_app(
    store: Optional[BillStore] = None,
    extract_fn: Optional[ExtractFn] = None,
    settings: Optional[Settings] = None,
    extract_pages_fn: Optional[ExtractPagesFn] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    store = store if store is not None else SqliteBillStore(settings.db_path)
    service = ReviewService(
        store,
        extract_fn or make_anthropic_extract_fn(settings),
        high_rate_multiplier=settings.high_rate_multiplier,
        extract_pages_fn=extract_pages_fn or make_anthropic_pages_fn(settings),
    )
    require_api_key = make_require_api_key(settings)

    app = FastAPI(
        title="Voltscope Review",
        version="0.5.0",
        description=_DESCRIPTION,
        openapi_tags=_TAGS,
    )

    # --- open routes (no auth) ---
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/health", tags=["system"])
    def health() -> Dict[str, Any]:
        """Liveness plus whether extraction and auth are configured."""
        return {
            "status": "ok",
            "extraction_available": settings.has_api_key,
            "auth_required": settings.auth_enabled,
        }

    # --- protected API ---
    api = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])

    @api.post("/bills", response_model=List[BillRecord], tags=["bills"])
    async def upload_bills(
        files: List[UploadFile],
        merge: bool = Query(False, description="Treat all uploaded files as pages of one bill."),
    ) -> List[BillRecord]:
        """Upload bills. By default each file is one bill; with ``merge=true`` all
        uploaded files are treated as the pages of a single multi-page bill."""
        if not files:
            raise HTTPException(status_code=400, detail="No files uploaded.")
        payloads = [(f.filename or "unnamed", await f.read()) for f in files]
        if merge:
            return [service.ingest_merged(payloads)]
        return service.ingest_many(payloads)

    @api.get("/bills", response_model=List[BillRecord], tags=["bills"])
    def list_bills() -> List[BillRecord]:
        """List all records, newest first."""
        return service.list()

    @api.get("/bills/{record_id}", response_model=BillRecord, tags=["bills"])
    def get_bill(record_id: str) -> BillRecord:
        """Fetch one record by id."""
        record = service.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return record

    @api.put("/bills/{record_id}", response_model=BillRecord, tags=["bills"])
    def edit_bill(record_id: str, bill: Dict[str, Any] = Body(...)) -> BillRecord:
        """Replace a record's bill fields and re-run validation."""
        record = service.apply_edits(record_id, bill)
        if record is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return record

    @api.delete("/bills/{record_id}", status_code=204, tags=["bills"])
    def delete_bill(record_id: str) -> Response:
        """Delete a record."""
        if not service.delete(record_id):
            raise HTTPException(status_code=404, detail="Bill not found.")
        return Response(status_code=204)

    @api.get("/bills/{record_id}/export.json", tags=["export"])
    def export_bill_json(record_id: str) -> Response:
        record = service.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return _json_download(record_to_json(record), f"{record_id}.json")

    @api.get("/bills/{record_id}/export.xlsx", tags=["export"])
    def export_bill_xlsx(record_id: str) -> Response:
        record = service.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return _xlsx_response(records_to_xlsx_bytes([record]), f"{record_id}.xlsx")

    @api.get("/bills/{record_id}/export.csv", tags=["export"])
    def export_bill_csv(record_id: str) -> Response:
        record = service.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Bill not found.")
        return _csv_response(records_to_csv([record], "bills"), f"{record_id}.csv")

    @api.get("/export.xlsx", tags=["export"])
    def export_all_xlsx() -> Response:
        """Export every record as a four-sheet Excel workbook."""
        return _xlsx_response(records_to_xlsx_bytes(service.list()), "voltscope_bills.xlsx")

    @api.get("/export.csv", tags=["export"])
    def export_all_csv(
        sheet: str = Query("bills", description="One of: " + ", ".join(_CSV_SHEETS))
    ) -> Response:
        """Export one flattening (bills, supply_points, charges, findings) as CSV."""
        if sheet not in _CSV_SHEETS:
            raise HTTPException(status_code=400, detail=f"Unknown sheet '{sheet}'.")
        return _csv_response(records_to_csv(service.list(), sheet), f"voltscope_{sheet}.csv")

    @api.get("/dashboard", response_model=DashboardStats, tags=["dashboard"])
    def dashboard() -> DashboardStats:
        """Portfolio aggregates: status, severity, spend, suppliers, renewals."""
        return service.dashboard()

    @api.get("/intelligence", response_model=IntelligenceReport, tags=["dashboard"])
    def intelligence() -> IntelligenceReport:
        """Deterministic portfolio insights: renewals, estimated reads, duplicate
        charges, high unit rates, spend, supplier comparison, and statistics."""
        return service.intelligence()

    @api.get("/history", response_model=List[HistoryEntry], tags=["dashboard"])
    def history(limit: int = 100) -> List[HistoryEntry]:
        """Recent processing events, newest first."""
        return service.history(limit)

    app.include_router(api)
    return app


def get_app() -> FastAPI:
    """Factory for ``uvicorn --factory voltscope.api.app:get_app``.

    Using a factory keeps importing this module side-effect free (no database
    file is opened at import time, which matters for tests).
    """
    return create_app()
