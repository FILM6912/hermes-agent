"""Normalized CRUD for WebUI roles (``webui_roles`` table)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.storage.audit import SYSTEM_ACTOR, actor_or_system
from app.storage.config import supabase_storage_enabled
from app.storage.connection import db_connection
from app.storage.timestamps import from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

_REPO_LOCK = threading.RLock()
_REPO: WebuiRolesRepository | None = None


def _backend() -> str:
    return "supabase" if supabase_storage_enabled() else "local"


def _coerce_permissions_map(value: Any) -> dict[str, bool]:
    from app.domain.roles import coerce_permissions_map

    return coerce_permissions_map(value)


def _permissions_for_write(value: Any, dialect: Any) -> Any:
    """Return a DB bind value: JSON object (JSONB) or JSON text (SQLite)."""
    perms = _coerce_permissions_map(value)
    if getattr(dialect, "name", None) == "postgres":
        return json.dumps(perms, ensure_ascii=False)
    return json.dumps(perms, ensure_ascii=False)


def _row_to_domain(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        data = {key: row[key] for key in row.keys()}
    elif hasattr(row, "_asdict"):
        data = row._asdict()
    else:
        data = dict(row)
    enabled_raw = data.get("builtin", 0)
    builtin = bool(int(enabled_raw)) if str(enabled_raw).strip() not in {"", "none", "null"} else False
    requires_raw = data.get("requires_profile", 0)
    requires_profile = (
        bool(int(requires_raw)) if str(requires_raw).strip() not in {"", "none", "null"} else False
    )
    return {
        "id": str(data.get("id") or "").strip().lower(),
        "label": str(data.get("label") or "").strip(),
        "description": str(data.get("description") or "").strip() or None,
        "permissions": _coerce_permissions_map(data.get("permissions")),
        "requires_profile": requires_profile,
        "builtin": builtin,
        "created_at": from_db_timestamp(data.get("created_at")),
        "updated_at": from_db_timestamp(data.get("updated_at")),
        "created_by": str(data.get("created_by") or "").strip() or None,
        "updated_by": str(data.get("updated_by") or "").strip() or None,
    }


class WebuiRolesRepository:
    """CRUD access to ``webui_roles``."""

    def enabled(self) -> bool:
        return _backend() == "supabase"

    def _connection(self):
        return db_connection(backend="supabase")

    def has_roles(self) -> bool:
        if not self.enabled():
            return False
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT 1 FROM webui_roles LIMIT 1"),
            ).fetchone()
        return row is not None

    def list_all(self) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        with self._connection() as (conn, dialect):
            rows = conn.execute(
                dialect.q("SELECT * FROM webui_roles ORDER BY id ASC"),
            ).fetchall()
        return [_row_to_domain(row) for row in rows if _row_to_domain(row).get("id")]

    def get(self, role_id: str) -> dict[str, Any] | None:
        key = str(role_id or "").strip().lower()
        if not key or not self.enabled():
            return None
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT * FROM webui_roles WHERE id = ?"),
                (key,),
            ).fetchone()
        if not row:
            return None
        return _row_to_domain(row)

    def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        domain = _row_to_domain(row)
        role_id = domain["id"]
        if not role_id:
            raise ValueError("role id is required")
        existing = self.get(role_id)
        actor = actor_or_system(
            row.get("updated_by") if existing is not None else row.get("created_by"),
            fallback=row.get("updated_by"),
        )
        created_by = (
            str(existing.get("created_by") or "").strip()
            if existing is not None
            else actor
        ) or SYSTEM_ACTOR
        with self._connection() as (conn, dialect):
            now = utc_now(dialect)
            perms_value = _permissions_for_write(domain.get("permissions"), dialect)
            if existing is None:
                conn.execute(
                    dialect.q(
                        """
                        INSERT INTO webui_roles (
                            id, label, description, permissions,
                            requires_profile, builtin, created_at, updated_at,
                            created_by, updated_by
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                    ),
                    (
                        role_id,
                        domain["label"] or role_id,
                        domain.get("description"),
                        perms_value,
                        1 if domain.get("requires_profile") else 0,
                        1 if domain.get("builtin") else 0,
                        now,
                        now,
                        created_by,
                        actor,
                    ),
                )
            else:
                conn.execute(
                    dialect.q(
                        """
                        UPDATE webui_roles
                        SET label = ?, description = ?, permissions = ?,
                            requires_profile = ?, builtin = ?, updated_at = ?,
                            updated_by = ?
                        WHERE id = ?
                        """
                    ),
                    (
                        domain["label"] or role_id,
                        domain.get("description"),
                        perms_value,
                        1 if domain.get("requires_profile") else 0,
                        1 if domain.get("builtin") else 0,
                        now,
                        actor,
                        role_id,
                    ),
                )
            conn.commit()
        return {**domain, "created_by": created_by, "updated_by": actor}

    def delete(self, role_id: str) -> bool:
        key = str(role_id or "").strip().lower()
        if not key or not self.enabled():
            return False
        with self._connection() as (conn, dialect):
            cur = conn.execute(
                dialect.q("DELETE FROM webui_roles WHERE id = ?"),
                (key,),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def import_legacy_document(
        self,
        document: dict[str, Any],
        *,
        json_path: Path | None = None,
    ) -> bool:
        if not self.enabled():
            return False
        roles = document.get("roles")
        if not isinstance(roles, dict) or not roles:
            return False
        imported = False
        for role_id, row in roles.items():
            if not isinstance(row, dict):
                continue
            cleaned = str(role_id or "").strip().lower()
            if not cleaned:
                continue
            if self.get(cleaned) is not None:
                continue
            try:
                self.upsert(
                    {
                        "id": cleaned,
                        "label": row.get("label") or cleaned,
                        "description": row.get("description"),
                        "permissions": row.get("permissions") or {},
                        "requires_profile": row.get("requires_profile"),
                        "builtin": row.get("builtin"),
                        "created_by": SYSTEM_ACTOR,
                        "updated_by": SYSTEM_ACTOR,
                    }
                )
                imported = True
            except Exception:
                logger.warning("Failed to import role %s", cleaned, exc_info=True)
        if imported and json_path and json_path.is_file():
            logger.info("Migrated roles.json into webui_roles")
        return imported

    def maybe_migrate_legacy(self, *, json_path: Path | None = None) -> bool:
        from app.storage.repositories.legacy_import import (
            legacy_import_done,
            mark_legacy_import_done,
        )

        table = "webui_roles"
        if not self.enabled():
            return False
        if self.has_roles():
            mark_legacy_import_done(table)
            return False
        if legacy_import_done(table):
            return False
        if not json_path or not json_path.is_file():
            mark_legacy_import_done(table)
            return False
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Failed to read roles.json for migration", exc_info=True)
            mark_legacy_import_done(table)
            return False
        imported = False
        if isinstance(raw, dict):
            imported = self.import_legacy_document(raw, json_path=json_path)
        mark_legacy_import_done(table)
        return imported

    def seed_defaults(self, defaults: dict[str, dict[str, Any]]) -> None:
        if not self.enabled():
            return
        for role_id, row in defaults.items():
            if self.get(role_id) is not None:
                continue
            if not isinstance(row, dict):
                continue
            self.upsert(
                {
                    "id": role_id,
                    "label": row.get("label") or role_id,
                    "description": row.get("description"),
                    "permissions": row.get("permissions") or {},
                    "requires_profile": row.get("requires_profile"),
                    "builtin": row.get("builtin"),
                    "created_by": SYSTEM_ACTOR,
                    "updated_by": SYSTEM_ACTOR,
                }
            )


def get_roles_repository() -> WebuiRolesRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = WebuiRolesRepository()
        return _REPO
