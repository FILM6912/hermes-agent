"""Database URL resolution for WebUI state storage."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse

# Namespaces migrated from webui_kv blobs into normalized Supabase tables.
SUPABASE_KV_NAMESPACES: frozenset[str] = frozenset({"users"})
NORMALIZED_KV_NAMESPACES: frozenset[str] = frozenset(SUPABASE_KV_NAMESPACES)


def _default_sqlite_url() -> str:
    from app.domain.config import STATE_DIR

    db_path = (STATE_DIR / "webui.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


def _build_postgres_url_from_pg_env() -> str | None:
    host = os.getenv("PG_HOST", "").strip()
    if not host:
        return None
    port = os.getenv("PG_PORT", "5432").strip() or "5432"
    database = os.getenv("PG_DATABASE", "postgres").strip() or "postgres"
    user = os.getenv("PG_USER", "postgres").strip() or "postgres"
    password = os.getenv("PG_PASSWORD", "")
    sslmode = os.getenv("PG_SSLMODE", "disable").strip() or "disable"
    auth = f"{quote_plus(user)}:{quote_plus(password)}@" if password else f"{quote_plus(user)}@"
    url = f"postgresql://{auth}{host}:{port}/{quote_plus(database, safe='')}"
    if sslmode and sslmode.lower() not in {"disable", "allow", "prefer"}:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode={quote_plus(sslmode)}"
    return url


@lru_cache
def get_local_database_url() -> str:
    """SQLite URL for local config (settings, workspaces, projects, …)."""
    explicit = os.getenv("HERMES_WEBUI_LOCAL_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    legacy = os.getenv("HERMES_WEBUI_DATABASE_URL", "").strip()
    if legacy and not _looks_like_postgres(legacy):
        return legacy
    return _default_sqlite_url()


@lru_cache
def get_supabase_database_url() -> str | None:
    """PostgreSQL/Supabase URL for users, sessions, and history — or None when disabled."""
    explicit = os.getenv("HERMES_WEBUI_SUPABASE_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    legacy = os.getenv("HERMES_WEBUI_DATABASE_URL", "").strip()
    if legacy and _looks_like_postgres(legacy):
        return legacy
    return _build_postgres_url_from_pg_env()


def supabase_storage_enabled() -> bool:
    return bool(get_supabase_database_url())


def uses_split_storage() -> bool:
    """True when an explicit local SQLite URL coexists with Supabase (tests / migration)."""
    if not supabase_storage_enabled():
        return False
    explicit = os.getenv("HERMES_WEBUI_LOCAL_DATABASE_URL", "").strip()
    if explicit:
        return is_sqlite_backend(explicit)
    legacy = os.getenv("HERMES_WEBUI_DATABASE_URL", "").strip()
    return bool(legacy) and not _looks_like_postgres(legacy)


def primary_storage_backend() -> str:
    """Active backend for WebUI state when Supabase/Postgres is configured."""
    return "supabase" if supabase_storage_enabled() else "local"


def backend_for_namespace(namespace: str) -> str:
    del namespace  # all namespaces share the primary backend
    return primary_storage_backend()


def backend_for_history() -> str:
    return primary_storage_backend()


def get_database_url(*, backend: str = "local") -> str:
    """Return the database URL for ``local`` or ``supabase`` storage."""
    if backend == "supabase":
        url = get_supabase_database_url()
        if not url:
            raise RuntimeError(
                "Supabase storage is not configured. Set HERMES_WEBUI_SUPABASE_DATABASE_URL "
                "or PG_HOST/PG_USER/PG_PASSWORD (same as document API)."
            )
        return url
    return get_local_database_url()


def is_postgres_backend(url: str | None = None) -> bool:
    parsed = urlparse(url or get_local_database_url())
    return parsed.scheme in {"postgres", "postgresql"}


def is_sqlite_backend(url: str | None = None) -> bool:
    parsed = urlparse(url or get_local_database_url())
    return parsed.scheme in {"sqlite", "file"} or not parsed.scheme


def sqlite_path_from_url(url: str | None = None) -> Path | None:
    parsed = urlparse(url or get_local_database_url())
    if parsed.scheme not in {"sqlite", "file", ""}:
        return None
    raw = parsed.path or parsed.netloc
    if not raw:
        return None
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        # sqlite:///C:/path on Windows
        return Path(raw[1:])
    if raw.startswith("/"):
        return Path(raw)
    return Path(raw)


def _looks_like_postgres(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in {"postgres", "postgresql"}


def clear_database_url_cache() -> None:
    get_local_database_url.cache_clear()
    get_supabase_database_url.cache_clear()
    from app.storage.schema import reset_schema_ready_cache

    reset_schema_ready_cache()
