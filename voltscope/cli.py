"""Command-line orchestration: the ``./bills`` -> ``./out`` batch loop.

Wires config, extractor, engine, and serialisation together and prints the
human-facing report (per-bill summary + rollup). Diagnostics go to logging; the
report goes to stdout, because it is the product's actual output.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from .config import Settings
from .engine import run_checks
from .extractor import SUPPORTED_EXTENSIONS, extract_one, extract_pages
from .logging_config import configure_logging, get_logger
from .models import Bill, Finding, Severity

logger = get_logger(__name__)


def _serialise_bill(bill_dict: Dict[str, Any]) -> Any:
    """Return a stable, typed dump of the bill for the output file.

    Validates into the :class:`Bill` model (stable key order, complete schema
    keys), and falls back to writing the raw dict if the payload does not fit
    the schema, so an extraction is never lost to a serialisation quirk.
    """
    try:
        return Bill.model_validate(bill_dict).model_dump(mode="json", by_alias=True)
    except Exception as exc:  # noqa: BLE001 - never lose output over a schema mismatch
        logger.warning("bill did not fit schema, writing raw extraction: %s", exc)
        return bill_dict


def _severity_summary(findings: List[Finding]) -> str:
    """Compact 'E:2 W:3 I:1' breakdown for a list of findings."""
    counts = Counter(f.severity for f in findings)
    return (
        f"E:{counts[Severity.ERROR]} "
        f"W:{counts[Severity.WARNING]} "
        f"I:{counts[Severity.INFO]}"
    )


def summarise(name: str, bill: Optional[Dict[str, Any]], findings: List[Finding]) -> None:
    """Print the per-bill report block."""
    print(f"\n=== {name} ===")
    if bill is None:
        print("  extraction FAILED")
        return
    sp = bill.get("supply_points") or []
    print(f"  supplier: {bill.get('supplier_name')}")
    print(f"  customer: {bill.get('customer_name')}")
    print(f"  period:   {bill.get('billing_period_start')} -> {bill.get('billing_period_end')}")
    print(
        f"  sites:    {len(sp)}   total: "
        f"{bill.get('currency') or ''} {bill.get('total_gbp')}"
    )
    if findings:
        print(f"  FINDINGS ({len(findings)})  [{_severity_summary(findings)}]:")
        for f in findings:
            print(f"    - [{f.severity.value}] {f.message}")
    else:
        print("  FINDINGS: none")


def run(settings: Settings) -> int:
    """Process every supported file in the bills directory. Returns an exit code."""
    configure_logging(settings.log_level)

    if not settings.has_api_key:
        logger.error("ANTHROPIC_API_KEY is not set.")
        return 1
    if not settings.bills_dir.is_dir():
        logger.error(
            "No bills directory at ./%s. Add bills there and retry.", settings.bills_dir
        )
        return 1
    settings.out_dir.mkdir(parents=True, exist_ok=True)

    loose_files = sorted(
        p for p in settings.bills_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    # Each sub-directory is treated as one multi-page bill (its files are pages).
    subdirs = sorted(p for p in settings.bills_dir.iterdir() if p.is_dir())
    subdirs = [d for d in subdirs
               if any(f.suffix.lower() in SUPPORTED_EXTENSIONS for f in d.iterdir())]

    if not loose_files and not subdirs:
        logger.error("No PDFs, images, or bill sub-folders in ./%s.", settings.bills_dir)
        return 1

    client = anthropic.Anthropic()
    logger.info("Model: %s   Bills: %d", settings.model, len(loose_files) + len(subdirs))

    rollup: List[Tuple[str, str, int, str]] = []

    def _handle(display: str, out_stem: str, bill: Optional[Dict[str, Any]], err: Optional[str]) -> None:
        if err or bill is None:
            logger.error("%s: %s", display, err)
            print(f"\n=== {display} ===\n  ERROR: {err}")
            rollup.append((display, "fail", 0, ""))
            return
        findings = run_checks(bill)
        out_path = settings.out_dir / (out_stem + ".json")
        out_path.write_text(
            json.dumps(_serialise_bill(bill), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        summarise(display, bill, findings)
        rollup.append((display, "ok", len(findings), _severity_summary(findings)))

    for path in loose_files:
        bill, err = extract_one(client, settings, path)
        _handle(path.name, path.stem, bill, err)

    for folder in subdirs:
        pages_paths = sorted(f for f in folder.iterdir()
                             if f.suffix.lower() in SUPPORTED_EXTENSIONS)
        pages = [(p.read_bytes(), p.name) for p in pages_paths]
        bill, err = extract_pages(client, settings, pages=pages, label=folder.name)
        _handle(f"{folder.name}/ ({len(pages)} pages)", folder.name, bill, err)

    print("\n" + "-" * 60)
    print("ROLLUP")
    for name, status, n, sev in rollup:
        sev_col = f"  {sev}" if sev else ""
        print(f"  {status:4}  {n:2} findings{sev_col:14}  {name}")
    print(f"\nPer-bill JSON written to ./{settings.out_dir}/")
    print(
        "Now do the part that matters: open each JSON next to the real bill and "
        "check the money fields by hand. Extraction accuracy is the product."
    )
    return 0


def main() -> None:
    """Entry point used by both ``python -m voltscope`` and the extract.py shim."""
    settings = Settings.from_env()
    sys.exit(run(settings))


if __name__ == "__main__":
    main()
