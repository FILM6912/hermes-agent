"""Cross-dialect timestamp helpers for WebUI storage tables."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.storage.dialect import Dialect

# Columns stored as JSON objects (permission maps, etc.).
JSON_OBJECT_COLUMNS: dict[str, frozenset[str]] = {
    "webui_roles": frozenset({"permissions"}),
}

# Tables whose listed columns store instants (created/updated/expiry).
TIMESTAMP_COLUMNS: dict[str, frozenset[str]] = {
    "webui_meta": frozenset({"updated_at"}),
    "webui_kv": frozenset({"updated_at"}),
    "webui_history": frozenset({"created_at", "updated_at"}),
    "webui_users": frozenset({"created_at", "updated_at"}),
    "webui_profile_bindings": frozenset({"updated_at"}),
    "webui_auth_sessions": frozenset({"exp", "created_at", "updated_at"}),
    "webui_sessions": frozenset({"created_at", "updated_at"}),
    "webui_departments": frozenset({"created_at", "updated_at"}),
    "webui_roles": frozenset({"created_at", "updated_at"}),
    "webui_settings": frozenset({"updated_at"}),
}

# Normalized Supabase tables migrated from legacy REAL epoch columns.
POSTGRES_TIMESTAMP_MIGRATION_TABLES: dict[str, frozenset[str]] = {
    "webui_meta": frozenset({"updated_at"}),
    "webui_users": frozenset({"created_at", "updated_at"}),
    "webui_sessions": frozenset({"created_at", "updated_at"}),
    "webui_departments": frozenset({"created_at", "updated_at"}),
    "webui_roles": frozenset({"created_at", "updated_at"}),
    "webui_settings": frozenset({"updated_at"}),
    "webui_history": frozenset({"created_at", "updated_at"}),
    "webui_kv": frozenset({"updated_at"}),
    "webui_auth_sessions": frozenset({"exp", "created_at", "updated_at"}),
}


def timestamp_column_spec(dialect: Dialect) -> str:
    if dialect.name == "postgres":
        return "TIMESTAMPTZ NOT NULL"
    return "REAL NOT NULL"


def json_object_column_spec(dialect: Dialect) -> str:
    if dialect.name == "postgres":
        return "JSONB NOT NULL DEFAULT '{}'::jsonb"
    return "TEXT NOT NULL DEFAULT '{}'"


def resolve_column_spec(table: str, name: str, spec: str, dialect: Dialect) -> str:
    if name in JSON_OBJECT_COLUMNS.get(table, frozenset()):
        return json_object_column_spec(dialect)
    if name in TIMESTAMP_COLUMNS.get(table, frozenset()):
        return timestamp_column_spec(dialect)
    return spec


def utc_now(dialect: Dialect) -> float | datetime:
    if dialect.name == "postgres":
        return datetime.now(timezone.utc)
    return time.time()


def to_db_timestamp(value: Any, dialect: Dialect) -> float | datetime:
    """Normalize a unix float or datetime for DB write."""
    if dialect.name == "postgres":
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def from_db_timestamp(value: Any) -> float | None:
    """Convert a DB timestamp to unix float for API/JSON compatibility."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cutoff_for_query(now: float | None, dialect: Dialect) -> float | datetime:
    ts = time.time() if now is None else float(now)
    return to_db_timestamp(ts, dialect)
