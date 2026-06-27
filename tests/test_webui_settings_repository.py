"""Tests for normalized webui_settings storage repository."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _use_isolated_storage(testcase: unittest.TestCase) -> Path:
    state_dir = Path(tempfile.mkdtemp(prefix="webui-settings-repo-test-"))
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
    from app.domain import config as domain_cfg

    domain_cfg.STATE_DIR = state_dir
    domain_cfg.SETTINGS_FILE = state_dir / "settings.json"
    conn_mod.reset_shared_connection()
    cfg_mod.clear_database_url_cache()
    settings_repo_mod.reset_settings_repository()
    testcase.addCleanup(conn_mod.reset_shared_connection)
    testcase.addCleanup(cfg_mod.clear_database_url_cache)
    testcase.addCleanup(settings_repo_mod.reset_settings_repository)
    return state_dir


class TestWebuiSettingsRepository(unittest.TestCase):
    def setUp(self) -> None:
        _use_isolated_storage(self)
        from app.storage.schema import init_storage

        init_storage()

    def test_config_load_save_roundtrip(self):
        from app.domain import config as cfg_mod
        from app.storage.repositories.settings import get_settings_repository

        saved = cfg_mod.save_settings({"theme": "light", "bot_name": "Hermes"})
        self.assertEqual(saved["theme"], "light")

        reloaded = cfg_mod.load_settings()
        self.assertEqual(reloaded["theme"], "light")
        self.assertEqual(reloaded["bot_name"], "Hermes")

        doc = get_settings_repository().load_document()
        assert doc is not None
        self.assertEqual(doc.get("theme"), "light")
        self.assertTrue(cfg_mod.SETTINGS_FILE.exists())
