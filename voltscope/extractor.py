"""Bill extraction: encode a file, call Claude, parse the JSON response.

This module owns the one external dependency (the Anthropic API) and the
brittle boundary where a model reply becomes structured data. It knows nothing
about validation, serialisation, or persistence, so those concerns can change
independently.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from .config import Settings
from .logging_config import get_logger

logger = get_logger(__name__)

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
# HEIC/HEIF (iPhone photos) are converted to JPEG before sending, since neither
# the API nor most tooling accepts HEIC directly.
HEIC_EXTENSIONS = {".heic", ".heif"}
SUPPORTED_EXTENSIONS = {".pdf", *IMAGE_MEDIA_TYPES, *HEIC_EXTENSIONS}

_PROMPT_PATH = Path(__file__).parent / "prompts" / "extraction_system.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_USER_INSTRUCTION = "Extract this energy bill into the required JSON schema."
_MULTI_PAGE_INSTRUCTION = (
    "These images are the pages of a SINGLE energy bill. Read all of them "
    "together and extract the one bill into the required JSON schema."
)
_MAX_ATTEMPTS = 2
_MAX_TOKENS = 8000


class ExtractionError(Exception):
    """Raised when a file cannot be read or encoded for extraction."""


def _heic_to_jpeg(data: bytes) -> bytes:
    """Convert HEIC/HEIF bytes to JPEG bytes.

    Requires ``pillow`` and ``pillow-heif`` (both in requirements). Imported
    lazily so the rest of the package works even if they are absent.
    """
    import io

    try:
        import pillow_heif
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise ExtractionError(
            "HEIC support needs 'pillow' and 'pillow-heif'; install requirements.txt."
        ) from exc

    pillow_heif.register_heif_opener()
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the caller
        raise ExtractionError(f"could not decode HEIC image: {exc}") from exc
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _content_block(data: bytes, ext: str) -> Optional[Dict[str, Any]]:
    """Return one image/document content block for a file's bytes.

    HEIC/HEIF is converted to JPEG. Returns ``None`` for an unsupported
    extension. This is the shared piece behind single- and multi-page builders.
    """
    ext = ext.lower()
    if ext == ".pdf":
        encoded = base64.standard_b64encode(data).decode("utf-8")
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": encoded},
        }

    if ext in HEIC_EXTENSIONS:
        data = _heic_to_jpeg(data)
        media_type = "image/jpeg"
    elif ext in IMAGE_MEDIA_TYPES:
        media_type = IMAGE_MEDIA_TYPES[ext]
    else:
        return None

    encoded = base64.standard_b64encode(data).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": encoded},
    }


def build_content_from_bytes(data: bytes, ext: str) -> Optional[List[Dict[str, Any]]]:
    """Return the Anthropic message content blocks for a single file's bytes.

    ``ext`` is the file extension including the dot (e.g. ``.pdf``). HEIC/HEIF is
    transparently converted to JPEG. Returns ``None`` for an unsupported
    extension.
    """
    block = _content_block(data, ext)
    if block is None:
        return None
    return [block, {"type": "text", "text": _USER_INSTRUCTION}]


def build_content_from_pages(
    pages: List[Tuple[bytes, str]]
) -> Optional[List[Dict[str, Any]]]:
    """Return message content for several pages of ONE bill.

    ``pages`` is a list of ``(data, filename)`` in page order. Unsupported pages
    are skipped; returns ``None`` if none are usable.
    """
    blocks: List[Dict[str, Any]] = []
    for data, filename in pages:
        block = _content_block(data, Path(filename).suffix)
        if block is not None:
            blocks.append(block)
    if not blocks:
        return None
    blocks.append({"type": "text", "text": _MULTI_PAGE_INSTRUCTION})
    return blocks


def build_content(path: Path) -> Optional[List[Dict[str, Any]]]:
    """Return the Anthropic message content blocks for a single file on disk.

    Returns ``None`` for an unsupported file extension. Raises
    :class:`ExtractionError` if the file cannot be read.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ExtractionError(f"could not read {path}: {exc}") from exc
    return build_content_from_bytes(data, path.suffix)


def parse_json(text: str) -> Dict[str, Any]:
    """Parse the model reply into a dict, tolerating stray fences or prose.

    Mirrors the original spike: strip a leading ``` fence, then fall back to the
    outermost ``{ ... }`` span if a direct parse fails.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


def _complete(
    client: anthropic.Anthropic,
    settings: Settings,
    content: List[Dict[str, Any]],
    label: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Send content to the model and parse the reply, with one retry.

    Shared by :func:`extract_one` (disk) and :func:`extract_document` (bytes) so
    both paths have identical extraction behaviour.
    """
    last_err: Optional[str] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            msg = client.messages.create(
                model=settings.model,
                max_tokens=_MAX_TOKENS,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            raw = "".join(b.text for b in msg.content if b.type == "text")
            return parse_json(raw), None
        except (anthropic.APIError, json.JSONDecodeError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "extraction attempt %d/%d failed for %s: %s",
                attempt, _MAX_ATTEMPTS, label, last_err,
            )
        except Exception as exc:  # noqa: BLE001 - keep the batch alive on any error
            last_err = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "unexpected error on attempt %d/%d for %s: %s",
                attempt, _MAX_ATTEMPTS, label, last_err,
            )
    return None, last_err


def extract_one(
    client: anthropic.Anthropic, settings: Settings, path: Path
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract a single bill from a file on disk.

    Returns ``(bill_dict, None)`` on success or ``(None, error_message)`` on
    failure, so the batch loop can continue past a bad file rather than dying.
    """
    try:
        content = build_content(path)
    except ExtractionError as exc:
        return None, str(exc)
    if content is None:
        return None, f"unsupported file type: {path}"
    return _complete(client, settings, content, path.name)


def extract_document(
    client: anthropic.Anthropic,
    settings: Settings,
    *,
    data: bytes,
    filename: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract a single bill from in-memory bytes (used by the review app)."""
    content = build_content_from_bytes(data, Path(filename).suffix)
    if content is None:
        return None, f"unsupported file type: {filename}"
    return _complete(client, settings, content, filename)


def extract_pages(
    client: anthropic.Anthropic,
    settings: Settings,
    *,
    pages: List[Tuple[bytes, str]],
    label: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract one bill from several pages (images/PDFs) sent in a single call."""
    content = build_content_from_pages(pages)
    if content is None:
        return None, f"no supported pages in {label}"
    return _complete(client, settings, content, label)
