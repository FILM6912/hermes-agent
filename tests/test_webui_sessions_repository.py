"""Tests for normalized auth session storage in webui_auth_sessions."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import app.domain.auth as auth
from app.core.security import get_current_user, session_valid
from app.repositories.auth import AuthRepository
from app.storage import config as storage_config
from app.storage import connection as storage_connection
from app.storage.repositories.sessions import (
    SessionsRepository,
    ensure_sessions_migrated,
    get_sessions_repository,
    hash_session_token,
    reset_sessions_repository,
)
from app.storage.schema import init_storage


def _use_isolated_storage(testcase: unittest.TestCase) -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix="webui-sessions-test-"))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(state_dir, ignore_errors=True))
    db_path = state_dir / "webui.db"
    os.environ["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
    os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.pop("HERMES_WEBUI_DATABASE_URL", None)
    os.environ.pop("HERMES_WEBUI_SUPABASE_DATABASE_URL", None)
    os.environ.pop("PG_HOST", None)

    from app.domain import config as domain_cfg

    domain_cfg.STATE_DIR = state_dir
    auth.STATE_DIR = state_dir
    auth._SESSIONS_FILE = state_dir / ".sessions.json"
    auth._sessions.clear()
    storage_connection.reset_shared_connection()
    storage_config.clear_database_url_cache()
    reset_sessions_repository()
    testcase.addCleanup(storage_connection.reset_shared_connection)
    testcase.addCleanup(storage_config.clear_database_url_cache)
    testcase.addCleanup(reset_sessions_repository)
    init_storage()
    ensure_sessions_migrated()
    return state_dir


class TestSessionsRepositoryCrud(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)
        self.repo = SessionsRepository()

    def test_create_get_revoke_roundtrip(self):
        token = "a" * 64
        exp = time.time() + 3600
        created = self.repo.create_session(
            token,
            user_id="alice@example.com",
            role="user",
            exp=exp,
        )
        self.assertEqual(created["user_id"], "alice@example.com")
        self.assertEqual(created["role"], "user")

        loaded = self.repo.get_by_token(token)
        assert loaded is not None
        self.assertEqual(loaded["user_id"], "alice@example.com")
        self.assertAlmostEqual(loaded["exp"], exp, delta=0.001)

        self.assertTrue(self.repo.revoke(token=token))
        self.assertIsNone(self.repo.get_by_token(token))

    def test_list_for_user_and_cleanup_expired(self):
        now = time.time()
        self.repo.create_session("token-a", user_id="alice@example.com", role="user", exp=now + 3600)
        self.repo.create_session("token-b", user_id="alice@example.com", role="user", exp=now - 10)
        self.repo.create_session("token-c", user_id="bob@example.com", role="admin", exp=now + 3600)

        alice_rows = self.repo.list_for_user("alice@example.com")
        self.assertEqual(len(alice_rows), 1)
        self.assertEqual(alice_rows[0]["user_id"], "alice@example.com")

        removed = self.repo.cleanup_expired(now=now)
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(self.repo.get_by_token("token-b"))
        self.assertIsNotNone(self.repo.get_by_token("token-a"))

    def test_ensure_sessions_migrated_retries_when_table_unavailable(self):
        """Migration must not mark complete when schema is not ready yet."""
        from unittest.mock import patch

        from app.storage.repositories import sessions as sessions_mod

        sessions_mod._MIGRATED = False
        original_count = self.repo.count

        def _fail_count():
            raise RuntimeError("table missing")

        self.repo.count = _fail_count  # type: ignore[method-assign]
        with patch.object(sessions_mod, "get_sessions_repository", return_value=self.repo):
            ensure_sessions_migrated()
        self.assertFalse(sessions_mod._MIGRATED)

        self.repo.count = original_count  # type: ignore[method-assign]
        ensure_sessions_migrated()
        self.assertTrue(sessions_mod._MIGRATED)

    def test_repository_uses_supabase_backend_when_configured(self):
        import os

        state_dir = Path(tempfile.mkdtemp(prefix="webui-sessions-supabase-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(state_dir, ignore_errors=True))
        supabase_db = state_dir / "supabase.db"
        os.environ["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
        os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{(state_dir / 'local.db').as_posix()}"
        os.environ["HERMES_WEBUI_SUPABASE_DATABASE_URL"] = f"sqlite:///{supabase_db.as_posix()}"

        from app.domain import config as domain_cfg
        from app.storage import config as storage_config
        from app.storage import connection as storage_connection

        domain_cfg.STATE_DIR = state_dir
        storage_connection.reset_shared_connection()
        storage_config.clear_database_url_cache()
        reset_sessions_repository()
        init_storage()

        repo = get_sessions_repository()
        self.assertEqual(repo.backend, "supabase")
        self.repo = repo
        self.test_create_get_revoke_roundtrip()

    def test_import_from_legacy_documents(self):
        now = time.time()
        auth_doc = {
            "legacy-token": now + 7200,
            "user-token": {
                "exp": now + 7200,
                "user_id": "legacy",
                "role": "admin",
            },
        }
        users_doc = {"user-token": "film@example.com"}
        imported = self.repo.import_from_documents(auth_doc, users_doc)
        self.assertEqual(imported, 2)

        user_row = self.repo.get_by_token("user-token")
        assert user_row is not None
        self.assertEqual(user_row["user_id"], "film@example.com")
        self.assertEqual(user_row["role"], "admin")


class TestAuthFlowWithSessionsRepository(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)
        auth._sessions.clear()

    def _signed_session(self, raw_token: str) -> str:
        exp = time.time() + 3600
        auth._persist_session(
            raw_token,
            {"exp": exp, "user_id": "legacy", "role": "admin"},
        )
        sig = hmac.new(auth._signing_key(), raw_token.encode(), hashlib.sha256).hexdigest()
        return f"{raw_token}.{sig}"

    def test_create_and_verify_session_uses_db(self):
        cookie = auth.create_session()
        token = cookie.split(".", 1)[0]
        self.assertTrue(auth.verify_session(cookie))

        repo = get_sessions_repository()
        self.assertIsNotNone(repo.get_by_token(token))
        auth.invalidate_session(cookie)
        self.assertFalse(auth.verify_session(cookie))
        self.assertIsNone(repo.get_by_token(token))

    def test_login_and_bearer_auth(self):
        auth._sessions.clear()
        monkeypatch_targets = {
            "is_auth_enabled": lambda: True,
            "verify_password": lambda _plain: True,
            "_check_login_rate": lambda _ip: True,
        }
        for name, fn in monkeypatch_targets.items():
            setattr(auth, name, fn)

        payload, status, cookie = AuthRepository().login("secret", client_ip="127.0.0.1")
        self.assertEqual(status, 200)
        assert cookie is not None
        self.assertEqual(payload["access_token"], cookie)

        class _Request:
            cookies = {}
            headers = {"authorization": f"Bearer {cookie}"}

        self.assertTrue(session_valid(_Request()))
        user = get_current_user(_Request())
        assert user is not None
        self.assertEqual(user.role, "admin")

    def test_session_survives_process_cache_reset(self):
        cookie = auth.create_session(user_id="legacy", role="admin")
        token = cookie.split(".", 1)[0]
        auth._sessions.clear()
        self.assertTrue(auth.verify_session(cookie))
        self.assertIsNotNone(get_sessions_repository().get_by_token(token))


if __name__ == "__main__":
    unittest.main()
