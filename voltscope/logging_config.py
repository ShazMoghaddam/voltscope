"""Structured logging setup for Voltscope.

Diagnostics (retries, skipped files, extraction errors) go through the logging
system so the eventual API layer can route them properly. The human-facing
report that the CLI prints is deliberately *not* logging; it is the product's
output and is written straight to stdout.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
