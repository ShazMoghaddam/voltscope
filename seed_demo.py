#!/usr/bin/env python3
"""Load the bundled fixture bills into the local database for a no-key demo.

Lets you explore the full review, dashboard, and insights experience on real,
deterministic data without an Anthropic API key (extraction is the only step a
key is needed for). Run from the project root with the virtual environment
active:

    python seed_demo.py

Then start the app (``python -m voltscope.api`` or ``./run.sh``) and refresh the
browser. Re-running clears the previous demo bills first, so you always get a
clean set.
"""

from __future__ import annotations

import glob
import json
import uuid
from datetime import datetime, timezone

from voltscope.api.sqlite_store import SqliteBillStore
from voltscope.config import Settings
from voltscope.engine import run_checks
from voltscope.models import BillRecord, ProcessingStatus


def main() -> None:
    settings = Settings.from_env()
    store = SqliteBillStore(settings.db_path)

    existing = store.list()
    for record in existing:
        store.delete(record.id)
    if existing:
        print(f"cleared {len(existing)} existing bill(s)")

    loaded = 0
    for path in sorted(glob.glob("tests/fixtures/*_bill.json")):
        if path.endswith(".flags.json"):
            continue
        bill = json.loads(open(path, encoding="utf-8").read())
        now = datetime.now(timezone.utc)
        record = BillRecord(
            id=uuid.uuid4().hex,
            filename=path.split("/")[-1],
            status=ProcessingStatus.PROCESSED,
            bill=bill,
            findings=run_checks(bill),
            created_at=now,
            updated_at=now,
        )
        store.add(record)
        store.record_event(record.id, "processed", f"{len(record.findings)} findings")
        loaded += 1
        print("loaded", record.filename)

    if not loaded:
        print("No fixture bills found. Run this from the project root.")
        return
    print(f"\nSeeded {loaded} demo bills into {settings.db_path}.")
    print("Start the app (./run.sh or python -m voltscope.api), then refresh the browser.")


if __name__ == "__main__":
    main()
