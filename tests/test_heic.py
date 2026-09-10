"""Test that HEIC/HEIF input is converted to JPEG for extraction."""

from __future__ import annotations

import base64
import io

import pytest

from voltscope.extractor import SUPPORTED_EXTENSIONS, build_content_from_bytes


def _make_heic_bytes() -> bytes:
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image

    pillow_heif.register_heif_opener()
    img = Image.new("RGB", (24, 24), (120, 180, 90))
    buf = io.BytesIO()
    img.save(buf, format="HEIF")
    return buf.getvalue()


def test_heic_extension_supported():
    assert ".heic" in SUPPORTED_EXTENSIONS
    assert ".heif" in SUPPORTED_EXTENSIONS


def test_heic_is_converted_to_jpeg():
    data = _make_heic_bytes()
    content = build_content_from_bytes(data, ".HEIC")  # uppercase to check normalisation
    assert content is not None
    block = content[0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"
    decoded = base64.b64decode(block["source"]["data"])
    assert decoded[:3] == b"\xff\xd8\xff"  # JPEG magic bytes
