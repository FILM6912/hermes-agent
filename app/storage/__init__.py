"""WebUI persistent storage — local SQLite + optional Supabase for users/history."""

from app.storage.config import (
    get_database_url,
    get_local_database_url,
    get_supabase_database_url,
    is_postgres_backend,
    supabase_storage_enabled,
)
from app.storage.schema import ensure_schema
from app.storage.store import WebuiStore, get_webui_store

__all__ = [
    "WebuiStore",
    "ensure_schema",
    "get_database_url",
    "get_local_database_url",
    "get_supabase_database_url",
    "get_webui_store",
    "is_postgres_backend",
    "supabase_storage_enabled",
]
