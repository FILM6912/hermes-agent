"""Dynamic WebUI department definitions."""

from __future__ import annotations

import json
import logging
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.config import STATE_DIR

logger = logging.getLogger(__name__)

DEPARTMENTS_FILE = STATE_DIR / "departments.json"
_DEPARTMENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

_departments_cache: dict[str, Any] | None = None
_departments_cache_lock = threading.Lock()


class DepartmentError(ValueError):
    """Raised when a department record violates storage invariants."""


class DepartmentNotFoundError(DepartmentError):
    """Raised when a department id is not present in the store."""


@dataclass(frozen=True)
class DepartmentRecord:
    department_id: str
    label: str
    description: str | None = None


def invalidate_departments_cache() -> None:
    global _departments_cache
    with _departments_cache_lock:
        _departments_cache = None


def validate_department_id(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned or not _DEPARTMENT_ID_RE.match(cleaned):
        raise DepartmentError(
            "department id must start with a letter and use lowercase letters, digits, _ or -"
        )
    return cleaned


def normalize_department_ref(value: str | None) -> str | None:
    cleaned = str(value or "").strip().lower()
    return cleaned or None


def generate_department_id() -> str:
    """Return a random id that satisfies ``validate_department_id``."""
    return f"d{secrets.token_hex(4)}"


def allocate_department_id() -> str:
    """Pick a random department id that is not already in use."""
    for _ in range(16):
        candidate = generate_department_id()
        if not department_exists(candidate):
            return candidate
    raise DepartmentError("could not allocate a unique department id")


def _record_from_row(department_id: str, row: dict[str, Any]) -> DepartmentRecord:
    return DepartmentRecord(
        department_id=department_id,
        label=str(row.get("label") or department_id).strip() or department_id,
        description=str(row.get("description") or "").strip() or None,
    )


def _public_department(record: DepartmentRecord) -> dict[str, Any]:
    return {
        "id": record.department_id,
        "label": record.label,
        "description": record.description,
    }


def _load_store_unlocked() -> dict[str, Any]:
    global _departments_cache
    if _departments_cache is not None and not _use_supabase_store():
        return _departments_cache
    payload: dict[str, Any] = {
        "version": 1,
        "updated_at": time.time(),
        "departments": {},
    }
    if DEPARTMENTS_FILE.is_file():
        try:
            raw = json.loads(DEPARTMENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("departments"), dict):
                payload = raw
        except Exception:
            logger.warning("Failed to read departments.json; using empty store", exc_info=True)
    _departments_cache = payload
    return payload


def _save_store_unlocked(store: dict[str, Any]) -> None:
    global _departments_cache
    store = dict(store)
    store["version"] = int(store.get("version") or 1)
    store["updated_at"] = time.time()
    departments = store.get("departments")
    if not isinstance(departments, dict):
        raise DepartmentError("departments store is invalid")
    DEPARTMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=DEPARTMENTS_FILE.parent,
        prefix=".departments.",
        suffix=".tmp",
    )
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(tmp_path).chmod(0o600)
        Path(tmp_path).replace(DEPARTMENTS_FILE)
    finally:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    _departments_cache = store


def _use_supabase_store() -> bool:
    try:
        from app.storage.config import supabase_storage_enabled

        return supabase_storage_enabled()
    except Exception:
        return False


def _supabase_repo():
    from app.storage.repositories.departments import get_departments_repository

    repo = get_departments_repository()
    repo.maybe_migrate_legacy(json_path=DEPARTMENTS_FILE)
    return repo


def ensure_departments_store() -> None:
    if _use_supabase_store():
        _supabase_repo()
        return
    with _departments_cache_lock:
        if not DEPARTMENTS_FILE.is_file():
            _save_store_unlocked(
                {
                    "version": 1,
                    "updated_at": time.time(),
                    "departments": {},
                }
            )


def list_departments() -> list[dict[str, Any]]:
    ensure_departments_store()
    if _use_supabase_store():
        return [
            {
                **_public_department(
                    _record_from_row(
                        row["id"],
                        {
                            "label": row.get("label"),
                            "description": row.get("description"),
                        },
                    )
                ),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "created_by": row.get("created_by"),
                "updated_by": row.get("updated_by"),
            }
            for row in _supabase_repo().list_all()
        ]
    store = _load_store_unlocked()
    departments = store.get("departments") or {}
    result: list[dict[str, Any]] = []
    for department_id in sorted(departments.keys()):
        row = departments.get(department_id)
        if not isinstance(row, dict):
            continue
        result.append(_public_department(_record_from_row(str(department_id), row)))
    return result


def get_department(department_id: str) -> DepartmentRecord:
    ensure_departments_store()
    cleaned = validate_department_id(department_id)
    if _use_supabase_store():
        row = _supabase_repo().get(cleaned)
        if row is None:
            raise DepartmentNotFoundError(f"department {cleaned!r} not found")
        return _record_from_row(
            cleaned,
            {"label": row.get("label"), "description": row.get("description")},
        )
    row = _load_store_unlocked().get("departments", {}).get(cleaned)
    if not isinstance(row, dict):
        raise DepartmentNotFoundError(f"department {cleaned!r} not found")
    return _record_from_row(cleaned, row)


def department_exists(department_id: str | None) -> bool:
    cleaned = normalize_department_ref(department_id)
    if not cleaned:
        return False
    try:
        get_department(cleaned)
        return True
    except (DepartmentError, DepartmentNotFoundError):
        return False


def count_users_with_department(department_id: str) -> int:
    from app.domain.users import list_users

    cleaned = normalize_department_ref(department_id)
    if not cleaned:
        return 0
    return sum(
        1
        for row in list_users()
        if normalize_department_ref(row.get("department_id") or row.get("department"))
        == cleaned
    )


def create_department(
    department_id: str | None = None,
    *,
    label: str,
    description: str | None = None,
) -> dict[str, Any]:
    cleaned = validate_department_id(department_id) if department_id else allocate_department_id()
    ensure_departments_store()
    if _use_supabase_store():
        repo = _supabase_repo()
        if repo.get(cleaned) is not None:
            raise DepartmentError(f"department {cleaned!r} already exists")
        row = {
            "label": str(label or cleaned).strip() or cleaned,
            "description": str(description or "").strip() or None,
        }
        repo.create({"id": cleaned, **row})
        return _public_department(_record_from_row(cleaned, row))
    with _departments_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "departments": dict(_load_store_unlocked().get("departments") or {}),
        }
        if cleaned in store["departments"]:
            raise DepartmentError(f"department {cleaned!r} already exists")
        row = {
            "label": str(label or cleaned).strip() or cleaned,
            "description": str(description or "").strip() or None,
        }
        store["departments"][cleaned] = row
        _save_store_unlocked(store)
        return _public_department(_record_from_row(cleaned, row))


def update_department(department_id: str, **fields: Any) -> dict[str, Any]:
    cleaned = validate_department_id(department_id)
    ensure_departments_store()
    if _use_supabase_store():
        repo = _supabase_repo()
        existing = repo.get(cleaned)
        if existing is None:
            raise DepartmentNotFoundError(f"department {cleaned!r} not found")
        payload: dict[str, Any] = {}
        if "label" in fields and fields["label"] is not None:
            payload["label"] = str(fields["label"]).strip() or cleaned
        if "description" in fields:
            payload["description"] = str(fields["description"] or "").strip() or None
        updated = repo.update(cleaned, {**existing, **payload})
        return _public_department(
            _record_from_row(
                cleaned,
                {"label": updated.get("label"), "description": updated.get("description")},
            )
        )
    with _departments_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "departments": dict(_load_store_unlocked().get("departments") or {}),
        }
        row = store["departments"].get(cleaned)
        if not isinstance(row, dict):
            raise DepartmentNotFoundError(f"department {cleaned!r} not found")
        updated = dict(row)
        if "label" in fields and fields["label"] is not None:
            updated["label"] = str(fields["label"]).strip() or cleaned
        if "description" in fields:
            updated["description"] = str(fields["description"] or "").strip() or None
        store["departments"][cleaned] = updated
        _save_store_unlocked(store)
        return _public_department(_record_from_row(cleaned, updated))


def delete_department(department_id: str) -> None:
    cleaned = validate_department_id(department_id)
    ensure_departments_store()
    assigned = count_users_with_department(cleaned)
    if assigned:
        raise DepartmentError(
            f"department {cleaned!r} is assigned to {assigned} user(s); reassign them first"
        )
    if _use_supabase_store():
        repo = _supabase_repo()
        if repo.get(cleaned) is None:
            raise DepartmentNotFoundError(f"department {cleaned!r} not found")
        repo.delete(cleaned)
        return
    with _departments_cache_lock:
        store = {
            "version": _load_store_unlocked().get("version", 1),
            "updated_at": _load_store_unlocked().get("updated_at"),
            "departments": dict(_load_store_unlocked().get("departments") or {}),
        }
        if cleaned not in store["departments"]:
            raise DepartmentNotFoundError(f"department {cleaned!r} not found")
        store["departments"].pop(cleaned, None)
        _save_store_unlocked(store)
