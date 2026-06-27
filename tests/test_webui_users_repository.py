"""Tests for normalized webui_users storage repository."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _use_isolated_storage(testcase: unittest.TestCase) -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix="webui-users-repo-test-"))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(state_dir, ignore_errors=True))
    db_path = state_dir / "webui.db"
    os.environ["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
    os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.pop("HERMES_WEBUI_DATABASE_URL", None)
    os.environ.pop("HERMES_WEBUI_SUPABASE_DATABASE_URL", None)
    os.environ.pop("PG_HOST", None)

    from app.storage import connection as conn_mod
    from app.storage import config as cfg_mod
    from app.storage.repositories import users as users_repo_mod
    from app.domain import config as domain_cfg
    from app.domain import users as users_domain

    domain_cfg.STATE_DIR = state_dir
    users_domain.STATE_DIR = state_dir
    users_domain.USERS_FILE = state_dir / "users.json"
    users_domain.invalidate_users_cache()
    conn_mod.reset_shared_connection()
    cfg_mod.clear_database_url_cache()
    users_repo_mod.reset_users_repository()
    testcase.addCleanup(conn_mod.reset_shared_connection)
    testcase.addCleanup(cfg_mod.clear_database_url_cache)
    testcase.addCleanup(users_repo_mod.reset_users_repository)
    testcase.addCleanup(users_domain.invalidate_users_cache)
    return state_dir


class TestWebuiUsersRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.state_dir = _use_isolated_storage(self)
        from app.storage.schema import init_storage

        init_storage()

    def test_crud_roundtrip(self):
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        created = repo.create(
            {
                "email": "alice@example.com",
                "role": "user",
                "profile_name": "alice",
                "profile_names": ["alice"],
                "password_hash": "a" * 64,
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        self.assertEqual(created["email"], "alice@example.com")

        loaded = repo.get_by_email("alice@example.com")
        assert loaded is not None
        self.assertEqual(loaded["profile_name"], "alice")
        self.assertEqual(repo.get_by_id("alice@example.com")["email"], "alice@example.com")

        updated = repo.update(
            "alice@example.com",
            {"display_name": "Alice", "updated_at": 2.0},
        )
        self.assertEqual(updated["display_name"], "Alice")

        users = repo.list_all()
        self.assertEqual([row["email"] for row in users], ["alice@example.com"])

        self.assertTrue(repo.delete("alice@example.com"))
        self.assertIsNone(repo.get_by_email("alice@example.com"))

    def test_department_id_synced_with_department(self):
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        created = repo.create(
            {
                "email": "dept@example.com",
                "role": "user",
                "profile_name": "dept",
                "profile_names": ["dept"],
                "password_hash": "d" * 64,
                "department": "HR",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        self.assertEqual(created["department"], "hr")
        self.assertEqual(created["department_id"], "hr")

        loaded = repo.get_by_email("dept@example.com")
        assert loaded is not None
        self.assertEqual(loaded["department_id"], "hr")

        updated = repo.update(
            "dept@example.com",
            {"department": "it", "updated_at": 2.0},
        )
        self.assertEqual(updated["department"], "it")
        self.assertEqual(updated["department_id"], "it")

    def test_profile_bindings_persist(self):
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        repo.create(
            {
                "email": "bob@example.com",
                "role": "user",
                "profile_name": "bob",
                "profile_names": ["bob"],
                "password_hash": "b" * 64,
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        repo.replace_profile_bindings({"bob": "bob@example.com"})
        bindings = repo.get_profile_bindings()
        self.assertEqual(bindings, {"bob": "bob@example.com"})

    def test_migrates_kv_document_into_table(self):
        from app.storage.repositories.users import get_users_repository
        from app.storage.store import get_webui_store

        payload = {
            "version": 1,
            "users": {
                "carol@example.com": {
                    "email": "carol@example.com",
                    "role": "user",
                    "profile_name": "carol",
                    "profile_names": ["carol"],
                    "password_hash": "c" * 64,
                    "created_at": 3.0,
                    "updated_at": 3.0,
                }
            },
            "profile_bindings": {"carol": "carol@example.com"},
        }
        get_webui_store().set_json("users", "_document", payload)

        repo = get_users_repository()
        self.assertTrue(repo.maybe_migrate_legacy(json_path=self.state_dir / "users.json"))
        loaded = repo.get_by_email("carol@example.com")
        assert loaded is not None
        self.assertEqual(loaded["profile_name"], "carol")
        self.assertEqual(repo.get_profile_bindings(), {"carol": "carol@example.com"})

    def test_domain_save_writes_table_and_json_mirror_without_supabase(self):
        import app.domain.users as users_domain

        users_domain.create_user(
            "dana@example.com",
            role="user",
            profile_name="dana",
            password_hash="d" * 64,
        )
        users_file = self.state_dir / "users.json"
        self.assertTrue(users_file.exists())

        db_path = self.state_dir / "webui.db"
        with sqlite3.connect(str(db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM webui_users").fetchone()[0]
        self.assertEqual(count, 1)

        on_disk = json.loads(users_file.read_text(encoding="utf-8"))
        self.assertIn("dana@example.com", on_disk["users"])

    def test_domain_skips_json_mirror_when_supabase_configured(self):
        users_db = self.state_dir / "users-remote.db"
        os.environ["HERMES_WEBUI_SUPABASE_DATABASE_URL"] = f"sqlite:///{users_db.as_posix()}"

        from app.storage import config as cfg_mod
        from app.storage import connection as conn_mod
        from app.storage.repositories import users as users_repo_mod
        from app.storage.schema import init_storage
        import app.domain.users as users_domain

        cfg_mod.clear_database_url_cache()
        conn_mod.reset_shared_connection()
        users_repo_mod.reset_users_repository()
        users_domain.invalidate_users_cache()
        init_storage()

        users_domain.create_user(
            "erin@example.com",
            role="admin",
            password_hash="e" * 64,
        )
        users_file = self.state_dir / "users.json"
        self.assertFalse(users_file.exists())

        with sqlite3.connect(str(users_db)) as conn:
            email = conn.execute("SELECT email FROM webui_users").fetchone()[0]
        self.assertEqual(email, "erin@example.com")


if __name__ == "__main__":
    unittest.main()
