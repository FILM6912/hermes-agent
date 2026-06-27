"""Migrate legacy JSON state files into WebUI database storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.storage.config import primary_storage_backend, supabase_storage_enabled
from app.storage.store import WebuiStore, get_webui_store

logger = logging.getLogger(__name__)

KV_NORMALIZED_NAMESPACES: tuple[str, ...] = (
    "users",
    "auth_sessions",
    "session_users",
    "settings",
)

# namespace -> relative path under STATE_DIR
_JSON_SOURCES: tuple[tuple[str, str], ...] = (
    ("settings", "settings.json"),
    ("workspaces", "workspaces.json"),
    ("projects", "projects.json"),
    ("users", "users.json"),
    ("auth_sessions", ".sessions.json"),
    ("session_users", ".session_users.json"),
)


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Skipping JSON migration for %s: %s", path, exc)
        return None


def migrate_json_state_files(
    store: WebuiStore | None = None,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Import known JSON files into DB when the DB row is absent.

    When Supabase/Postgres is configured, all namespaces use the primary backend.
    Split SQLite + Supabase mode (tests) keeps workspaces/projects on local only
    when ``uses_split_storage()`` is true.

    Returns a map of namespace -> status (``imported``, ``skipped``, ``missing``).
    """
    from app.storage.config import uses_split_storage
    from app.domain.config import STATE_DIR

    store = store or get_webui_store()
    results: dict[str, str] = {}
    for namespace, rel in _JSON_SOURCES:
        path = STATE_DIR / rel
        existing = store.get_json(namespace, "_document")
        if existing is not None and not force:
            results[namespace] = "skipped"
            continue
        payload = _read_json(path)
        if payload is None:
            results[namespace] = "missing"
            continue
        store.set_json(namespace, "_document", payload)
        store.append_history(
            "migration",
            "json_file",
            "import",
            entity_id=rel,
            payload={
                "path": str(path),
                "namespace": namespace,
                "backend": (
                    "local"
                    if uses_split_storage() and namespace not in ("users", "settings", "auth_sessions", "session_users")
                    else primary_storage_backend()
                ),
            },
        )
        results[namespace] = "imported"
        logger.info("Migrated %s into WebUI DB namespace %s", path.name, namespace)
    return results


def migrate_kv_to_normalized_tables(
    store: WebuiStore | None = None,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Import ``webui_kv`` document blobs into normalized Supabase tables.

    Reads ``namespace=_document`` rows for users, auth_sessions, session_users,
    and settings; populates ``webui_users``, ``webui_sessions``, and
    ``webui_settings``. Idempotent — skips when ``kv_normalized_v1`` meta is set.
    """
    from app.storage.normalized import (
        is_normalized_active,
        set_normalized_active,
        write_document,
    )

    if not supabase_storage_enabled():
        return {"status": "skipped", "reason": "supabase_disabled"}

    if is_normalized_active() and not force:
        return {"status": "skipped", "reason": "already_migrated"}

    store = store or get_webui_store()
    results: dict[str, str] = {}

    for namespace in KV_NORMALIZED_NAMESPACES:
        if namespace == "settings":
            status = migrate_settings_from_kv(store=store, force=force)
            results[namespace] = status
            continue
        doc = store.get_json(namespace, "_document", _allow_kv=True)
        if doc is None:
            results[namespace] = "missing"
            continue
        try:
            write_document(namespace, doc)
            results[namespace] = "imported"
            logger.info("Migrated webui_kv namespace %s into normalized tables", namespace)
        except Exception as exc:
            logger.warning("Failed to migrate namespace %s: %s", namespace, exc)
            results[namespace] = "error"

    if any(status == "imported" for status in results.values()) or force:
        set_normalized_active()
        store.append_history(
            "migration",
            "kv_normalized",
            "import",
            payload={"namespaces": results},
        )
        results["status"] = "completed"
    else:
        results["status"] = "skipped"

    return results


def migrate_settings_from_kv(
    store: WebuiStore | None = None,
    *,
    force: bool = False,
) -> str:
    """Import ``webui_kv`` settings/_document into ``webui_settings`` rows."""
    from app.storage.repositories.settings import get_settings_repository

    store = store or get_webui_store()
    repo = get_settings_repository()
    if repo.has_rows() and not force:
        return "skipped"
    doc = store.get_json("settings", "_document", _allow_kv=True)
    if not isinstance(doc, dict):
        return "missing"
    if force or repo.import_legacy_document(doc):
        logger.info("Migrated settings KV document into webui_settings")
        return "imported"
    return "skipped"


def run_storage_migrations(
    store: WebuiStore | None = None,
    *,
    force: bool = False,
) -> dict[str, object]:
    """Run JSON file import then KV-to-normalized migration."""
    store = store or get_webui_store()
    json_results = migrate_json_state_files(store=store, force=force)
    settings_kv = migrate_settings_from_kv(store=store, force=force)
    kv_results = migrate_kv_to_normalized_tables(store=store, force=force)
    return {"json": json_results, "settings_kv": settings_kv, "normalized": kv_results}


def load_document(namespace: str, *, json_path: Path | None = None) -> Any | None:
    """Load a document namespace from DB, falling back to JSON file."""
    store = get_webui_store()
    doc = store.get_json(namespace, "_document")
    if doc is not None:
        return doc
    if json_path is None:
        from app.domain.config import STATE_DIR

        mapping = {ns: name for ns, name in _JSON_SOURCES}
        rel = mapping.get(namespace)
        if not rel:
            return None
        json_path = STATE_DIR / rel
    payload = _read_json(json_path)
    if payload is not None:
        try:
            store.set_json(namespace, "_document", payload)
            store.append_history(
                "migration",
                "json_file",
                "lazy_import",
                entity_id=json_path.name,
                payload={"namespace": namespace},
            )
        except Exception:
            logger.debug("Lazy JSON import failed for %s", namespace, exc_info=True)
    return payload


def save_document(namespace: str, payload: Any, *, json_path: Path | None = None) -> None:
    """Persist a document namespace to DB and mirror to JSON when path known."""
    store = get_webui_store()
    store.set_json(namespace, "_document", payload)
    store.append_history(
        namespace,
        "document",
        "save",
        payload={"keys": list(payload.keys()) if isinstance(payload, dict) else None},
    )
    if json_path is None:
        from app.domain.config import STATE_DIR

        mapping = {ns: name for ns, name in _JSON_SOURCES}
        rel = mapping.get(namespace)
        if rel:
            json_path = STATE_DIR / rel
    if json_path is not None:
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.debug("JSON mirror write failed for %s", json_path, exc_info=True)
