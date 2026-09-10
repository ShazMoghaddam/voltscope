"""Run the review app: ``python -m voltscope.api``.

Reads host/port from VOLTSCOPE_HOST / VOLTSCOPE_PORT (defaults 127.0.0.1:8000),
and the database path from VOLTSCOPE_DB (default ./voltscope.db).
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("VOLTSCOPE_HOST", "127.0.0.1")
    port = int(os.environ.get("VOLTSCOPE_PORT", "8000"))
    uvicorn.run("voltscope.api.app:get_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
