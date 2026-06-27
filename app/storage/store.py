"""Key-value and history storage backed by WebUI database."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any

from app.storage.config import backend_for_history, backend_for_namespace
from app.storage.connection import Backend, db_connection, resolve_backend
from app.storage.dialect import Dialect
from app.storage.normalized import (
    read_document,
    uses_normalized_namespace,
    write_document,
)

logger = logging.getLogger(__name__)

_STORE_LOCK = threading.RLock()
_STORE: "WebuiStore | None" = None


class WebuiStore:
    """Persistent config/history store with JSON document helpers."""

    @staticmethod
    def _backend_for_namespace(namespace: str) -> Backend:
        return "supabase" if backend_for_namespace(namespace) == "supabase" else "local"

    @staticmethod
    def _backend_for_kv_table() -> Backend:
        from app.storage.config import primary_storage_backend

        return "supabase" if primary_storage_backend() == "supabase" else "local"

    def get_json(
        self,
        namespace: str,
        key: str,
        *,
        profile: str = "",
        default: Any = None,
        _allow_kv: bool = False,
    ) -> Any:
        if not _allow_kv and key == "_document" and namespace == "settings":
            from app.storage.repositories.settings import get_settings_repository

            repo = get_settings_repository()
            repo.maybe_migrate_legacy()
            doc = repo.load_document()
            return default if doc is None else doc
        if (
            not _allow_kv
            and key == "_document"
            and uses_normalized_namespace(namespace)
        ):
            doc = read_document(namespace)
            return default if doc is None else doc
        row = self.get_raw(namespace, key, profile=profile, _allow_kv=_allow_kv)
        if row is None:
            return default
        try:
            return json.loads(row)
        except json.JSONDecodeError:
            logger.debug("Invalid JSON in webui_kv %s/%s", namespace, key)
            return default

    def set_json(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        profile: str = "",
        _allow_kv: bool = False,
    ) -> None:
        if not _allow_kv and key == "_document" and namespace == "settings":
            from app.storage.repositories.settings import get_settings_repository

            if isinstance(value, dict):
                get_settings_repository().save_document(value)
            return
        if (
            not _allow_kv
            and key == "_document"
            and uses_normalized_namespace(namespace)
        ):
            write_document(namespace, value)
            return
        self.set_raw(
            namespace,
            key,
            json.dumps(value, ensure_ascii=False),
            profile=profile,
            _allow_kv=_allow_kv,
        )

    def get_raw(
        self,
        namespace: str,
        key: str,
        *,
        profile: str = "",
        _allow_kv: bool = False,
    ) -> str | None:
        if not _allow_kv and (
            namespace == "settings" or uses_normalized_namespace(namespace)
        ):
            return None
        backend = self._backend_for_kv_table()
        with db_connection(backend=backend, namespace=namespace) as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    """
                    SELECT value FROM webui_kv
                    WHERE namespace = ? AND profile = ? AND key = ?
                    """
                ),
                (namespace, profile, key),
            ).fetchone()
        if not row:
            return None
        return str(row[0])

    def set_raw(
        self,
        namespace: str,
        key: str,
        value: str,
        *,
        profile: str = "",
        _allow_kv: bool = False,
    ) -> None:
        if not _allow_kv and (
            namespace == "settings" or uses_normalized_namespace(namespace)
        ):
            logger.debug("Skipping webui_kv write for normalized namespace %s", namespace)
            return
        now = time.time()
        backend = self._backend_for_kv_table()
        with db_connection(backend=backend, namespace=namespace) as (conn, dialect):
            if dialect.name == "sqlite":
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_kv (namespace, profile, key, value, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(namespace, profile, key) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at
                        """
                    ),
                    (namespace, profile, key, value, now),
                )
            else:
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_kv (namespace, profile, key, value, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (namespace, profile, key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    (namespace, profile, key, value, now),
                )
            conn.commit()

    def delete(self, namespace: str, key: str, *, profile: str = "") -> bool:
        if namespace == "settings" or uses_normalized_namespace(namespace):
            return False
        backend = self._backend_for_kv_table()
        with db_connection(backend=backend, namespace=namespace) as (conn, dialect):
            cur = conn.execute(
                dialect.q(
                    """
                    DELETE FROM webui_kv
                    WHERE namespace = ? AND profile = ? AND key = ?
                    """
                ),
                (namespace, profile, key),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def list_namespace(
        self,
        namespace: str,
        *,
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        if namespace == "settings" or uses_normalized_namespace(namespace):
            return []
        backend = self._backend_for_kv_table()
        with db_connection(backend=backend, namespace=namespace) as (conn, dialect):
            if profile is None:
                rows = conn.execute(
                    dialect.q(
                        """
                        SELECT profile, key, value, updated_at
                        FROM webui_kv
                        WHERE namespace = ?
                        ORDER BY profile, key
                        """
                    ),
                    (namespace,),
                ).fetchall()
            else:
                rows = conn.execute(
                    dialect.q(
                        """
                        SELECT profile, key, value, updated_at
                        FROM webui_kv
                        WHERE namespace = ? AND profile = ?
                        ORDER BY key
                        """
                    ),
                    (namespace, profile),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                parsed = json.loads(row[2])
            except json.JSONDecodeError:
                parsed = row[2]
            out.append(
                {
                    "profile": row[0],
                    "key": row[1],
                    "value": parsed,
                    "updated_at": row[3],
                }
            )
        return out

    def append_history(
        self,
        namespace: str,
        entity_type: str,
        action: str,
        *,
        entity_id: str = "",
        profile: str = "",
        payload: dict | list | None = None,
    ) -> str:
        entry_id = uuid.uuid4().hex
        now = time.time()
        body = json.dumps(payload or {}, ensure_ascii=False)
        backend: Backend = "supabase" if backend_for_history() == "supabase" else "local"
        with db_connection(backend=backend, for_history=True) as (conn, dialect):
            conn.execute(
                dialect.q(
                    """
                    INSERT INTO webui_history
                        (id, namespace, entity_type, entity_id, action, profile, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (entry_id, namespace, entity_type, entity_id, action, profile, body, now, now),
            )
            conn.commit()
        return entry_id

    def list_history(
        self,
        namespace: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        profile: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["namespace = ?"]
        params: list[Any] = [namespace]
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if profile is not None:
            clauses.append("profile = ?")
            params.append(profile)
        params.append(max(1, min(limit, 1000)))
        where = " AND ".join(clauses)
        backend: Backend = "supabase" if backend_for_history() == "supabase" else "local"
        with db_connection(backend=backend, for_history=True) as (conn, dialect):
            rows = conn.execute(
                dialect.q(
                    f"""
                    SELECT id, entity_type, entity_id, action, profile, payload, created_at
                    FROM webui_history
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """
                ),
                tuple(params),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[5])
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "id": row[0],
                    "entity_type": row[1],
                    "entity_id": row[2],
                    "action": row[3],
                    "profile": row[4],
                    "payload": payload,
                    "created_at": row[6],
                }
            )
        return out


def get_webui_store() -> WebuiStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = WebuiStore()
        return _STORE
