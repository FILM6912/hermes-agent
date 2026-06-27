"""Tests for WebUI database storage (SQLite default, schema auto-migration)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _use_isolated_storage(testcase: unittest.TestCase) -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix="webui-storage-test-"))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(state_dir, ignore_errors=True))
    db_path = state_dir / "webui.db"
    os.environ["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
    os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.pop("HERMES_WEBUI_DATABASE_URL", None)
    os.environ.pop("HERMES_WEBUI_SUPABASE_DATABASE_URL", None)
    os.environ.pop("PG_HOST", None)

    from app.storage import connection as conn_mod
    from app.storage import config as cfg_mod
    from app.storage.repositories import settings as settings_repo_mod
    from app.storage.schema import reset_schema_ready_cache
    from app.domain import config as domain_cfg

    domain_cfg.STATE_DIR = state_dir
    domain_cfg.SETTINGS_FILE = state_dir / "settings.json"
    domain_cfg.SESSION_DIR = state_dir / "sessions"
    conn_mod.reset_shared_connection()
    cfg_mod.clear_database_url_cache()
    reset_schema_ready_cache()
    settings_repo_mod.reset_settings_repository()
    testcase.addCleanup(conn_mod.reset_shared_connection)
    testcase.addCleanup(cfg_mod.clear_database_url_cache)
    testcase.addCleanup(settings_repo_mod.reset_settings_repository)
    return state_dir


class TestTimestampHelpers(unittest.TestCase):
    def test_sqlite_uses_real_epoch_values(self):
        from app.storage.dialect import SQLITE
        from app.storage.timestamps import (
            from_db_timestamp,
            timestamp_column_spec,
            to_db_timestamp,
            utc_now,
        )

        self.assertEqual(timestamp_column_spec(SQLITE), "REAL NOT NULL")
        now = utc_now(SQLITE)
        self.assertIsInstance(now, float)
        stored = to_db_timestamp(1_780_890_000.0, SQLITE)
        self.assertEqual(stored, 1_780_890_000.0)
        self.assertEqual(from_db_timestamp(stored), 1_780_890_000.0)

    def test_postgres_uses_timestamptz_values(self):
        from datetime import datetime, timezone

        from app.storage.dialect import POSTGRES
        from app.storage.timestamps import (
            from_db_timestamp,
            timestamp_column_spec,
            to_db_timestamp,
            utc_now,
        )

        self.assertEqual(timestamp_column_spec(POSTGRES), "TIMESTAMPTZ NOT NULL")
        now = utc_now(POSTGRES)
        self.assertIsInstance(now, datetime)
        self.assertEqual(now.tzinfo, timezone.utc)
        stored = to_db_timestamp(1_780_890_000.0, POSTGRES)
        self.assertIsInstance(stored, datetime)
        self.assertAlmostEqual(from_db_timestamp(stored), 1_780_890_000.0, places=3)


class TestWebuiStorageSchema(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)

    def test_creates_sqlite_db_and_tables(self):
        from app.storage.schema import init_storage
        from app.storage.config import get_local_database_url, sqlite_path_from_url

        info = init_storage()
        self.assertEqual(info["local_backend"], "sqlite")
        self.assertFalse(info["supabase_enabled"])
        db_path = sqlite_path_from_url(get_local_database_url())
        assert db_path is not None
        self.assertTrue(db_path.exists())

        with sqlite3.connect(str(db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("webui_kv", tables)
        self.assertIn("webui_history", tables)
        self.assertIn("webui_meta", tables)
        self.assertIn("webui_auth_sessions", tables)
        self.assertIn("webui_users", tables)
        self.assertIn("webui_profile_bindings", tables)
        self.assertIn("webui_settings", tables)

    def test_sqlite_timestamp_columns_remain_real(self):
        from app.storage.config import get_local_database_url, sqlite_path_from_url
        from app.storage.schema import init_storage

        init_storage()
        db_path = sqlite_path_from_url(get_local_database_url())
        assert db_path is not None
        with sqlite3.connect(str(db_path)) as conn:
            for table, column in (
                ("webui_users", "created_at"),
                ("webui_users", "updated_at"),
                ("webui_auth_sessions", "exp"),
                ("webui_auth_sessions", "created_at"),
                ("webui_settings", "updated_at"),
            ):
                row = conn.execute(f"PRAGMA table_info({table})").fetchall()
                types = {str(r[1]): str(r[2]).upper() for r in row}
                self.assertEqual(types.get(column), "REAL", f"{table}.{column}")

    def test_schema_version_tracks_migrations(self):
        from app.storage.schema import SCHEMA_VERSION, init_storage

        info = init_storage()
        self.assertEqual(info["schema_version"], SCHEMA_VERSION)
        self.assertGreaterEqual(SCHEMA_VERSION, 4)

    def test_adds_missing_columns_idempotently(self):
        from app.storage.schema import ensure_schema, TABLES
        from app.storage.connection import open_connection, reset_shared_connection

        reset_shared_connection()
        conn = open_connection()
        ensure_schema(conn=conn)
        conn.execute("ALTER TABLE webui_kv ADD COLUMN extra_note TEXT DEFAULT ''")
        conn.commit()
        ensure_schema(conn=conn)
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(webui_kv)").fetchall()
        }
        for name in TABLES["webui_kv"]:
            self.assertIn(name, cols)
        conn.close()


class TestWebuiStorageStore(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)

    def test_kv_roundtrip_and_history(self):
        from app.storage.store import get_webui_store
        from app.storage.schema import init_storage

        init_storage()
        store = get_webui_store()
        store.set_json("settings", "_document", {"theme": "dark", "language": "th"})
        loaded = store.get_json("settings", "_document")
        self.assertEqual(loaded["theme"], "dark")

        entry_id = store.append_history(
            "settings",
            "document",
            "save",
            payload={"theme": "dark"},
        )
        self.assertTrue(entry_id)
        history = store.list_history("settings", limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "save")


class TestSettingsRepository(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)
        from app.storage.schema import init_storage

        init_storage()

    def test_kv_roundtrip_and_complex_values(self):
        from app.storage.config import get_local_database_url, sqlite_path_from_url
        from app.storage.repositories.settings import get_settings_repository

        repo = get_settings_repository()
        repo.set("theme", "dark")
        repo.set("language", "th")
        repo.set("hidden_tabs", ["tasks", "kanban"])
        repo.set("onboarding_completed", True)

        self.assertEqual(repo.get("theme"), "dark")
        self.assertEqual(repo.get("language"), "th")
        self.assertEqual(repo.get("hidden_tabs"), ["tasks", "kanban"])
        self.assertTrue(repo.get("onboarding_completed"))

        all_settings = repo.get_all()
        self.assertEqual(all_settings["theme"], "dark")
        self.assertEqual(all_settings["hidden_tabs"], ["tasks", "kanban"])

        self.assertTrue(repo.delete("language"))
        self.assertIsNone(repo.get("language"))
        self.assertNotIn("language", repo.get_all())

        db_path = sqlite_path_from_url(get_local_database_url())
        assert db_path is not None
        with sqlite3.connect(str(db_path)) as conn:
            kv_rows = conn.execute(
                "SELECT COUNT(*) FROM webui_kv WHERE namespace='settings'"
            ).fetchone()[0]
        self.assertEqual(kv_rows, 0)

    def test_migrate_settings_from_kv(self):
        from app.storage.migrate import migrate_settings_from_kv
        from app.storage.repositories.settings import get_settings_repository
        from app.storage.store import get_webui_store

        store = get_webui_store()
        store.set_json(
            "settings",
            "_document",
            {"theme": "dark", "language": "en"},
            _allow_kv=True,
        )

        result = migrate_settings_from_kv()
        self.assertEqual(result, "imported")

        repo = get_settings_repository()
        self.assertEqual(repo.get("theme"), "dark")
        self.assertEqual(migrate_settings_from_kv(), "skipped")

    def test_save_document_replaces_stale_keys(self):
        from app.storage.repositories.settings import get_settings_repository

        repo = get_settings_repository()
        repo.save_document({"theme": "dark", "language": "en"})
        repo.save_document({"theme": "light"})

        doc = repo.load_document()
        assert doc is not None
        self.assertEqual(doc["theme"], "light")
        self.assertNotIn("language", doc)


class TestSettingsDbIntegration(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)

    def test_save_settings_writes_db_and_json_mirror(self):
        from app.domain import config as cfg_mod
        from app.storage.schema import init_storage

        init_storage()
        settings_path = cfg_mod.SETTINGS_FILE
        saved = cfg_mod.save_settings({"theme": "light", "language": "en"})
        self.assertEqual(saved["theme"], "light")

        reloaded = cfg_mod.load_settings()
        self.assertEqual(reloaded["theme"], "light")
        self.assertTrue(settings_path.exists())

        from app.storage.config import get_local_database_url, sqlite_path_from_url
        from app.storage.repositories.settings import get_settings_repository

        doc = get_settings_repository().load_document()
        self.assertIsInstance(doc, dict)
        self.assertEqual(doc.get("theme"), "light")

        db_path = sqlite_path_from_url(get_local_database_url())
        assert db_path is not None
        with sqlite3.connect(str(db_path)) as conn:
            kv_rows = conn.execute(
                "SELECT COUNT(*) FROM webui_kv WHERE namespace='settings'"
            ).fetchone()[0]
            setting_rows = conn.execute(
                "SELECT COUNT(*) FROM webui_settings WHERE namespace='settings'"
            ).fetchone()[0]
        self.assertEqual(kv_rows, 0)
        self.assertGreaterEqual(setting_rows, 1)


class TestJsonMigration(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)

    def test_migrates_settings_json_on_startup(self):
        from app.domain import config as cfg_mod
        from app.storage.migrate import migrate_json_state_files
        from app.storage.schema import init_storage

        init_storage()
        payload = {"theme": "dark", "onboarding_completed": True}
        cfg_mod.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg_mod.SETTINGS_FILE.write_text(json.dumps(payload), encoding="utf-8")

        result = migrate_json_state_files()
        self.assertEqual(result.get("settings"), "imported")

        from app.storage.store import get_webui_store

        doc = get_webui_store().get_json("settings", "_document")
        self.assertEqual(doc["theme"], "dark")


class TestSupabaseNamespaceRouting(unittest.TestCase):
    def setUp(self) -> None:
        state_dir = _use_isolated_storage(self)
        users_db = state_dir / "users.db"
        os.environ["HERMES_WEBUI_SUPABASE_DATABASE_URL"] = f"sqlite:///{users_db.as_posix()}"

        from app.storage import config as cfg_mod

        cfg_mod.clear_database_url_cache()

    def test_all_namespaces_use_supabase_when_configured(self):
        from app.storage.config import backend_for_namespace, supabase_storage_enabled
        from app.storage.schema import init_storage
        from app.storage.store import get_webui_store

        self.assertTrue(supabase_storage_enabled())
        for namespace in ("users", "settings", "workspaces"):
            self.assertEqual(backend_for_namespace(namespace), "supabase")

        init_storage()
        store = get_webui_store()
        store.set_json("users", "_document", {"version": 1, "users": {}})
        store.set_json("settings", "_document", {"theme": "dark"})
        store.set_json("workspaces", "_document", {"workspaces": []})

        from app.storage.config import get_supabase_database_url, sqlite_path_from_url

        supabase_path = sqlite_path_from_url(get_supabase_database_url())
        assert supabase_path is not None

        with sqlite3.connect(str(supabase_path)) as conn:
            kv_users = conn.execute(
                "SELECT value FROM webui_kv WHERE namespace='users'"
            ).fetchall()
            kv_workspaces = conn.execute(
                "SELECT value FROM webui_kv WHERE namespace='workspaces'"
            ).fetchall()
            remote_settings_rows = conn.execute(
                "SELECT key, value FROM webui_settings WHERE namespace='settings'"
            ).fetchall()

        self.assertEqual(len(kv_users), 1)
        self.assertEqual(len(kv_workspaces), 1)
        self.assertGreaterEqual(len(remote_settings_rows), 1)


class TestNormalizedSupabaseSchema(unittest.TestCase):
    def setUp(self) -> None:
        state_dir = _use_isolated_storage(self)
        users_db = state_dir / "users.db"
        os.environ["HERMES_WEBUI_SUPABASE_DATABASE_URL"] = f"sqlite:///{users_db.as_posix()}"

        from app.storage import config as cfg_mod

        cfg_mod.clear_database_url_cache()

    def test_creates_full_supabase_tables(self):
        import sqlite3

        from app.storage.config import get_supabase_database_url, sqlite_path_from_url
        from app.storage.schema import SUPABASE_TABLES, init_storage

        init_storage()
        db_path = sqlite_path_from_url(get_supabase_database_url())
        assert db_path is not None

        with sqlite3.connect(str(db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        for table in SUPABASE_TABLES:
            self.assertIn(table, tables)

    def test_migrate_kv_to_normalized_tables(self):
        import sqlite3

        from app.storage.config import (
            get_local_database_url,
            get_supabase_database_url,
            sqlite_path_from_url,
        )
        from app.storage.migrate import migrate_kv_to_normalized_tables
        from app.storage.normalized import is_normalized_active
        from app.storage.schema import init_storage
        from app.storage.store import get_webui_store

        init_storage()
        store = get_webui_store()
        store.set_json(
            "users",
            "_document",
            {
                "version": 1,
                "users": {
                    "admin@example.com": {
                        "email": "admin@example.com",
                        "role": "admin",
                        "password_hash": "a" * 64,
                        "profile_name": None,
                        "created_at": 1.0,
                    }
                },
                "profile_bindings": {},
            },
        )
        store.set_json(
            "settings",
            "_document",
            {"theme": "dark", "language": "en"},
            _allow_kv=True,
        )

        result = migrate_kv_to_normalized_tables()
        self.assertEqual(result.get("users"), "imported")
        self.assertEqual(result.get("settings"), "imported")
        self.assertTrue(is_normalized_active())

        loaded_users = store.get_json("users", "_document")
        self.assertIsInstance(loaded_users, dict)
        self.assertIn("admin@example.com", loaded_users.get("users", {}))

        loaded_settings = store.get_json("settings", "_document")
        self.assertEqual(loaded_settings.get("theme"), "dark")

        db_path = sqlite_path_from_url(get_supabase_database_url())
        assert db_path is not None
        with sqlite3.connect(str(db_path)) as conn:
            kv_users = conn.execute(
                "SELECT COUNT(*) FROM webui_kv WHERE namespace='users'"
            ).fetchone()[0]
        supabase_path = sqlite_path_from_url(get_supabase_database_url())
        assert supabase_path is not None
        with sqlite3.connect(str(supabase_path)) as conn:
            user_rows = conn.execute("SELECT COUNT(*) FROM webui_users").fetchone()[0]
            setting_rows = conn.execute(
                "SELECT COUNT(*) FROM webui_settings WHERE namespace='settings'"
            ).fetchone()[0]
        self.assertGreaterEqual(user_rows, 1)
        self.assertGreaterEqual(setting_rows, 1)
        self.assertGreaterEqual(kv_users, 1)
