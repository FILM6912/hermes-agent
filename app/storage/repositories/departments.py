"""Normalized CRUD for WebUI departments (``webui_departments`` table)."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from app.storage.audit import SYSTEM_ACTOR, actor_or_system
from app.storage.config import supabase_storage_enabled
from app.storage.connection import db_connection
from app.storage.timestamps import from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

_REPO_LOCK = threading.RLock()
_REPO: WebuiDepartmentsRepository | None = None


def _backend() -> str:
    return "supabase" if supabase_storage_enabled() else "local"


def _row_to_domain(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        data = {key: row[key] for key in row.keys()}
    elif hasattr(row, "_asdict"):
        data = row._asdict()
    else:
        data = dict(row)
    return {
        "id": str(data.get("id") or "").strip().lower(),
        "label": str(data.get("label") or "").strip(),
        "description": str(data.get("description") or "").strip() or None,
        "created_at": from_db_timestamp(data.get("created_at")),
        "updated_at": from_db_timestamp(data.get("updated_at")),
        "created_by": str(data.get("created_by") or "").strip() or None,
        "updated_by": str(data.get("updated_by") or "").strip() or None,
    }


class WebuiDepartmentsRepository:
    """CRUD access to ``webui_departments``."""

    def enabled(self) -> bool:
        return _backend() == "supabase"

    def _connection(self):
        return db_connection(backend="supabase")

    def has_departments(self) -> bool:
        if not self.enabled():
            return False
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT 1 FROM webui_departments LIMIT 1"),
            ).fetchone()
        return row is not None

    def list_all(self) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        with self._connection() as (conn, dialect):
            rows = conn.execute(
                dialect.q(
                    "SELECT * FROM webui_departments ORDER BY id ASC",
                ),
            ).fetchall()
        return [_row_to_domain(row) for row in rows if _row_to_domain(row).get("id")]

    def get(self, department_id: str) -> dict[str, Any] | None:
        key = str(department_id or "").strip().lower()
        if not key or not self.enabled():
            return None
        with self._connection() as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT * FROM webui_departments WHERE id = ?"),
                (key,),
            ).fetchone()
        if not row:
            return None
        return _row_to_domain(row)

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        domain = _row_to_domain(row)
        dept_id = domain["id"]
        if not dept_id:
            raise ValueError("department id is required")
        with self._connection() as (conn, dialect):
            now = utc_now(dialect)
            actor = actor_or_system(row.get("created_by"), fallback=row.get("updated_by"))
            conn.execute(
                dialect.q(
                    """
                    INSERT INTO webui_departments (
                        id, label, description, created_at, updated_at,
                        created_by, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    dept_id,
                    domain["label"] or dept_id,
                    domain.get("description"),
                    now,
                    now,
                    actor,
                    actor,
                ),
            )
            conn.commit()
        return domain

    def update(self, department_id: str, row: dict[str, Any]) -> dict[str, Any]:
        key = str(department_id or "").strip().lower()
        existing = self.get(key)
        if existing is None:
            raise KeyError(f"department {key!r} not found")
        label = str(row.get("label", existing["label"]) or key).strip() or key
        description = row.get("description", existing.get("description"))
        if description is not None:
            description = str(description).strip() or None
        with self._connection() as (conn, dialect):
            now = utc_now(dialect)
            actor = actor_or_system(row.get("updated_by"))
            conn.execute(
                dialect.q(
                    """
                    UPDATE webui_departments
                    SET label = ?, description = ?, updated_at = ?, updated_by = ?
                    WHERE id = ?
                    """
                ),
                (label, description, now, actor, key),
            )
            conn.commit()
        return {
            **existing,
            "label": label,
            "description": description,
            "updated_at": from_db_timestamp(now),
            "updated_by": actor,
        }

    def delete(self, department_id: str) -> bool:
        key = str(department_id or "").strip().lower()
        if not key or not self.enabled():
            return False
        with self._connection() as (conn, dialect):
            cur = conn.execute(
                dialect.q("DELETE FROM webui_departments WHERE id = ?"),
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
        if not self.enabled() or self.has_departments():
            return False
        departments = document.get("departments")
        if not isinstance(departments, dict) or not departments:
            return False
        for department_id, row in departments.items():
            if not isinstance(row, dict):
                continue
            cleaned = str(department_id or "").strip().lower()
            if not cleaned:
                continue
            try:
                self.create(
                    {
                        "id": cleaned,
                        "label": row.get("label") or cleaned,
                        "description": row.get("description"),
                        "created_by": SYSTEM_ACTOR,
                        "updated_by": SYSTEM_ACTOR,
                    }
                )
            except Exception:
                logger.warning("Failed to import department %s", cleaned, exc_info=True)
        if json_path and json_path.is_file():
            logger.info("Migrated departments.json into webui_departments")
        return True

    def maybe_migrate_legacy(self, *, json_path: Path | None = None) -> bool:
        from app.storage.repositories.legacy_import import (
            legacy_import_done,
            mark_legacy_import_done,
        )

        table = "webui_departments"
        if not self.enabled():
            return False
        if self.has_departments():
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
            logger.debug("Failed to read departments.json for migration", exc_info=True)
            mark_legacy_import_done(table)
            return False
        imported = False
        if isinstance(raw, dict):
            imported = self.import_legacy_document(raw, json_path=json_path)
        mark_legacy_import_done(table)
        return imported


def get_departments_repository() -> WebuiDepartmentsRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = WebuiDepartmentsRepository()
        return _REPO
