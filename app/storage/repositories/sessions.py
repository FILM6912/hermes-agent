"""Auth session persistence in the ``webui_auth_sessions`` table."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any

from app.storage.connection import Backend, db_connection
from app.storage.timestamps import cutoff_for_query, from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

_REPO_LOCK = threading.RLock()
_REPO: SessionsRepository | None = None
_MIGRATED = False


def hash_session_token(token: str) -> str:
    """Return a stable SHA-256 hex digest for an opaque session token."""
    return hashlib.sha256(str(token or "").encode()).hexdigest()


def _sessions_backend() -> Backend:
    from app.storage.config import primary_storage_backend

    return "supabase" if primary_storage_backend() == "supabase" else "local"


def _row_to_entry(row: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    raw_meta = row[6] if len(row) > 6 else "{}"
    if raw_meta:
        try:
            parsed = json.loads(str(raw_meta))
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}
    return {
        "exp": from_db_timestamp(row[4]) or 0.0,
        "user_id": str(row[2] or "legacy"),
        "role": str(row[3] or "admin"),
        **metadata,
    }


_AUTH_SESSIONS_TABLE = "webui_auth_sessions"


class SessionsRepository:
    """CRUD for browser/API auth sessions stored in ``webui_auth_sessions``."""

    def __init__(self, *, backend: Backend | None = None) -> None:
        self._backend_override = backend

    @property
    def backend(self) -> Backend:
        return self._backend_override or _sessions_backend()

    def create_session(
        self,
        token: str,
        *,
        user_id: str = "legacy",
        role: str = "admin",
        exp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a new session row keyed by ``token`` hash."""
        token_hash = hash_session_token(token)
        session_id = uuid.uuid4().hex
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with db_connection(backend=self.backend) as (conn, dialect):
            now = utc_now(dialect)
            expiry = to_db_timestamp(exp if exp is not None else now, dialect)
            existing = conn.execute(
                dialect.q(f"SELECT id FROM {_AUTH_SESSIONS_TABLE} WHERE token_hash = ?"),
                (token_hash,),
            ).fetchone()
            if existing:
                conn.execute(
                    dialect.q(
                        """
                        UPDATE webui_auth_sessions
                        SET user_id = ?, role = ?, exp = ?, metadata = ?, updated_at = ?
                        WHERE token_hash = ?
                        """
                    ),
                    (user_id, role, expiry, meta_json, now, token_hash),
                )
            elif dialect.name == "sqlite":
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_auth_sessions
                            (id, token_hash, user_id, role, exp, created_at, updated_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """
                    ),
                    (session_id, token_hash, user_id, role, expiry, now, now, meta_json),
                )
            else:
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_auth_sessions
                            (id, token_hash, user_id, role, exp, created_at, updated_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (token_hash) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            role = EXCLUDED.role,
                            exp = EXCLUDED.exp,
                            metadata = EXCLUDED.metadata,
                            updated_at = EXCLUDED.updated_at
                        """
                    ),
                    (session_id, token_hash, user_id, role, expiry, now, now, meta_json),
                )
            conn.commit()
        return {
            "exp": from_db_timestamp(expiry) or 0.0,
            "user_id": user_id,
            "role": role,
        }

    def get_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        """Return session metadata for a token hash, or ``None`` when absent."""
        with db_connection(backend=self.backend) as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    """
                    SELECT id, token_hash, user_id, role, exp, created_at, metadata
                    FROM webui_auth_sessions
                    WHERE token_hash = ?
                    """
                ),
                (token_hash,),
            ).fetchone()
        if not row:
            return None
        entry = _row_to_entry(row)
        if (from_db_timestamp(entry.get("exp")) or 0.0) <= time.time():
            return None
        return entry

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        """Return session metadata for a raw opaque token."""
        if not token:
            return None
        return self.get_by_token_hash(hash_session_token(token))

    def revoke(self, token: str | None = None, *, token_hash: str | None = None) -> bool:
        """Delete a session row by raw token or token hash."""
        resolved_hash = token_hash or (hash_session_token(token) if token else "")
        if not resolved_hash:
            return False
        with db_connection(backend=self.backend) as (conn, dialect):
            cur = conn.execute(
                dialect.q("DELETE FROM webui_auth_sessions WHERE token_hash = ?"),
                (resolved_hash,),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Return non-expired sessions for ``user_id``, newest first."""
        with db_connection(backend=self.backend) as (conn, dialect):
            cutoff = cutoff_for_query(time.time(), dialect)
            rows = conn.execute(
                dialect.q(
                    """
                    SELECT id, token_hash, user_id, role, exp, created_at, metadata
                    FROM webui_auth_sessions
                    WHERE user_id = ? AND exp > ?
                    ORDER BY exp DESC, created_at DESC
                    """
                ),
                (user_id, cutoff),
            ).fetchall()
        return [
            {
                "id": str(row[0]),
                "token_hash": str(row[1]),
                **_row_to_entry(row),
                "created_at": from_db_timestamp(row[5]) or 0.0,
            }
            for row in rows
        ]

    def cleanup_expired(self, *, now: float | None = None) -> int:
        """Delete expired rows and return the number removed."""
        with db_connection(backend=self.backend) as (conn, dialect):
            cutoff = cutoff_for_query(now, dialect)
            cur = conn.execute(
                dialect.q("DELETE FROM webui_auth_sessions WHERE exp <= ?"),
                (cutoff,),
            )
            conn.commit()
            return int(getattr(cur, "rowcount", 0) or 0)

    def count(self) -> int:
        with db_connection(backend=self.backend) as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT COUNT(*) FROM webui_auth_sessions"),
            ).fetchone()
        return int(row[0]) if row else 0

    def import_from_documents(
        self,
        auth_sessions: dict[str, Any] | None,
        session_users: dict[str, Any] | None = None,
    ) -> int:
        """Import legacy KV/JSON session maps into ``webui_auth_sessions``.

        ``auth_sessions`` mirrors ``.sessions.json`` (token -> exp or metadata).
        ``session_users`` mirrors ``.session_users.json`` (token -> username).
        """
        if not isinstance(auth_sessions, dict):
            return 0
        users_map = session_users if isinstance(session_users, dict) else {}
        imported = 0
        now = time.time()
        for raw_token, entry in auth_sessions.items():
            if not isinstance(raw_token, str) or not raw_token:
                continue
            normalized = _normalize_legacy_entry(entry, users_map.get(raw_token), now=now)
            if normalized is None:
                continue
            self.create_session(
                raw_token,
                user_id=normalized["user_id"],
                role=normalized["role"],
                exp=normalized["exp"],
            )
            imported += 1
        return imported


def _normalize_legacy_entry(
    entry: Any,
    session_user: Any,
    *,
    now: float,
) -> dict[str, Any] | None:
    if isinstance(entry, (int, float)):
        exp = float(entry)
        user_id = "legacy"
        role = "admin"
    elif isinstance(entry, dict):
        exp_raw = entry.get("exp")
        if not isinstance(exp_raw, (int, float)):
            return None
        exp = float(exp_raw)
        user_id = str(entry.get("user_id") or "legacy")
        role = str(entry.get("role") or "admin")
    else:
        return None
    if exp <= now:
        return None
    if session_user is not None:
        username = str(session_user).strip()
        if username:
            user_id = username
    return {"exp": exp, "user_id": user_id, "role": role}


def get_sessions_repository() -> SessionsRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = SessionsRepository()
        return _REPO


def reset_sessions_repository() -> None:
    global _REPO, _MIGRATED
    with _REPO_LOCK:
        _REPO = None
        _MIGRATED = False


def ensure_sessions_migrated() -> None:
    """One-time import from KV namespaces or JSON mirrors into ``webui_auth_sessions``."""
    global _MIGRATED
    with _REPO_LOCK:
        if _MIGRATED:
            return
        repo = get_sessions_repository()
        try:
            existing = repo.count()
        except Exception as exc:
            from app.storage.config import supabase_storage_enabled

            if supabase_storage_enabled():
                logger.warning(
                    "Auth session table unavailable during migration (will retry after schema init): %s",
                    exc,
                )
            else:
                logger.debug("Auth session table unavailable during migration: %s", exc)
            return
        if existing > 0:
            _MIGRATED = True
            return
        try:
            from app.storage.migrate import load_document

            auth_doc = load_document("auth_sessions")
            users_doc = load_document("session_users")
            imported = repo.import_from_documents(auth_doc, users_doc)
            if imported:
                logger.info("Imported %s auth session(s) into webui_auth_sessions", imported)
        except Exception as exc:
            from app.storage.config import supabase_storage_enabled

            if supabase_storage_enabled():
                logger.warning("Auth session migration skipped: %s", exc)
            else:
                logger.debug("Auth session migration skipped: %s", exc)
        _MIGRATED = True


def verify_supabase_sessions_storage() -> dict[str, object]:
    """Probe Supabase session persistence; used at startup for diagnostics."""
    from app.storage.config import supabase_storage_enabled

    if not supabase_storage_enabled():
        return {"status": "skipped", "reason": "supabase_disabled"}
    repo = get_sessions_repository()
    if repo.backend != "supabase":
        return {"status": "error", "reason": "sessions_repo_not_supabase"}
    try:
        count = repo.count()
        return {"status": "ok", "backend": repo.backend, "row_count": count}
    except Exception as exc:
        return {"status": "error", "backend": repo.backend, "error": str(exc)}
