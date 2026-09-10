"""API-key authentication.

Authentication is opt-in: if ``VOLTSCOPE_API_KEYS`` is unset, the API is open
(convenient for local use), and a warning is logged. If one or more keys are
configured, every ``/api`` route except ``/api/health`` requires a matching
``X-API-Key`` header. Using :class:`APIKeyHeader` also advertises the scheme in
the OpenAPI docs, so the ``/docs`` page gets an Authorize button.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ..config import Settings
from ..logging_config import get_logger

logger = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def make_require_api_key(settings: Settings) -> Callable[[Optional[str]], None]:
    """Build the auth dependency bound to these settings."""
    if not settings.auth_enabled:
        logger.warning("No VOLTSCOPE_API_KEYS set: the API is unauthenticated.")

    def require_api_key(key: Optional[str] = Security(api_key_header)) -> None:
        if not settings.auth_enabled:
            return
        if not key or key not in settings.api_keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key.",
            )

    return require_api_key
