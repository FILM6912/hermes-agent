"""Schema definitions and automatic table/column migration."""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.storage.dialect import Dialect, column_data_type, list_columns, table_exists
from app.storage.timestamps import (
    JSON_OBJECT_COLUMNS,
    POSTGRES_TIMESTAMP_MIGRATION_TABLES,
    resolve_column_spec,
    utc_now,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 6

_SCHEMA_READY: dict[str, int] = {}
_SCHEMA_READY_LOCK = threading.Lock()


def reset_schema_ready_cache() -> None:
    """Force a full schema ensure on the next connection (tests / recovery)."""
    with _SCHEMA_READY_LOCK:
        _SCHEMA_READY.clear()

_AUDIT_BY = "TEXT"
_AUDIT_AT = "REAL NOT NULL"

# Local SQLite tables (settings, auth tokens, workspaces KV, …).
LOCAL_TABLES: dict[str, dict[str, str]] = {
    "webui_meta": {
        "key": "TEXT PRIMARY KEY",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_kv": {
        "namespace": "TEXT NOT NULL",
        "profile": "TEXT NOT NULL DEFAULT ''",
        "key": "TEXT NOT NULL",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_history": {
        "id": "TEXT PRIMARY KEY",
        "namespace": "TEXT NOT NULL",
        "entity_type": "TEXT NOT NULL",
        "entity_id": "TEXT NOT NULL DEFAULT ''",
        "action": "TEXT NOT NULL",
        "profile": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_users": {
        "id": "TEXT PRIMARY KEY",
        "email": "TEXT NOT NULL UNIQUE",
        "role": "TEXT NOT NULL",
        "password_hash": "TEXT",
        "profile_name": "TEXT",
        "profile_names": "TEXT NOT NULL DEFAULT '[]'",
        "display_name": "TEXT",
        "department": "TEXT",
        "department_id": "TEXT",
        "position": "TEXT",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
        "enabled": "INTEGER NOT NULL DEFAULT 1",
        "mcp_api_key_hash": "TEXT",
    },
    "webui_profile_bindings": {
        "profile_name": "TEXT PRIMARY KEY",
        "user_email": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_auth_sessions": {
        "id": "TEXT PRIMARY KEY",
        "token_hash": "TEXT NOT NULL UNIQUE",
        "user_id": "TEXT NOT NULL",
        "role": "TEXT NOT NULL DEFAULT 'admin'",
        "exp": "REAL NOT NULL",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
    },
    "webui_settings": {
        "namespace": "TEXT NOT NULL",
        "key": "TEXT NOT NULL",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
}

# Backward-compatible alias for local schema consumers.
TABLES = LOCAL_TABLES

# Supabase/PostgreSQL: full WebUI state when PG is configured.
SUPABASE_TABLES: dict[str, dict[str, str]] = {
    "webui_meta": {
        "key": "TEXT PRIMARY KEY",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_kv": {
        "namespace": "TEXT NOT NULL",
        "profile": "TEXT NOT NULL DEFAULT ''",
        "key": "TEXT NOT NULL",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_history": {
        "id": "TEXT PRIMARY KEY",
        "namespace": "TEXT NOT NULL",
        "entity_type": "TEXT NOT NULL",
        "entity_id": "TEXT NOT NULL DEFAULT ''",
        "action": "TEXT NOT NULL",
        "profile": "TEXT NOT NULL DEFAULT ''",
        "payload": "TEXT NOT NULL DEFAULT '{}'",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_users": {
        "id": "TEXT PRIMARY KEY",
        "email": "TEXT NOT NULL UNIQUE",
        "role": "TEXT NOT NULL",
        "password_hash": "TEXT",
        "profile_name": "TEXT",
        "profile_names": "TEXT NOT NULL DEFAULT '[]'",
        "display_name": "TEXT",
        "department": "TEXT",
        "department_id": "TEXT",
        "position": "TEXT",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
        "enabled": "INTEGER NOT NULL DEFAULT 1",
        "mcp_api_key_hash": "TEXT",
    },
    "webui_profile_bindings": {
        "profile_name": "TEXT PRIMARY KEY",
        "user_email": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_auth_sessions": {
        "id": "TEXT PRIMARY KEY",
        "token_hash": "TEXT NOT NULL UNIQUE",
        "user_id": "TEXT NOT NULL",
        "role": "TEXT NOT NULL DEFAULT 'admin'",
        "exp": "REAL NOT NULL",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
    },
    "webui_settings": {
        "namespace": "TEXT NOT NULL",
        "key": "TEXT NOT NULL",
        "value": "TEXT NOT NULL",
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_sessions": {
        "id": "TEXT PRIMARY KEY",
        "user_id": "TEXT NOT NULL",
        "profile": "TEXT NOT NULL DEFAULT ''",
        "title": "TEXT NOT NULL DEFAULT ''",
        "workspace": "TEXT",
        "model": "TEXT",
        "model_provider": "TEXT",
        "conversation": "TEXT NOT NULL DEFAULT '{}'",
        "metadata": "TEXT NOT NULL DEFAULT '{}'",
        "pinned": "INTEGER NOT NULL DEFAULT 0",
        "archived": "INTEGER NOT NULL DEFAULT 0",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_departments": {
        "id": "TEXT PRIMARY KEY",
        "label": "TEXT NOT NULL",
        "description": "TEXT",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
    "webui_roles": {
        "id": "TEXT PRIMARY KEY",
        "label": "TEXT NOT NULL",
        "description": "TEXT",
        "permissions": "TEXT NOT NULL DEFAULT '{}'",
        "requires_profile": "INTEGER NOT NULL DEFAULT 0",
        "builtin": "INTEGER NOT NULL DEFAULT 0",
        "created_at": _AUDIT_AT,
        "updated_at": _AUDIT_AT,
        "created_by": _AUDIT_BY,
        "updated_by": _AUDIT_BY,
    },
}

INDEXES: list[tuple[str, str, str]] = [
    (
        "idx_webui_kv_namespace",
        "webui_kv",
        "CREATE INDEX IF NOT EXISTS idx_webui_kv_namespace ON webui_kv(namespace, profile)",
    ),
    (
        "idx_webui_history_entity",
        "webui_history",
        (
            "CREATE INDEX IF NOT EXISTS idx_webui_history_entity "
            "ON webui_history(namespace, entity_type, entity_id, created_at DESC)"
        ),
    ),
    (
        "idx_webui_history_created",
        "webui_history",
        "CREATE INDEX IF NOT EXISTS idx_webui_history_created ON webui_history(created_at DESC)",
    ),
    (
        "idx_webui_users_email",
        "webui_users",
        "CREATE INDEX IF NOT EXISTS idx_webui_users_email ON webui_users(email)",
    ),
    (
        "idx_webui_profile_bindings_user",
        "webui_profile_bindings",
        (
            "CREATE INDEX IF NOT EXISTS idx_webui_profile_bindings_user "
            "ON webui_profile_bindings(user_email)"
        ),
    ),
    (
        "idx_webui_auth_sessions_user_id",
        "webui_auth_sessions",
        "CREATE INDEX IF NOT EXISTS idx_webui_auth_sessions_user_id ON webui_auth_sessions(user_id, exp DESC)",
    ),
    (
        "idx_webui_auth_sessions_exp",
        "webui_auth_sessions",
        "CREATE INDEX IF NOT EXISTS idx_webui_auth_sessions_exp ON webui_auth_sessions(exp)",
    ),
    (
        "idx_webui_settings_namespace",
        "webui_settings",
        "CREATE INDEX IF NOT EXISTS idx_webui_settings_namespace ON webui_settings(namespace, key)",
    ),
]

SUPABASE_INDEXES: list[tuple[str, str, str]] = [
    (
        "idx_webui_kv_namespace",
        "webui_kv",
        "CREATE INDEX IF NOT EXISTS idx_webui_kv_namespace ON webui_kv(namespace, profile)",
    ),
    (
        "idx_webui_history_entity",
        "webui_history",
        (
            "CREATE INDEX IF NOT EXISTS idx_webui_history_entity "
            "ON webui_history(namespace, entity_type, entity_id, created_at DESC)"
        ),
    ),
    (
        "idx_webui_history_created",
        "webui_history",
        "CREATE INDEX IF NOT EXISTS idx_webui_history_created ON webui_history(created_at DESC)",
    ),
    (
        "idx_webui_users_email",
        "webui_users",
        "CREATE INDEX IF NOT EXISTS idx_webui_users_email ON webui_users(email)",
    ),
    (
        "idx_webui_profile_bindings_user",
        "webui_profile_bindings",
        (
            "CREATE INDEX IF NOT EXISTS idx_webui_profile_bindings_user "
            "ON webui_profile_bindings(user_email)"
        ),
    ),
    (
        "idx_webui_auth_sessions_user_id",
        "webui_auth_sessions",
        "CREATE INDEX IF NOT EXISTS idx_webui_auth_sessions_user_id ON webui_auth_sessions(user_id, exp DESC)",
    ),
    (
        "idx_webui_auth_sessions_exp",
        "webui_auth_sessions",
        "CREATE INDEX IF NOT EXISTS idx_webui_auth_sessions_exp ON webui_auth_sessions(exp)",
    ),
    (
        "idx_webui_settings_namespace",
        "webui_settings",
        "CREATE INDEX IF NOT EXISTS idx_webui_settings_namespace ON webui_settings(namespace, key)",
    ),
    (
        "idx_webui_chat_sessions_user_id",
        "webui_sessions",
        (
            "CREATE INDEX IF NOT EXISTS idx_webui_chat_sessions_user_id "
            "ON webui_sessions(user_id, updated_at DESC)"
        ),
    ),
    (
        "idx_webui_chat_sessions_updated",
        "webui_sessions",
        "CREATE INDEX IF NOT EXISTS idx_webui_chat_sessions_updated ON webui_sessions(updated_at DESC)",
    ),
]

_COMPOSITE_PRIMARY_KEYS: dict[str, str] = {
    "webui_kv": "PRIMARY KEY (namespace, profile, key)",
    "webui_settings": "PRIMARY KEY (namespace, key)",
}


def _create_table_sql(table: str, columns: dict[str, str], dialect: Dialect) -> str:
    parts = [
        f"{name} {resolve_column_spec(table, name, spec, dialect)}"
        for name, spec in columns.items()
    ]
    body = ", ".join(parts)
    pk = _COMPOSITE_PRIMARY_KEYS.get(table)
    if pk:
        body += f", {pk}"
    return f"CREATE TABLE IF NOT EXISTS {table} ({body})"


def _rollback_connection(conn: Any) -> None:
    try:
        if hasattr(conn, "rollback"):
            conn.rollback()
        elif hasattr(conn, "_conn"):
            conn._conn.rollback()
    except Exception:
        logger.debug("Failed rolling back WebUI DB connection during schema migrate", exc_info=True)


def _alter_add_column_sql(
    dialect: Dialect,
    table: str,
    column: str,
    spec: str,
) -> str:
    if dialect.name == "postgres":
        return f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {spec}"
    return f"ALTER TABLE {table} ADD COLUMN {column} {spec}"


def _ensure_table(conn: Any, dialect: Dialect, table: str, columns: dict[str, str]) -> None:
    if not table_exists(conn, dialect, table):
        conn.execute(_create_table_sql(table, columns, dialect))
        conn.commit()
        logger.info("Created WebUI storage table %s", table)
        return

    existing = list_columns(conn, dialect, table)
    for name, spec in columns.items():
        if name in existing:
            continue
        alter_spec = resolve_column_spec(table, name, spec, dialect)
        alter_spec = alter_spec.replace(" PRIMARY KEY", "").replace(" UNIQUE", "")
        # Existing rows cannot satisfy NOT NULL on ALTER ADD COLUMN (Postgres/SQLite).
        if " NOT NULL" in alter_spec.upper():
            alter_spec = alter_spec.replace(" NOT NULL", "").replace(" not null", "")
        try:
            conn.execute(_alter_add_column_sql(dialect, table, name, alter_spec))
            logger.info("Added column %s.%s", table, name)
        except Exception:
            _rollback_connection(conn)
            if name in list_columns(conn, dialect, table):
                logger.debug("Column %s.%s already present after rollback", table, name)
                continue
            raise
    conn.commit()


def _ensure_indexes(conn: Any, dialect: Dialect, *, extra: list[tuple[str, str, str]] | None = None) -> None:
    for _name, table, sql in INDEXES + (extra or []):
        if not table_exists(conn, dialect, table):
            continue
        conn.execute(sql)
    conn.commit()


def _get_schema_version(conn: Any, dialect: Dialect) -> int:
    row = conn.execute(
        dialect.q("SELECT value FROM webui_meta WHERE key = ?"),
        ("schema_version",),
    ).fetchone()
    if not row:
        return 0
    try:
        return int(str(row[0]))
    except (TypeError, ValueError):
        return 0


def _set_schema_version(conn: Any, dialect: Dialect, version: int) -> None:
    now = utc_now(dialect)
    conn.execute(
        dialect.q(
            """
            INSERT INTO webui_meta (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """
        ),
        ("schema_version", str(version), now),
    )
    conn.commit()


def _migrate_real_timestamp_columns(conn: Any, dialect: Dialect) -> None:
    """Convert legacy REAL/float epoch columns to TIMESTAMPTZ on PostgreSQL."""
    if dialect.name != "postgres":
        return
    for table, columns in POSTGRES_TIMESTAMP_MIGRATION_TABLES.items():
        if not table_exists(conn, dialect, table):
            continue
        for column in columns:
            data_type = column_data_type(conn, dialect, table, column)
            if data_type is None:
                continue
            if data_type in {"timestamp with time zone", "timestamp without time zone"}:
                continue
            if data_type not in {"real", "double precision"}:
                logger.warning(
                    "Skipping timestamp migration for %s.%s (unexpected type %s)",
                    table,
                    column,
                    data_type,
                )
                continue
            conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE TIMESTAMPTZ USING to_timestamp({column})"
            )
            logger.info("Migrated %s.%s from %s to TIMESTAMPTZ", table, column, data_type)
    conn.commit()


def _rename_legacy_auth_sessions_table(conn: Any, dialect: Dialect) -> None:
    """Rename local ``webui_sessions`` auth rows to ``webui_auth_sessions``."""
    if table_exists(conn, dialect, "webui_auth_sessions"):
        return
    if not table_exists(conn, dialect, "webui_sessions"):
        return
    cols = set(list_columns(conn, dialect, "webui_sessions"))
    if "token_hash" not in cols:
        return
    conn.execute("ALTER TABLE webui_sessions RENAME TO webui_auth_sessions")
    conn.commit()
    logger.info("Renamed legacy webui_sessions auth table to webui_auth_sessions")


def _drop_legacy_supabase_auth_sessions(conn: Any, dialect: Dialect) -> None:
    """Remove legacy auth-token ``webui_sessions`` before creating chat schema."""
    if dialect.name != "postgres":
        return
    if not table_exists(conn, dialect, "webui_sessions"):
        return
    cols = set(list_columns(conn, dialect, "webui_sessions"))
    if "token_hash" in cols and "conversation" not in cols:
        conn.execute("DROP TABLE webui_sessions")
        conn.commit()
        logger.info("Dropped legacy Supabase auth webui_sessions table")


def _migrate_json_object_columns(conn: Any, dialect: Dialect) -> None:
    """Convert legacy TEXT/array JSON columns to JSONB permission maps on PostgreSQL."""
    if dialect.name != "postgres":
        return
    pending_text_columns = False
    for table, columns in JSON_OBJECT_COLUMNS.items():
        if not table_exists(conn, dialect, table):
            continue
        for column in columns:
            data_type = column_data_type(conn, dialect, table, column)
            if data_type is None:
                continue
            if data_type in {"text", "character varying"}:
                pending_text_columns = True
                conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
                conn.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {column} "
                    f"TYPE JSONB USING COALESCE(NULLIF(trim({column}::text), ''), '{{}}')::jsonb"
                )
                conn.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{{}}'::jsonb"
                )
                logger.info("Migrated %s.%s from %s to JSONB", table, column, data_type)

    if table_exists(conn, dialect, "webui_roles"):
        perm_type = column_data_type(conn, dialect, "webui_roles", "permissions")
        if pending_text_columns or perm_type in {"text", "character varying"}:
            import json

            from app.domain.roles import coerce_permissions_map

            rows = conn.execute("SELECT id, permissions FROM webui_roles").fetchall()
            for row in rows:
                role_id = str(row[0])
                raw = row[1]
                if isinstance(raw, list):
                    mapped = coerce_permissions_map(raw)
                    conn.execute(
                        "UPDATE webui_roles SET permissions = %s::jsonb WHERE id = %s",
                        (json.dumps(mapped), role_id),
                    )
                    logger.info(
                        "Converted webui_roles.permissions array to map for %s",
                        role_id,
                    )
            conn.execute(
                "ALTER TABLE webui_roles ALTER COLUMN permissions SET DEFAULT '{}'::jsonb"
            )
    conn.commit()


def migrate_schema(
    conn: Any,
    dialect: Dialect,
    *,
    backend: str = "local",
) -> int:
    """Apply incremental schema migrations and return the active version."""
    if backend == "supabase":
        _drop_legacy_supabase_auth_sessions(conn, dialect)

    current = _get_schema_version(conn, dialect)
    if dialect.name == "postgres" and current < 3:
        _migrate_real_timestamp_columns(conn, dialect)
    if backend == "supabase" and dialect.name == "postgres":
        _migrate_json_object_columns(conn, dialect)
    if current < 4 and backend == "local":
        _rename_legacy_auth_sessions_table(conn, dialect)
    target = SCHEMA_VERSION
    if current < target:
        _set_schema_version(conn, dialect, target)
    return target


def ensure_schema(
    *,
    conn: Any | None = None,
    backend: str = "local",
) -> int:
    """Create missing tables/columns and return the active schema version."""
    from app.storage.config import get_database_url
    from app.storage.connection import db_connection
    from app.storage.dialect import dialect_for_url

    with _SCHEMA_READY_LOCK:
        if _SCHEMA_READY.get(backend) == SCHEMA_VERSION:
            return SCHEMA_VERSION

    if conn is None:
        with db_connection(backend=backend) as (managed_conn, managed_dialect):
            return _ensure_schema_on_connection(
                managed_conn,
                managed_dialect,
                backend=backend,
            )

    dialect = dialect_for_url(get_database_url(backend=backend))  # type: ignore[arg-type]
    return _ensure_schema_on_connection(conn, dialect, backend=backend)


def _ensure_schema_on_connection(
    conn: Any,
    dialect: Dialect,
    *,
    backend: str,
) -> int:
    """Create missing tables/columns on an open connection."""
    extra_indexes: list[tuple[str, str, str]] = []
    if backend == "supabase":
        for table, columns in SUPABASE_TABLES.items():
            _ensure_table(conn, dialect, table, columns)
        extra_indexes = SUPABASE_INDEXES
    else:
        for table, columns in LOCAL_TABLES.items():
            _ensure_table(conn, dialect, table, columns)
        extra_indexes = INDEXES

    _ensure_indexes(conn, dialect, extra=extra_indexes)
    version = migrate_schema(conn, dialect, backend=backend)
    with _SCHEMA_READY_LOCK:
        _SCHEMA_READY[backend] = SCHEMA_VERSION
    return version


def ensure_backend_schema(
    *,
    backend: str = "local",
    conn: Any | None = None,
) -> int:
    """Idempotent: create any missing WebUI tables/columns for ``backend``."""
    return ensure_schema(conn=conn, backend=backend)


def init_storage() -> dict[str, object]:
    """Initialize storage schema; safe to call on every startup."""
    from app.storage.config import (
        get_local_database_url,
        get_supabase_database_url,
        is_postgres_backend,
        primary_storage_backend,
        supabase_storage_enabled,
        uses_split_storage,
    )

    from app.storage.connection import db_connection

    version = SCHEMA_VERSION
    result: dict[str, object] = {
        "schema_version": version,
        "primary_backend": primary_storage_backend(),
        "supabase_enabled": supabase_storage_enabled(),
        "split_storage": uses_split_storage(),
    }

    if uses_split_storage() or not supabase_storage_enabled():
        local_error: str | None = None
        try:
            with db_connection(shared=False, backend="local") as (conn, _dialect):
                version = ensure_schema(conn=conn, backend="local")
        except Exception as exc:
            local_error = str(exc)
            logger.warning("Local WebUI schema ensure failed: %s", exc, exc_info=True)
        result["local_backend"] = (
            "postgres" if is_postgres_backend(get_local_database_url()) else "sqlite"
        )
        result["local_url_scheme"] = get_local_database_url().split(":", 1)[0]
        result["schema_version"] = version
        if local_error:
            result["local_schema_error"] = local_error

    if supabase_storage_enabled():
        try:
            with db_connection(shared=False, backend="supabase") as (conn, _dialect):
                ensure_schema(conn=conn, backend="supabase")
            supabase_url = get_supabase_database_url() or ""
            result["supabase_backend"] = "postgres"
            result["supabase_url_scheme"] = supabase_url.split(":", 1)[0]
        except Exception as exc:
            logger.warning("Supabase WebUI schema ensure failed: %s", exc, exc_info=True)
            result["supabase_schema_error"] = str(exc)

    try:
        from app.storage.repositories.users import get_users_repository

        backfilled = get_users_repository().backfill_department_ids()
        if backfilled:
            logger.info("Backfilled department_id for %s webui_users row(s)", backfilled)
            result["users_department_id_backfill"] = backfilled
    except Exception:
        logger.debug("webui_users department_id backfill skipped", exc_info=True)

    return result
