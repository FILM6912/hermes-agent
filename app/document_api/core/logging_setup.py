from __future__ import annotations

import logging


def configure_app_logging(level: str = "INFO") -> None:
    """Ensure app loggers emit to stdout (Docker/uvicorn default root level is often WARNING)."""
    lvl = getattr(logging, (level or "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(lvl)
