"""Normalized CRUD for WebUI user accounts (``webui_users`` table)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.storage.audit import SYSTEM_ACTOR, actor_or_system
from app.storage.config import backend_for_namespace, supabase_storage_enabled
from app.storage.connection import db_connection
from app.storage.timestamps import from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

_USERS_NAMESPACE = "users"
_REPO_LOCK = threading.RLock()
_REPO: WebuiUsersRepository | None = None


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _backend() -> str:
    return backend_for_namespace(_USERS_NAMESPACE)


def _row_email(row: dict[str, Any]) -> str:
    return str(row.get("email") or row.get("username") or "").strip().lower()


def _encode_profile_names(row: dict[str, Any]) -> str:
    raw = row.get("profile_names")
    if isinstance(raw, list):
        names = [str(item).strip() for item in raw if str(item or "").strip()]
    else:
        names = []
    primary = str(row.get("profile_name") or "").strip()
    if primary and primary not in names:
        names = [primary, *names]
    return json.dumps(names, ensure_ascii=False)


def _decode_profile_names(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item or "").strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item or "").strip()]
    return []


def _account_id(row: dict[str, Any]) -> str:
    email = _normalize_email(_row_email(row))
    explicit = _normalize_email(str(row.get("id") or ""))
    return explicit or email


def _effective_department(row: dict[str, Any]) -> str | None:
    dept_id = str(row.get("department_id") or "").strip().lower() or None
    legacy = str(row.get("department") or "").strip().lower() or None
    return dept_id or legacy


def _sync_department_columns(row: dict[str, Any], *, incoming_keys: set[str] | None = None) -> None:
    """Keep ``department`` and ``department_id`` aligned for API compatibility."""
    if incoming_keys is not None:
        if "department" in incoming_keys:
            dept = str(row.get("department") or "").strip().lower() or None
        elif "department_id" in incoming_keys:
            dept = str(row.get("department_id") or "").strip().lower() or None
        else:
            return
    else:
        dept = _effective_department(row)
    row["department_id"] = dept
    row["department"] = dept


def _row_to_domain(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        data = {key: row[key] for key in row.keys()}
    elif hasattr(row, "_asdict"):
        data = row._asdict()
    else:
        data = dict(row)
    profile_names = _decode_profile_names(data.get("profile_names"))
    profile_name = str(data.get("profile_name") or "").strip() or None
    if profile_name is None and profile_names:
        profile_name = profile_names[0]
    email = _normalize_email(str(data.get("email") or data.get("id") or ""))
    enabled_raw = data.get("enabled", 1)
    enabled = bool(int(enabled_raw)) if str(enabled_raw).strip() not in {"", "none", "null"} else True
    return {
        "id": str(data.get("id") or email),
        "email": email,
        "role": str(data.get("role") or "user"),
        "profile_name": profile_name,
        "profile_names": profile_names,
        "display_name": str(data.get("display_name") or "").strip() or None,
        "department": _effective_department(data),
        "department_id": _effective_department(data),
        "position": str(data.get("position") or "").strip() or None,
        "password_hash": data.get("password_hash"),
        "enabled": enabled,
        "created_at": from_db_timestamp(data.get("created_at")),
        "updated_at": from_db_timestamp(data.get("updated_at")),
        "created_by": str(data.get("created_by") or "").strip() or None,
        "updated_by": str(data.get("updated_by") or "").strip() or None,
        "mcp_api_key_hash": str(data.get("mcp_api_key_hash") or "").strip() or None,
    }


class WebuiUsersRepository:
    """CRUD access to ``webui_users`` and ``webui_profile_bindings``."""

    def _connection(self):
        backend = "supabase" if _backend() == "supabase" else "local"
        return db_connection(backend=backend, namespace=_USERS_NAMESPACE)

    def has_users(self) -> bool:
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT 1 FROM webui_users LIMIT 1"),
            ).fetchone()
        return row is not None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        key = _normalize_email(email)
        if not key:
            return None
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT * FROM webui_users WHERE email = ?"),
                (key,),
            ).fetchone()
        if not row:
            return None
        return _row_to_domain(row)

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        key = _normalize_email(user_id)
        if not key:
            return None
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT * FROM webui_users WHERE id = ?"),
                (key,),
            ).fetchone()
        if not row:
            return None
        return _row_to_domain(row)

    def list_all(self) -> list[dict[str, Any]]:
        with self._connection() as (conn, dialect):
            rows = conn.execute(
                dialect.q("SELECT * FROM webui_users ORDER BY email"),
            ).fetchall()
        return [_row_to_domain(row) for row in rows]

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        domain = _row_to_domain(row)
        payload_row = dict(row)
        _sync_department_columns(payload_row)
        domain = _row_to_domain({**domain, **payload_row})
        email = domain["email"]
        if not email:
            raise ValueError("email is required")
        account_id = _account_id(domain)
        with self._connection() as (conn, dialect):
            now_raw = row.get("updated_at") or row.get("created_at")
            now = to_db_timestamp(
                float(now_raw) if now_raw is not None else utc_now(dialect),
                dialect,
            )
            created_at = to_db_timestamp(row.get("created_at") or now_raw or now, dialect)
            actor = actor_or_system(row.get("created_by") or row.get("updated_by"))
            payload = (
                account_id,
                email,
                domain["role"],
                domain.get("password_hash"),
                domain["profile_name"],
                _encode_profile_names(domain),
                domain["display_name"],
                domain["department"],
                domain["department_id"],
                domain["position"],
                created_at,
                now,
                actor,
                actor,
                1 if domain.get("enabled", True) else 0,
            )
            conn.execute(
                dialect.q(
                    """
                    INSERT INTO webui_users (
                        id, email, role, password_hash, profile_name, profile_names,
                        display_name, department, department_id, position,
                        created_at, updated_at, created_by, updated_by, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                payload,
            )
            conn.commit()
        return domain

    def update(self, email: str, row: dict[str, Any]) -> dict[str, Any]:
        key = _normalize_email(email)
        existing = self.get_by_email(key)
        if existing is None:
            raise KeyError(f"user {key!r} not found")
        merged = {**existing, **row}
        _sync_department_columns(merged, incoming_keys=set(row.keys()))
        merged["email"] = _normalize_email(_row_email(merged) or key)
        with self._connection() as (conn, dialect):
            now = to_db_timestamp(float(row.get("updated_at") or time.time()), dialect)
            merged["updated_at"] = from_db_timestamp(now)
            actor = actor_or_system(row.get("updated_by"))
            created_by = str(existing.get("created_by") or "").strip() or actor_or_system(
                row.get("created_by")
            )
            new_email = merged["email"]
            old_id = str(existing.get("id") or key)
            new_id = _account_id({**merged, "id": new_email if new_email != key else old_id})
            params = (
                new_id,
                new_email,
                merged["role"],
                merged.get("password_hash"),
                merged["profile_name"],
                _encode_profile_names(merged),
                merged["display_name"],
                merged["department"],
                merged["department_id"],
                merged["position"],
                to_db_timestamp(merged.get("created_at") or now, dialect),
                now,
                created_by,
                actor,
                1 if merged.get("enabled", True) else 0,
            )
            if new_email != key or new_id != old_id:
                conn.execute(
                    dialect.q("DELETE FROM webui_users WHERE id = ?"),
                    (old_id,),
                )
                conn.execute(
                    dialect.q(
                        """
                        UPDATE webui_profile_bindings
                        SET user_email = ?, updated_at = ?, updated_by = ?
                        WHERE user_email = ?
                        """
                    ),
                    (new_email, now, actor, key),
                )
            excluded = "EXCLUDED" if dialect.name == "postgres" else "excluded"
            conn.execute(
                dialect.q(
                    f"""
                    INSERT INTO webui_users (
                        id, email, role, password_hash, profile_name, profile_names,
                        display_name, department, department_id, position,
                        created_at, updated_at, created_by, updated_by, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        email = {excluded}.email,
                        role = {excluded}.role,
                        password_hash = {excluded}.password_hash,
                        profile_name = {excluded}.profile_name,
                        profile_names = {excluded}.profile_names,
                        display_name = {excluded}.display_name,
                        department = {excluded}.department,
                        department_id = {excluded}.department_id,
                        position = {excluded}.position,
                        updated_at = {excluded}.updated_at,
                        updated_by = {excluded}.updated_by,
                        enabled = {excluded}.enabled
                    """
                ),
                params,
            )
            conn.commit()
        merged["id"] = new_id
        return _row_to_domain(merged)

    def delete(self, email: str) -> bool:
        key = _normalize_email(email)
        existing = self.get_by_email(key)
        if existing is None:
            return False
        account_id = str(existing.get("id") or key)
        with self._connection() as (conn, dialect):
            cur = conn.execute(
                dialect.q("DELETE FROM webui_users WHERE id = ?"),
                (account_id,),
            )
            conn.execute(
                dialect.q(
                    "DELETE FROM webui_profile_bindings WHERE user_email = ?"
                ),
                (key,),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def get_profile_bindings(self) -> dict[str, str]:
        with self._connection() as (conn, dialect):
            rows = conn.execute(
                dialect.q(
                    """
                    SELECT profile_name, user_email
                    FROM webui_profile_bindings
                    ORDER BY profile_name
                    """
                ),
            ).fetchall()
        bindings: dict[str, str] = {}
        for row in rows:
            profile_name = str(row[0] or "").strip()
            user_email = _normalize_email(str(row[1] or ""))
            if profile_name and user_email:
                bindings[profile_name] = user_email
        return bindings

    def replace_profile_bindings(self, bindings: dict[str, str]) -> None:
        cleaned: dict[str, str] = {}
        for profile_name, user_email in bindings.items():
            pname = str(profile_name or "").strip()
            email = _normalize_email(user_email)
            if pname and email:
                cleaned[pname] = email
        with self._connection() as (conn, dialect):
            now = utc_now(dialect)
            actor = actor_or_system()
            conn.execute(dialect.q("DELETE FROM webui_profile_bindings"))
            for profile_name, user_email in cleaned.items():
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_profile_bindings
                            (profile_name, user_email, updated_at, created_by, updated_by)
                        VALUES (?, ?, ?, ?, ?)
                        """
                    ),
                    (profile_name, user_email, now, actor, actor),
                )
            conn.commit()

    def set_mcp_api_key_hash(
        self,
        email: str,
        key_hash: str | None,
        *,
        updated_by: str | None = None,
    ) -> None:
        key = _normalize_email(email)
        if not key:
            raise KeyError("email is required")
        if self.get_by_email(key) is None:
            raise KeyError(f"user {key!r} not found")
        with self._connection() as (conn, dialect):
            now = utc_now(dialect)
            actor = actor_or_system(updated_by)
            conn.execute(
                dialect.q(
                    """
                    UPDATE webui_users
                    SET mcp_api_key_hash = ?, updated_at = ?, updated_by = ?
                    WHERE email = ?
                    """
                ),
                (key_hash, now, actor, key),
            )
            conn.commit()

    def find_by_mcp_api_key_hash(self, key_hash: str) -> dict[str, Any] | None:
        cleaned = str(key_hash or "").strip()
        if not cleaned:
            return None
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q(
                    """
                    SELECT * FROM webui_users
                    WHERE mcp_api_key_hash = ? AND enabled = 1
                    LIMIT 1
                    """
                ),
                (cleaned,),
            ).fetchone()
        if not row:
            return None
        return _row_to_domain(row)

    def load_store(self) -> dict[str, Any] | None:
        users = self.list_all()
        try:
            bindings = self.get_profile_bindings()
        except Exception:
            logger.warning(
                "Failed to read webui_profile_bindings; continuing with empty bindings",
                exc_info=True,
            )
            bindings = {}
        if not users and not bindings:
            return None
        users_map = {row["email"]: row for row in users if row.get("email")}
        updated_at = 0.0
        for row in users_map.values():
            ts = from_db_timestamp(row.get("updated_at") or row.get("created_at")) or 0.0
            updated_at = max(updated_at, ts)
        return {
            "version": 1,
            "updated_at": updated_at or time.time(),
            "users": users_map,
            "profile_bindings": bindings,
        }

    def save_store(self, store: dict[str, Any], *, json_path: Path | None = None) -> None:
        users_raw = store.get("users")
        bindings_raw = store.get("profile_bindings")
        users = users_raw if isinstance(users_raw, dict) else {}
        bindings = bindings_raw if isinstance(bindings_raw, dict) else {}

        existing = {
            str(row.get("id") or row.get("email"))
            for row in self.list_all()
            if row.get("email")
        }
        target: dict[str, dict[str, Any]] = {}
        target_ids: set[str] = set()
        for account_key, row in users.items():
            if not isinstance(row, dict):
                continue
            email = _normalize_email(_row_email(row) or account_key)
            if not email:
                continue
            payload = dict(row)
            payload["email"] = email
            payload["id"] = _account_id(payload)
            _sync_department_columns(payload)
            target[email] = payload
            target_ids.add(payload["id"])

        for account_id in existing - target_ids:
            with self._connection() as (conn, dialect):
                row = conn.execute(
                    dialect.q("SELECT email FROM webui_users WHERE id = ?"),
                    (account_id,),
                ).fetchone()
                if row:
                    self.delete(str(row[0]))

        for email, row in target.items():
            payload = dict(row)
            payload["email"] = email
            if self.get_by_email(email) is None:
                self.create(payload)
            else:
                self.update(email, payload)

        cleaned_bindings: dict[str, str] = {}
        valid_accounts = set(target.keys())
        for profile_name, bound_user in bindings.items():
            pname = str(profile_name or "").strip()
            bound = _normalize_email(bound_user)
            if pname and bound and bound in valid_accounts:
                cleaned_bindings[pname] = bound
        self.replace_profile_bindings(cleaned_bindings)

        if not supabase_storage_enabled():
            cleaned_store = {
                "version": store.get("version", 1),
                "updated_at": time.time(),
                "users": target,
                "profile_bindings": cleaned_bindings,
            }
            self._mirror_json(cleaned_store, json_path=json_path)

    def import_legacy_document(
        self,
        document: dict[str, Any],
        *,
        json_path: Path | None = None,
    ) -> bool:
        if not isinstance(document, dict):
            return False
        if self.has_users():
            return False
        users = document.get("users")
        if not isinstance(users, dict) or not users:
            return False
        store = {
            "version": document.get("version", 1),
            "updated_at": document.get("updated_at", time.time()),
            "users": users,
            "profile_bindings": document.get("profile_bindings")
            if isinstance(document.get("profile_bindings"), dict)
            else {},
        }
        self.save_store(store, json_path=json_path)
        return True

    def maybe_migrate_legacy(
        self,
        *,
        json_path: Path | None = None,
    ) -> bool:
        from app.storage.repositories.legacy_import import (
            legacy_import_done,
            mark_legacy_import_done,
        )

        table = "webui_users"
        if self.has_users():
            mark_legacy_import_done(table)
            return False
        if legacy_import_done(table):
            return False

        imported = False
        try:
            from app.storage.store import get_webui_store

            doc = get_webui_store().get_json(_USERS_NAMESPACE, "_document")
            if isinstance(doc, dict) and self.import_legacy_document(doc, json_path=json_path):
                logger.info("Migrated users KV document into webui_users")
                imported = True
        except Exception:
            logger.debug("Users KV migration probe failed", exc_info=True)

        if not imported and json_path is not None and json_path.is_file():
            try:
                doc = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.debug("Users JSON migration probe failed", exc_info=True)
            else:
                if isinstance(doc, dict) and self.import_legacy_document(doc, json_path=json_path):
                    logger.info("Migrated users.json into webui_users")
                    imported = True

        mark_legacy_import_done(table)
        return imported

    def backfill_department_ids(self) -> int:
        """Populate ``department_id`` from validated legacy ``department`` values."""
        from app.domain.departments import department_exists, normalize_department_ref

        updated = 0
        for row in self.list_all():
            email = str(row.get("email") or "").strip().lower()
            if not email:
                continue
            if row.get("department_id"):
                continue
            legacy = normalize_department_ref(row.get("department"))
            if not legacy or not department_exists(legacy):
                continue
            self.update(email, {"department": legacy, "department_id": legacy})
            updated += 1
        return updated

    def _mirror_json(self, store: dict[str, Any], *, json_path: Path | None) -> None:
        if json_path is None:
            return
        payload = {
            "version": store.get("version", 1),
            "updated_at": store.get("updated_at", time.time()),
            "users": dict(store.get("users") or {}),
            "profile_bindings": dict(store.get("profile_bindings") or {}),
        }
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=json_path.parent, suffix=".users.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                Path(tmp).chmod(0o600)
                Path(tmp).replace(json_path)
            except Exception:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        except OSError:
            logger.debug("JSON mirror write failed for %s", json_path, exc_info=True)


def get_users_repository() -> WebuiUsersRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = WebuiUsersRepository()
        return _REPO


def reset_users_repository() -> None:
    global _REPO
    with _REPO_LOCK:
        _REPO = None


__all__ = ["WebuiUsersRepository", "get_users_repository", "reset_users_repository"]
