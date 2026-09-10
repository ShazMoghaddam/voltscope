"""SQLite-backed :class:`BillStore`.

Stores the full record losslessly as JSON, plus a set of scalar columns
(supplier, invoice date, contract end date, status, total, severity counts) so
the dashboard can be built with plain queries. Validation results are also kept
in a ``findings`` table, and a ``history`` table records processing events.

Connections are short-lived (one per operation) so the store is safe to use
from the worker threads FastAPI/uvicorn may run handlers on, with SQLite's own
file locking handling concurrency. There are no formulas or external files, so
nothing here needs recalculation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..dateparsing import parse_date
from ..logging_config import get_logger
from ..models import BillRecord, HistoryEntry, Severity
from .store import BillStore

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
    id                TEXT PRIMARY KEY,
    filename          TEXT NOT NULL,
    status            TEXT NOT NULL,
    supplier_name     TEXT,
    customer_name     TEXT,
    invoice_date      TEXT,
    invoice_date_iso  TEXT,
    contract_end_date TEXT,
    contract_end_iso  TEXT,
    total_gbp         REAL,
    error             TEXT,
    error_count       INTEGER NOT NULL DEFAULT 0,
    warning_count     INTEGER NOT NULL DEFAULT 0,
    info_count        INTEGER NOT NULL DEFAULT 0,
    data              TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id        TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    severity       TEXT NOT NULL,
    category       TEXT NOT NULL,
    code           TEXT NOT NULL,
    message        TEXT NOT NULL,
    affected_field TEXT,
    recommendation TEXT
);

CREATE TABLE IF NOT EXISTS history (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id TEXT,
    event   TEXT NOT NULL,
    detail  TEXT,
    at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_bills_created ON bills(created_at);
CREATE INDEX IF NOT EXISTS ix_findings_bill ON findings(bill_id);
CREATE INDEX IF NOT EXISTS ix_history_at ON history(at);
"""


def _iso(value: Optional[str]) -> Optional[str]:
    """Normalise a printed date to ISO ``YYYY-MM-DD``, or ``None``."""
    parsed = parse_date(value)
    return parsed.date().isoformat() if parsed else None


class SqliteBillStore(BillStore):
    """Persistent store backed by a SQLite database file."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(_SCHEMA)

    # --- helpers ---
    @staticmethod
    def _scalars(record: BillRecord) -> Tuple[Any, ...]:
        bill = record.bill
        supplier = getattr(bill, "supplier_name", None) if bill else None
        customer = getattr(bill, "customer_name", None) if bill else None
        invoice_date = getattr(bill, "invoice_date", None) if bill else None
        contract_end = getattr(bill, "contract_end_date", None) if bill else None
        total = getattr(bill, "total_gbp", None) if bill else None
        counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        for f in record.findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        return (
            record.id, record.filename, record.status.value,
            supplier, customer, invoice_date, _iso(invoice_date),
            contract_end, _iso(contract_end),
            total if isinstance(total, (int, float)) else None,
            record.error,
            counts["ERROR"], counts["WARNING"], counts["INFO"],
            record.model_dump_json(by_alias=True),
            record.created_at.isoformat(), record.updated_at.isoformat(),
        )

    def _write_findings(self, con: sqlite3.Connection, record: BillRecord) -> None:
        con.execute("DELETE FROM findings WHERE bill_id = ?", (record.id,))
        con.executemany(
            "INSERT INTO findings "
            "(bill_id, severity, category, code, message, affected_field, recommendation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (record.id, f.severity.value, f.category.value, f.code,
                 f.message, f.affected_field, f.recommendation)
                for f in record.findings
            ],
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> BillRecord:
        return BillRecord.model_validate(json.loads(row["data"]))

    # --- CRUD ---
    def add(self, record: BillRecord) -> BillRecord:
        with self._connect() as con:
            con.execute(
                "INSERT INTO bills (id, filename, status, supplier_name, customer_name, "
                "invoice_date, invoice_date_iso, contract_end_date, contract_end_iso, "
                "total_gbp, error, error_count, warning_count, info_count, data, "
                "created_at, updated_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._scalars(record),
            )
            self._write_findings(con, record)
        return record

    def get(self, record_id: str) -> Optional[BillRecord]:
        with self._connect() as con:
            row = con.execute("SELECT data FROM bills WHERE id = ?", (record_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list(self) -> List[BillRecord]:
        with self._connect() as con:
            rows = con.execute("SELECT data FROM bills ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(r) for r in rows]

    def update(self, record: BillRecord) -> BillRecord:
        with self._connect() as con:
            con.execute(
                "UPDATE bills SET filename=?, status=?, supplier_name=?, customer_name=?, "
                "invoice_date=?, invoice_date_iso=?, contract_end_date=?, contract_end_iso=?, "
                "total_gbp=?, error=?, error_count=?, warning_count=?, info_count=?, data=?, "
                "created_at=?, updated_at=? WHERE id=?",
                self._scalars(record)[1:] + (record.id,),
            )
            self._write_findings(con, record)
        return record

    def delete(self, record_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute("DELETE FROM bills WHERE id = ?", (record_id,))
            return cur.rowcount > 0

    # --- history ---
    def record_event(self, bill_id: Optional[str], event: str, detail: Optional[str] = None) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO history (bill_id, event, detail, at) VALUES (?, ?, ?, ?)",
                (bill_id, event, detail, datetime.now(timezone.utc).isoformat()),
            )

    def history(self, limit: int = 100) -> List[HistoryEntry]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT bill_id, event, detail, at FROM history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            HistoryEntry(
                bill_id=r["bill_id"], event=r["event"], detail=r["detail"],
                at=datetime.fromisoformat(r["at"]),
            )
            for r in rows
        ]
