"""Normalized key/value storage for WebUI settings (``webui_settings`` table)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.storage.audit import actor_or_system
from app.storage.config import backend_for_namespace
from app.storage.connection import db_connection
from app.storage.repositories.base import RepositoryBase

logger = logging.getLogger(__name__)

_SETTINGS_DOC_NAMESPACE = "settings"
_REPO_LOCK = threading.RLock()
_REPO: SettingsRepository | None = None


def _backend() -> str:
    return backend_for_namespace(_SETTINGS_DOC_NAMESPACE)


class SettingsRepository(RepositoryBase):
    """Key/value access to ``webui_settings`` rows."""

    def _connection(self):
        backend = "supabase" if _backend() == "supabase" else "local"
        return db_connection(backend=backend, namespace=_SETTINGS_DOC_NAMESPACE)

    def get(
        self,
        key: str,
        *,
        namespace: str = _SETTINGS_DOC_NAMESPACE,
        default: Any = None,
    ) -> Any:
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    """
                    SELECT value FROM webui_settings
                    WHERE namespace = ? AND key = ?
                    """
                ),
                (namespace, str(key)),
            ).fetchone()
        if not row:
            return default
        return self.json_loads(str(row[0]), default=default)

    def set(
        self,
        key: str,
        value: Any,
        *,
        namespace: str = _SETTINGS_DOC_NAMESPACE,
    ) -> None:
        encoded = self.json_dumps(value)
        with self._connection() as (conn, dialect):
            now = self.now(dialect)
            actor = actor_or_system()
            excluded = "EXCLUDED" if dialect.name == "postgres" else "excluded"
            conn.execute(
                dialect.q(
                    f"""
                    INSERT INTO webui_settings (namespace, key, value, updated_at, created_by, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (namespace, key) DO UPDATE SET
                        value = {excluded}.value,
                        updated_at = {excluded}.updated_at,
                        updated_by = {excluded}.updated_by
                    """
                ),
                (namespace, str(key), encoded, now, actor, actor),
            )
            conn.commit()

    def delete(self, key: str, *, namespace: str = _SETTINGS_DOC_NAMESPACE) -> bool:
        with self._connection() as (conn, dialect):
            cur = conn.execute(
                dialect.q(
                    """
                    DELETE FROM webui_settings
                    WHERE namespace = ? AND key = ?
                    """
                ),
                (namespace, str(key)),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def get_all(self, *, namespace: str = _SETTINGS_DOC_NAMESPACE) -> dict[str, Any]:
        return self.list_namespace(namespace=namespace)

    def list_namespace(self, namespace: str = _SETTINGS_DOC_NAMESPACE) -> dict[str, Any]:
        with self._connection() as (conn, dialect):
            rows = conn.execute(
                dialect.q(
                    """
                    SELECT key, value FROM webui_settings
                    WHERE namespace = ?
                    ORDER BY key
                    """
                ),
                (namespace,),
            ).fetchall()
        out: dict[str, Any] = {}
        for row in rows:
            out[str(row[0])] = self.json_loads(str(row[1]), default=str(row[1]))
        return out

    def has_rows(self, *, namespace: str = _SETTINGS_DOC_NAMESPACE) -> bool:
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    "SELECT 1 FROM webui_settings WHERE namespace = ? LIMIT 1",
                ),
                (namespace,),
            ).fetchone()
        return row is not None

    def load_document(self) -> dict[str, Any] | None:
        """Rebuild legacy ``settings.json`` dict for transitional callers."""
        doc = self.get_all(namespace=_SETTINGS_DOC_NAMESPACE)
        return doc if doc else None

    def save_document(self, payload: dict[str, Any]) -> None:
        """Flatten legacy ``settings.json`` dict into key/value rows."""
        if not isinstance(payload, dict):
            raise TypeError("settings document must be a dict")
        current = self.get_all(namespace=_SETTINGS_DOC_NAMESPACE)
        stale = set(current.keys()) - set(payload.keys())
        for key in stale:
            self.delete(key, namespace=_SETTINGS_DOC_NAMESPACE)
        for key, value in payload.items():
            self.set(key, value, namespace=_SETTINGS_DOC_NAMESPACE)

    def import_legacy_document(self, document: dict[str, Any]) -> bool:
        if not isinstance(document, dict) or not document:
            return False
        if self.has_rows(namespace=_SETTINGS_DOC_NAMESPACE):
            return False
        self.save_document(document)
        return True

    def maybe_migrate_legacy(self) -> bool:
        """Import ``webui_kv`` settings/_document blob into ``webui_settings`` rows."""
        if self.has_rows(namespace=_SETTINGS_DOC_NAMESPACE):
            return False
        try:
            from app.storage.store import get_webui_store

            doc = get_webui_store().get_json(
                _SETTINGS_DOC_NAMESPACE,
                "_document",
                _allow_kv=True,
            )
            if isinstance(doc, dict) and self.import_legacy_document(doc):
                logger.info("Migrated settings KV document into webui_settings")
                return True
        except Exception:
            logger.debug("Settings KV migration probe failed", exc_info=True)
        return False


def get_settings_repository() -> SettingsRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = SettingsRepository()
        return _REPO


def reset_settings_repository() -> None:
    global _REPO
    with _REPO_LOCK:
        _REPO = None


__all__ = ["SettingsRepository", "get_settings_repository", "reset_settings_repository"]
