"""Transitional document-level accessors for normalized Supabase tables."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any

from app.storage.connection import Backend, db_connection
from app.storage.timestamps import from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

META_KEY = "kv_normalized_v1"
NORMALIZED_NAMESPACES = frozenset({"users"})


def _storage_backend() -> Backend:
    from app.storage.config import primary_storage_backend

    return "supabase" if primary_storage_backend() == "supabase" else "local"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def user_id_for_email(email: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"hermes-webui-user:{email}"))


def is_normalized_active() -> bool:
    from app.storage.config import supabase_storage_enabled

    if not supabase_storage_enabled():
        return False
    try:
        with db_connection(backend=_storage_backend()) as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    "SELECT value FROM webui_meta WHERE key = ?",
                ),
                (META_KEY,),
            ).fetchone()
        return row is not None and str(row[0]).lower() in {"1", "true", "yes"}
    except Exception:
        logger.debug("Normalized storage probe failed", exc_info=True)
        return False


def uses_normalized_namespace(namespace: str) -> bool:
    return namespace in NORMALIZED_NAMESPACES and is_normalized_active()


def read_document(namespace: str) -> Any | None:
    if namespace == "settings":
        return _read_settings_document()
    if namespace == "users":
        return _read_users_document()
    if namespace == "auth_sessions":
        return _read_auth_sessions_document()
    if namespace == "session_users":
        return _read_session_users_document()
    return None


def write_document(namespace: str, payload: Any) -> None:
    if namespace == "settings":
        _write_settings_document(payload)
    elif namespace == "users":
        _write_users_document(payload)
    elif namespace == "auth_sessions":
        _write_auth_sessions_document(payload)
    elif namespace == "session_users":
        _write_session_users_document(payload)
    else:
        raise ValueError(f"Unsupported normalized namespace: {namespace}")


def _read_settings_document() -> dict[str, Any] | None:
    from app.storage.repositories.settings import get_settings_repository

    repo = get_settings_repository()
    repo.maybe_migrate_legacy()
    return repo.load_document()


def _write_settings_document(payload: Any) -> None:
    from app.storage.repositories.settings import get_settings_repository

    if not isinstance(payload, dict):
        raise TypeError("settings document must be a dict")
    get_settings_repository().save_document(payload)


def _read_users_document() -> dict[str, Any] | None:
    from app.storage.repositories.users import get_users_repository

    return get_users_repository().load_store()


def _write_users_document(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise TypeError("users document must be a dict")
    from app.storage.repositories.users import get_users_repository

    get_users_repository().save_store(payload)


def _read_auth_sessions_document() -> dict[str, Any]:
    with db_connection(backend=_storage_backend()) as (conn, dialect):
        rows = conn.execute(
            dialect.q(
                """
                SELECT token_hash, user_id, role, exp, metadata
                FROM webui_auth_sessions
                ORDER BY created_at
                """
            ),
        ).fetchall()
    sessions: dict[str, Any] = {}
    for row in rows:
        meta = {}
        try:
            meta = json.loads(row[4]) if row[4] else {}
        except json.JSONDecodeError:
            meta = {}
        token = meta.get("token")
        if not isinstance(token, str) or not token:
            continue
        sessions[token] = {
            "exp": from_db_timestamp(row[3]) or 0.0,
            "user_id": str(row[1]),
            "role": str(row[2]),
        }
    return sessions


def _write_auth_sessions_document(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise TypeError("auth_sessions document must be a dict")
    with db_connection(backend=_storage_backend()) as (conn, dialect):
        now = utc_now(dialect)
        conn.execute(dialect.q("DELETE FROM webui_auth_sessions"))
        for token, entry in payload.items():
            if not isinstance(token, str):
                continue
            if isinstance(entry, (int, float)):
                exp = to_db_timestamp(entry, dialect)
                user_id = "legacy"
                role = "admin"
            elif isinstance(entry, dict):
                exp_raw = entry.get("exp")
                if not isinstance(exp_raw, (int, float)):
                    continue
                exp = to_db_timestamp(exp_raw, dialect)
                user_id = str(entry.get("user_id") or "legacy")
                role = str(entry.get("role") or "admin")
            else:
                continue
            th = token_hash(token)
            conn.execute(
                dialect.q(
                    """
                    INSERT INTO webui_auth_sessions (
                        id, token_hash, user_id, role, exp, created_at, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    uuid.uuid4().hex,
                    th,
                    user_id,
                    role,
                    exp,
                    now,
                    json.dumps({"token": token}, ensure_ascii=False),
                ),
            )
        conn.commit()


def _read_session_users_document() -> dict[str, str]:
    with db_connection(backend=_storage_backend()) as (conn, dialect):
        rows = conn.execute(
            dialect.q(
                """
                SELECT metadata FROM webui_auth_sessions
                WHERE metadata IS NOT NULL AND metadata != '{}'
                """
            ),
        ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        try:
            meta = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        if not isinstance(meta, dict):
            continue
        token = meta.get("token")
        bound_user = meta.get("session_user")
        if isinstance(token, str) and isinstance(bound_user, str):
            out[token] = bound_user
    return out


def _write_session_users_document(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise TypeError("session_users document must be a dict")
    with db_connection(backend=_storage_backend()) as (conn, dialect):
        rows = conn.execute(
            dialect.q("SELECT id, token_hash, metadata FROM webui_auth_sessions"),
        ).fetchall()
        by_token: dict[str, tuple[str, dict[str, Any]]] = {}
        for row in rows:
            try:
                meta = json.loads(row[2]) if row[2] else {}
            except json.JSONDecodeError:
                meta = {}
            token = meta.get("token")
            if isinstance(token, str):
                by_token[token] = (str(row[0]), meta)
        for token, bound_user in payload.items():
            if not isinstance(token, str) or not isinstance(bound_user, str):
                continue
            row_id, meta = by_token.get(token, (None, {"token": token}))
            if row_id is None:
                continue
            merged = dict(meta)
            merged["session_user"] = bound_user
            conn.execute(
                dialect.q("UPDATE webui_auth_sessions SET metadata = ? WHERE id = ?"),
                (json.dumps(merged, ensure_ascii=False), row_id),
            )
        conn.commit()


def set_normalized_active() -> None:
    with db_connection(backend=_storage_backend()) as (conn, dialect):
        now = utc_now(dialect)
        conn.execute(
            dialect.q(
                """
                INSERT INTO webui_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """
            ),
            (META_KEY, "true", now),
        )
        conn.commit()
