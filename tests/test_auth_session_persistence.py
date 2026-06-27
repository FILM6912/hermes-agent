"""Regression tests: auth sessions persist across process restarts.

_sessions is an in-memory dict. Without persistence, any restart (launchd,
systemd, container) invalidates all active browser sessions and floods clients
with 401s until they clear cookies. The HMAC signing key already persists to
STATE_DIR; this PR persists the session table using the same pattern.
"""
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Isolate state dir so tests never touch real sessions
_TEST_STATE = Path(tempfile.mkdtemp())
os.environ["HERMES_WEBUI_STATE_DIR"] = str(_TEST_STATE)

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.domain.auth as auth


class TestSessionPersistence(unittest.TestCase):
    """Sessions survive a simulated process restart (module reload)."""

    def setUp(self) -> None:
        auth._sessions.clear()
        sessions_file = _TEST_STATE / '.sessions.json'
        if sessions_file.exists():
            sessions_file.unlink()
        db_path = _TEST_STATE / "webui.db"
        if db_path.exists():
            db_path.unlink()
        os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ.pop("HERMES_WEBUI_DATABASE_URL", None)
        os.environ.pop("HERMES_WEBUI_SUPABASE_DATABASE_URL", None)
        os.environ.pop("PG_HOST", None)
        from app.storage import connection as storage_connection
        from app.storage import config as storage_config
        from app.storage.repositories.sessions import reset_sessions_repository

        storage_connection.reset_shared_connection()
        storage_config.clear_database_url_cache()
        reset_sessions_repository()

    def _simulate_restart(self) -> None:
        """Reload auth module to simulate a fresh process start.

        api.auth does `from app.domain.config import STATE_DIR` at module level, so
        `_SESSIONS_FILE` is computed from app.domain.config.STATE_DIR at reload time.
        We temporarily override api.config.STATE_DIR so the reload uses the
        test state dir without reloading api.config itself (which would
        invalidate imported references like STREAM_PARTIAL_TEXT in other tests).
        """
        import app.domain.config as _config
        _saved = _config.STATE_DIR
        _config.STATE_DIR = _TEST_STATE
        try:
            importlib.reload(auth)
        finally:
            _config.STATE_DIR = _saved

    def test_session_survives_restart(self) -> None:
        """A session created before restart should still verify after reload."""
        from app.storage.schema import init_storage

        init_storage()
        cookie = auth.create_session()
        self.assertTrue(auth.verify_session(cookie))
        self._simulate_restart()
        self.assertTrue(
            auth.verify_session(cookie),
            "Session must survive process restart via webui_sessions",
        )

    def test_invalidated_session_does_not_survive_restart(self) -> None:
        """Invalidating a session must be reflected after reload."""
        from app.storage.schema import init_storage

        init_storage()
        cookie = auth.create_session()
        auth.invalidate_session(cookie)
        self._simulate_restart()
        self.assertFalse(
            auth.verify_session(cookie),
            "Invalidated session must not be reinstated after restart",
        )

    def test_expired_sessions_pruned_on_load(self) -> None:
        """Sessions that expire between restarts must not be loaded."""
        from app.storage.repositories.sessions import get_sessions_repository
        from app.storage.schema import init_storage

        init_storage()
        repo = get_sessions_repository()
        now = time.time()
        repo.create_session("expired_token", user_id="legacy", role="admin", exp=now - 10)
        repo.create_session("valid_token", user_id="legacy", role="admin", exp=now + 3600)
        auth._sessions.clear()
        self._simulate_restart()
        repo = get_sessions_repository()
        self.assertIsNone(repo.get_by_token("expired_token"))
        self.assertIsNotNone(repo.get_by_token("valid_token"))

    def test_sessions_file_permissions(self) -> None:
        """Legacy JSON mirror remains owner-read-only when DB persistence fails."""
        auth.create_session()
        sessions_file = _TEST_STATE / '.sessions.json'
        if sessions_file.exists():
            mode = oct(sessions_file.stat().st_mode & 0o777)
            self.assertEqual(mode, oct(0o600),
                             f".sessions.json permissions {mode} — expected 0o600")

    def test_malformed_sessions_file_starts_fresh(self) -> None:
        """A corrupt sessions file must not crash auth — start with empty dict."""
        sessions_file = _TEST_STATE / '.sessions.json'
        sessions_file.write_text("not valid json {{{{")
        self._simulate_restart()
        self.assertEqual(auth._sessions, {},
                         "Corrupt sessions file must result in empty session dict")

    def test_sessions_file_wrong_type_starts_fresh(self) -> None:
        """A sessions file containing a non-dict must be ignored."""
        sessions_file = _TEST_STATE / '.sessions.json'
        sessions_file.write_text(json.dumps(["list", "not", "dict"]))
        self._simulate_restart()
        self.assertEqual(auth._sessions, {})


if __name__ == "__main__":
    unittest.main()
