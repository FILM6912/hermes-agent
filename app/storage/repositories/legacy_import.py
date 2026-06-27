"""One-time legacy JSON/KV import markers for Supabase-backed tables."""

from __future__ import annotations

import logging

from app.storage.config import supabase_storage_enabled
from app.storage.connection import db_connection
from app.storage.timestamps import utc_now

logger = logging.getLogger(__name__)

_META_PREFIX = "legacy_import_done:"


def _meta_key(table: str) -> str:
    return f"{_META_PREFIX}{table.strip()}"


def legacy_import_done(table: str) -> bool:
    """Return True when legacy import for ``table`` must not run again."""
    if not supabase_storage_enabled():
        return False
    try:
        with db_connection(backend="supabase") as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT value FROM webui_meta WHERE key = ?"),
                (_meta_key(table),),
            ).fetchone()
        if not row:
            return False
        return str(row[0]).strip().lower() in {"1", "true", "yes", "done"}
    except Exception:
        logger.debug("Legacy import marker probe failed for %s", table, exc_info=True)
        return False


def mark_legacy_import_done(table: str) -> None:
    """Record that legacy import for ``table`` has finished (success or no source)."""
    if not supabase_storage_enabled():
        return
    try:
        with db_connection(backend="supabase") as (conn, dialect):
            now = utc_now(dialect)
            conn.execute(
                dialect.q(
                    """
                    INSERT INTO webui_meta (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """
                ),
                (_meta_key(table), "done", now),
            )
            conn.commit()
    except Exception:
        logger.warning("Failed to mark legacy import done for %s", table, exc_info=True)
