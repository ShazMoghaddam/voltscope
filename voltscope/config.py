"""Application configuration for Voltscope.

Settings are loaded once from environment variables (and an optional ``.env``
file) into a single immutable :class:`Settings` object. No other module reads
``os.environ`` directly; they all receive ``Settings``. This is what lets the
CLI and, later, the web layer construct configuration differently without the
extractor or validator knowing or caring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; .env simply won't auto-load.
    load_dotenv = None  # type: ignore[assignment]

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_BILLS_DIR = "bills"
DEFAULT_OUT_DIR = "out"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_DB_PATH = "voltscope.db"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration for a single Voltscope run."""

    model: str
    bills_dir: Path
    out_dir: Path
    api_key: Optional[str]
    log_level: str
    db_path: Path
    api_keys: tuple = ()
    high_rate_multiplier: float = 1.3

    @property
    def has_api_key(self) -> bool:
        """True if an Anthropic API key is present in the environment."""
        return bool(self.api_key)

    @property
    def auth_enabled(self) -> bool:
        """True if request authentication is configured (any API keys set)."""
        return bool(self.api_keys)

    @classmethod
    def from_env(cls) -> "Settings":
        """Build :class:`Settings` from environment variables.

        Loads a ``.env`` file first if ``python-dotenv`` is installed. Missing
        optional variables fall back to the module-level defaults.
        """
        if load_dotenv is not None:
            load_dotenv()
        raw_keys = os.environ.get("VOLTSCOPE_API_KEYS", "")
        api_keys = tuple(k.strip() for k in raw_keys.split(",") if k.strip())
        try:
            multiplier = float(os.environ.get("VOLTSCOPE_HIGH_RATE_MULTIPLIER", "1.3"))
        except ValueError:
            multiplier = 1.3
        return cls(
            model=os.environ.get("VOLTSCOPE_MODEL", DEFAULT_MODEL),
            bills_dir=Path(os.environ.get("VOLTSCOPE_BILLS_DIR", DEFAULT_BILLS_DIR)),
            out_dir=Path(os.environ.get("VOLTSCOPE_OUT_DIR", DEFAULT_OUT_DIR)),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            log_level=os.environ.get("VOLTSCOPE_LOG_LEVEL", DEFAULT_LOG_LEVEL),
            db_path=Path(os.environ.get("VOLTSCOPE_DB", DEFAULT_DB_PATH)),
            api_keys=api_keys,
            high_rate_multiplier=multiplier,
        )
