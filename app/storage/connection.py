"""Database connection management for WebUI storage."""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Literal
from urllib.parse import urlparse

from app.storage.config import (
    backend_for_history,
    backend_for_namespace,
    get_database_url,
    is_postgres_backend,
    sqlite_path_from_url,
    supabase_storage_enabled,
)
from app.storage.dialect import Dialect, dialect_for_url

logger = logging.getLogger(__name__)

Backend = Literal["local", "supabase"]

_CONN_LOCK = threading.Lock()
# Per-thread SQLite reuse only — PostgreSQL uses the process-wide pool below.
_CONN_LOCAL = threading.local()

_PG_POOLS: dict[str, "_PostgresPool"] = {}
_PG_POOLS_LOCK = threading.Lock()
_PG_TLS = threading.local()


def _pg_pool_max_size() -> int:
    raw = os.getenv("HERMES_WEBUI_PG_POOL_SIZE", "8").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


def _local_conn_pool() -> dict[str, Any]:
    pool = getattr(_CONN_LOCAL, "pool", None)
    if pool is None:
        pool = {}
        _CONN_LOCAL.pool = pool
    return pool


def _local_url_pool() -> dict[str, str]:
    urls = getattr(_CONN_LOCAL, "urls", None)
    if urls is None:
        urls = {}
        _CONN_LOCAL.urls = urls
    return urls


def _prepare_connection(conn: Any) -> None:
    """Clear aborted transactions before reusing a connection."""
    _rollback_connection(conn)


class _PgConnectionWrapper:
    """Minimal psycopg connection wrapper with sqlite-like execute()."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


@dataclass
class _PgCheckout:
    conn: _PgConnectionWrapper
    url: str
    depth: int = 0


def _pg_checkout_state() -> _PgCheckout | None:
    return getattr(_PG_TLS, "checkout", None)


class _PostgresPool:
    """Thread-safe checkout pool — reuse TCP connections across worker threads."""

    def __init__(self, url: str, *, max_size: int) -> None:
        self.url = url
        self.max_size = max_size
        self._available: queue.Queue[_PgConnectionWrapper] = queue.Queue()
        self._lock = threading.Lock()
        self._opened = 0
        parsed = urlparse(url)
        self._label = (
            f"{parsed.hostname or 'localhost'}:"
            f"{parsed.port or 5432}/"
            f"{(parsed.path or '/').lstrip('/') or 'postgres'}"
        )
        logger.info(
            "WebUI PostgreSQL pool ready for %s (max %s connections)",
            self._label,
            max_size,
        )

    @property
    def opened(self) -> int:
        with self._lock:
            return self._opened

    def acquire(self) -> _PgConnectionWrapper:
        try:
            conn = self._available.get_nowait()
            _prepare_connection(conn)
            return conn
        except queue.Empty:
            pass
        with self._lock:
            if self._opened < self.max_size:
                self._opened += 1
                logger.debug(
                    "WebUI storage opening PostgreSQL connection %s/%s to %s",
                    self._opened,
                    self.max_size,
                    self._label,
                )
                return _open_postgres(self.url)
        conn = self._available.get(timeout=30)
        _prepare_connection(conn)
        return conn

    def release(self, conn: _PgConnectionWrapper) -> None:
        _rollback_connection(conn)
        try:
            self._available.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._opened = max(0, self._opened - 1)

    def close_all(self) -> None:
        while True:
            try:
                conn = self._available.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._opened = 0


def _get_postgres_pool(url: str) -> _PostgresPool:
    with _PG_POOLS_LOCK:
        pool = _PG_POOLS.get(url)
        if pool is None:
            pool = _PostgresPool(url, max_size=_pg_pool_max_size())
            _PG_POOLS[url] = pool
        return pool


def _acquire_postgres(url: str) -> _PgConnectionWrapper:
    state = _pg_checkout_state()
    if state is not None and state.url == url and state.depth > 0:
        state.depth += 1
        _prepare_connection(state.conn)
        return state.conn
    conn = _get_postgres_pool(url).acquire()
    _PG_TLS.checkout = _PgCheckout(conn=conn, url=url, depth=1)
    return conn


def _release_postgres(url: str) -> None:
    state = _pg_checkout_state()
    if state is None or state.url != url:
        return
    state.depth -= 1
    if state.depth > 0:
        return
    _PG_TLS.checkout = None
    _get_postgres_pool(url).release(state.conn)


def reset_postgres_pools() -> None:
    """Close all pooled PostgreSQL connections (tests / shutdown)."""
    with _PG_POOLS_LOCK:
        pools = list(_PG_POOLS.values())
        _PG_POOLS.clear()
    for pool in pools:
        pool.close_all()
    if hasattr(_PG_TLS, "checkout"):
        del _PG_TLS.checkout


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL/Supabase storage requires psycopg. "
            "Install with: pip install 'psycopg[binary]>=3.2'"
        ) from exc
    return psycopg


def _open_postgres(url: str) -> _PgConnectionWrapper:
    psycopg = _require_psycopg()
    from psycopg.rows import namedtuple_row

    conn = psycopg.connect(url, row_factory=namedtuple_row)
    conn.autocommit = False
    return _PgConnectionWrapper(conn)


def _open_sqlite(url: str) -> sqlite3.Connection:
    path = sqlite_path_from_url(url)
    if path is None:
        raise ValueError(f"Invalid SQLite database URL: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    logger.debug("WebUI storage using SQLite at %s", path)
    return conn


def open_connection(*, backend: Backend = "local", url: str | None = None) -> Any:
    resolved = url or get_database_url(backend=backend)
    if is_postgres_backend(resolved):
        return _open_postgres(resolved)
    return _open_sqlite(resolved)


def _rollback_connection(conn: Any) -> None:
    try:
        if hasattr(conn, "rollback"):
            conn.rollback()
        elif hasattr(conn, "_conn"):
            conn._conn.rollback()
    except Exception:
        logger.debug("Failed rolling back WebUI DB connection", exc_info=True)


def _invalidate_shared_connection(backend: Backend) -> None:
    pool = _local_conn_pool()
    urls = _local_url_pool()
    conn = pool.pop(backend, None)
    urls.pop(backend, None)
    if conn is None:
        return
    _rollback_connection(conn)
    try:
        conn.close()
    except Exception:
        logger.debug("Failed closing invalidated WebUI DB connection", exc_info=True)


def _apply_schema(conn: Any, *, backend: Backend) -> None:
    from app.storage.schema import ensure_schema

    try:
        ensure_schema(conn=conn, backend=backend)
        conn.commit()
    except Exception:
        _rollback_connection(conn)
        raise


def _open_shared_sqlite(*, backend: Backend, url: str) -> Any:
    conn = open_connection(backend=backend, url=url)
    _apply_schema(conn, backend=backend)
    return conn


def get_shared_connection(*, backend: Backend = "local") -> Any:
    """Return a reusable SQLite connection for the current thread."""
    url = get_database_url(backend=backend)
    if is_postgres_backend(url):
        return _acquire_postgres(url)
    pool = _local_conn_pool()
    urls = _local_url_pool()
    conn = pool.get(backend)
    if conn is not None and urls.get(backend) == url:
        _prepare_connection(conn)
        return conn
    if conn is not None:
        _invalidate_shared_connection(backend)
    conn = _open_shared_sqlite(backend=backend, url=url)
    pool[backend] = conn
    urls[backend] = url
    return conn


def reset_shared_connection() -> None:
    with _CONN_LOCK:
        pool = getattr(_CONN_LOCAL, "pool", None)
        if pool:
            for conn in list(pool.values()):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        if hasattr(_CONN_LOCAL, "pool"):
            del _CONN_LOCAL.pool
        if hasattr(_CONN_LOCAL, "urls"):
            del _CONN_LOCAL.urls
    reset_postgres_pools()


def resolve_backend(*, namespace: str | None = None, for_history: bool = False) -> Backend:
    from app.storage.config import primary_storage_backend

    if for_history:
        resolved = backend_for_history()
    elif namespace is not None:
        resolved = backend_for_namespace(namespace)
    else:
        resolved = primary_storage_backend()
    return "supabase" if resolved == "supabase" else "local"


@contextmanager
def db_connection(
    *,
    shared: bool = True,
    backend: Backend | None = None,
    namespace: str | None = None,
    for_history: bool = False,
) -> Iterator[tuple[Any, Dialect]]:
    resolved_backend = backend or resolve_backend(namespace=namespace, for_history=for_history)
    url = get_database_url(backend=resolved_backend)
    dialect = dialect_for_url(url)
    if shared and is_postgres_backend(url):
        conn = _acquire_postgres(url)
        try:
            yield conn, dialect
        except Exception:
            _rollback_connection(conn)
            raise
        finally:
            _release_postgres(url)
    elif shared:
        conn = get_shared_connection(backend=resolved_backend)
        try:
            yield conn, dialect
        except Exception:
            _rollback_connection(conn)
            raise
    else:
        conn = open_connection(backend=resolved_backend, url=url)
        try:
            from app.storage.schema import ensure_schema

            ensure_schema(conn=conn, backend=resolved_backend)
            yield conn, dialect
            conn.commit()
        except Exception:
            if is_postgres_backend(url):
                conn._conn.rollback()
            else:
                conn.rollback()
            raise
        finally:
            if is_postgres_backend(url):
                try:
                    conn.close()
                except Exception:
                    pass
            else:
                conn.close()


def health_check() -> dict[str, object]:
    from app.storage.config import uses_split_storage

    checks: dict[str, object] = {}
    overall = "ok"
    backends: tuple[Backend, ...] = ("local", "supabase")
    for backend in backends:
        if backend == "supabase" and not supabase_storage_enabled():
            continue
        if backend == "local" and supabase_storage_enabled() and not uses_split_storage():
            continue
        url = get_database_url(backend=backend)  # type: ignore[arg-type]
        entry: dict[str, object] = {
            "backend": "postgres" if is_postgres_backend(url) else "sqlite",
            "url_scheme": urlparse(url).scheme,
        }
        try:
            with db_connection(shared=False, backend=backend) as (conn, _dialect):
                row = conn.execute("SELECT 1").fetchone()
                ok = row is not None and int(row[0]) == 1
            entry["status"] = "ok" if ok else "error"
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = type(exc).__name__
            entry["message"] = str(exc)
            overall = "error"
        checks[backend] = entry
    return {"status": overall, "backends": checks}


def storage_health_status() -> dict[str, object]:
    """Alias for health_check used by deep health endpoints."""
    return health_check()
