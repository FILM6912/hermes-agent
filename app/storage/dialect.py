"""SQL dialect helpers for SQLite and PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Dialect:
    name: str
    placeholder: str

    def q(self, sql: str) -> str:
        return sql.replace("?", self.placeholder)


SQLITE = Dialect(name="sqlite", placeholder="?")
POSTGRES = Dialect(name="postgres", placeholder="%s")


def dialect_for_url(url: str) -> Dialect:
    from app.storage.config import is_postgres_backend

    return POSTGRES if is_postgres_backend(url) else SQLITE


def table_exists(conn: Any, dialect: Dialect, table: str) -> bool:
    if dialect.name == "sqlite":
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchone()
    return row is not None


def list_columns(conn: Any, dialect: Dialect, table: str) -> set[str]:
    if dialect.name == "sqlite":
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def column_data_type(conn: Any, dialect: Dialect, table: str, column: str) -> str | None:
    """Return information_schema ``data_type`` for a column, or ``None``."""
    if dialect.name != "postgres":
        return None
    row = conn.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return str(row[0]) if row else None
