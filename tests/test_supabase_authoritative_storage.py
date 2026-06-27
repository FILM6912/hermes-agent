"""Regression tests: Supabase/Postgres is authoritative over in-memory and JSON fallbacks."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _isolated_state(testcase: unittest.TestCase) -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix="supabase-auth-test-"))
    testcase.addCleanup(lambda: __import__("shutil").rmtree(state_dir, ignore_errors=True))
    db_path = state_dir / "webui.db"
    os.environ["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
    os.environ["HERMES_WEBUI_LOCAL_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["HERMES_WEBUI_SUPABASE_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["PG_HOST"] = "127.0.0.1"

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


class TestSupabaseAuthoritativeUsers(unittest.TestCase):
    def setUp(self) -> None:
        self.state_dir = _isolated_state(self)
        from app.storage.schema import init_storage

        init_storage()

    def test_users_reload_from_db_each_read_when_supabase_enabled(self):
        from app.domain.users import _load_store, invalidate_users_cache
        from app.storage.repositories.users import get_users_repository

        repo = get_users_repository()
        repo.create(
            {
                "email": "alive@example.com",
                "role": "user",
                "profile_name": "alive",
                "profile_names": ["alive"],
                "password_hash": "a" * 64,
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        invalidate_users_cache()
        self.assertIn("alive@example.com", _load_store()["users"])

        repo.delete("alive@example.com")
        invalidate_users_cache()
        self.assertNotIn("alive@example.com", _load_store()["users"])

    def test_users_do_not_reimport_json_after_db_cleared(self):
        from app.domain.users import _load_store, invalidate_users_cache
        from app.storage.repositories.legacy_import import mark_legacy_import_done
        from app.storage.repositories.users import get_users_repository

        users_json = self.state_dir / "users.json"
        users_json.write_text(
            json.dumps(
                {
                    "version": 1,
                    "users": {
                        "ghost@example.com": {
                            "email": "ghost@example.com",
                            "role": "user",
                            "profile_name": "ghost",
                            "profile_names": ["ghost"],
                            "password_hash": "g" * 64,
                        }
                    },
                    "profile_bindings": {},
                }
            ),
            encoding="utf-8",
        )

        repo = get_users_repository()
        repo.create(
            {
                "email": "real@example.com",
                "role": "user",
                "profile_name": "real",
                "profile_names": ["real"],
                "password_hash": "r" * 64,
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        mark_legacy_import_done("webui_users")
        repo.delete("real@example.com")

        invalidate_users_cache()
        store = _load_store()
        self.assertNotIn("ghost@example.com", store["users"])
        self.assertNotIn("real@example.com", store["users"])

    def test_departments_do_not_reimport_json_after_db_cleared(self):
        from app.domain.departments import list_departments
        from app.storage.repositories.departments import get_departments_repository
        from app.storage.repositories.legacy_import import mark_legacy_import_done

        dept_json = self.state_dir / "departments.json"
        dept_json.write_text(
            json.dumps(
                {
                    "version": 1,
                    "departments": {
                        "ghost": {"label": "Ghost Dept", "description": None},
                    },
                }
            ),
            encoding="utf-8",
        )

        repo = get_departments_repository()
        repo.create({"id": "live", "label": "Live"})
        mark_legacy_import_done("webui_departments")
        repo.delete("live")

        ids = {row["id"] for row in list_departments()}
        self.assertNotIn("ghost", ids)
        self.assertNotIn("live", ids)


class TestUsersCacheBypassWithMockedSupabase(unittest.TestCase):
    def test_second_load_hits_repository_when_supabase_flag_set(self):
        from app.domain import users as users_domain

        calls = {"count": 0}

        def fake_load_store():
            calls["count"] += 1
            email = "first@example.com" if calls["count"] == 1 else "second@example.com"
            return {
                "version": 1,
                "updated_at": 1.0,
                "users": {
                    email: {
                        "email": email,
                        "role": "user",
                        "profile_name": email.split("@")[0],
                        "profile_names": [email.split("@")[0]],
                    }
                },
                "profile_bindings": {},
            }

        class FakeRepo:
            def maybe_migrate_legacy(self, **kwargs):
                return False

            def load_store(self):
                return fake_load_store()

        users_domain.invalidate_users_cache()
        with patch.object(users_domain, "_use_supabase_store", return_value=True):
            with patch(
                "app.storage.repositories.users.get_users_repository",
                return_value=FakeRepo(),
            ):
                first = users_domain._load_store()
                second = users_domain._load_store()

        self.assertIn("first@example.com", first["users"])
        self.assertIn("second@example.com", second["users"])
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
