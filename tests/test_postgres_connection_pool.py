"""Regression: PostgreSQL connections must be pooled, not one-per-thread."""

from __future__ import annotations

import threading
from unittest import TestCase
from unittest.mock import patch

import app.storage.connection as conn_mod


class _FakePgConn:
    def __init__(self, conn_id: int) -> None:
        self.conn_id = conn_id
        self.autocommit = False

    def cursor(self):
        raise AssertionError("not used in this test")

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestPostgresConnectionPool(TestCase):
    def setUp(self) -> None:
        conn_mod.reset_shared_connection()
        self._created = 0
        self._lock = threading.Lock()

        def _fake_open(url: str) -> conn_mod._PgConnectionWrapper:
            with self._lock:
                self._created += 1
                conn_id = self._created
            return conn_mod._PgConnectionWrapper(_FakePgConn(conn_id))

        self._open_patch = patch.object(conn_mod, "_open_postgres", side_effect=_fake_open)
        self._open_patch.start()
        self.addCleanup(self._open_patch.stop)
        self.addCleanup(conn_mod.reset_shared_connection)

    def test_parallel_checkouts_reuse_pool_instead_of_unbounded_connect(self) -> None:
        url = "postgresql://postgres:secret@127.0.0.1:5432/postgres"
        pool = conn_mod._PostgresPool(url, max_size=3)
        acquired: list[conn_mod._PgConnectionWrapper] = []

        def worker() -> None:
            conn = pool.acquire()
            acquired.append(conn)
            pool.release(conn)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(self._created, 3, "pool must cap new PostgreSQL handshakes")
        self.assertEqual(pool.opened, 3)

    def test_db_connection_returns_postgres_connection_to_pool(self) -> None:
        url = "postgresql://postgres:secret@127.0.0.1:5432/postgres"

        with patch.object(conn_mod, "get_database_url", return_value=url):
            with patch.object(conn_mod, "is_postgres_backend", return_value=True):
                with conn_mod.db_connection(backend="supabase") as (first, _dialect):
                    first_id = first._conn.conn_id
                with conn_mod.db_connection(backend="supabase") as (second, _dialect):
                    second_id = second._conn.conn_id

        self.assertEqual(first_id, second_id)
        self.assertEqual(self._created, 1)
