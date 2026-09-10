"""Segment follow-up tests: multi-page bills.

Stubs stand in for extraction so these run without an Anthropic key. They check
that several pages are combined into one content payload and one record.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from voltscope.api.app import create_app
from voltscope.api.service import ReviewService
from voltscope.api.store import InMemoryBillStore
from voltscope.extractor import build_content_from_pages

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = json.loads((FIXTURES / "messy_bill.json").read_text(encoding="utf-8"))


def test_build_content_from_pages_combines_images():
    pages = [(b"\x89PNG-a", "p1.png"), (b"\x89PNG-b", "p2.png"), (b"%PDF-c", "p3.pdf")]
    content = build_content_from_pages(pages)
    # three media blocks + one trailing instruction
    assert len(content) == 4
    assert [b["type"] for b in content[:3]] == ["image", "image", "document"]
    assert content[-1]["type"] == "text"


def test_build_content_from_pages_skips_unsupported():
    pages = [(b"x", "notes.txt"), (b"\x89PNG", "page.png")]
    content = build_content_from_pages(pages)
    assert len(content) == 2  # one image + instruction
    assert content[0]["type"] == "image"


def test_ingest_merged_makes_one_record():
    captured = {}

    def pages_fn(pages):
        captured["n"] = len(pages)
        return json.loads(json.dumps(MESSY)), None

    svc = ReviewService(InMemoryBillStore(), extract_fn=lambda d, f: (None, "unused"),
                        extract_pages_fn=pages_fn)
    rec = svc.ingest_merged([("a.png", b"1"), ("b.png", b"2"), ("c.png", b"3")])
    assert captured["n"] == 3
    assert rec.status.value == "processed"
    assert "(+2 pages)" in rec.filename


def test_ingest_merged_without_pages_fn_fails_cleanly():
    svc = ReviewService(InMemoryBillStore(), extract_fn=lambda d, f: (None, "x"))
    rec = svc.ingest_merged([("a.png", b"1"), ("b.png", b"2")])
    assert rec.status.value == "failed"


def test_merge_upload_endpoint():
    def pages_fn(pages):
        return json.loads(json.dumps(MESSY)), None

    app = create_app(store=InMemoryBillStore(),
                     extract_fn=lambda d, f: (None, "single not used"),
                     extract_pages_fn=pages_fn)
    client = TestClient(app)
    resp = client.post(
        "/api/bills?merge=true",
        files=[("files", ("p1.png", b"a", "image/png")),
               ("files", ("p2.png", b"b", "image/png"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1  # one merged record
    assert body[0]["status"] == "processed"
