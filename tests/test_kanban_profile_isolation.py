"""Kanban API must read/write the active WebUI profile's kanban root.

hermes_cli.kanban_db resolves its umbrella root from HERMES_KANBAN_HOME (or
falls back to get_default_hermes_root()). Without per-request pinning, every
tab would share the process-default ~/.hermes/kanban.db regardless of the
hermes_profile cookie.
"""
import os
import pathlib
import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

WEBUI_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(WEBUI_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBUI_ROOT))


class _EnvTrackingKanban:
    """Minimal fake that records HERMES_KANBAN_HOME on each connect()."""

    DEFAULT_BOARD = "default"

    def __init__(self):
        self.connect_calls = []

    def _normalize_board_slug(self, raw):
        return str(raw or "").strip().lower() or None

    def board_exists(self, slug):
        return True

    def init_db(self, board=None):
        return None

    def connect(self, board=None):
        self.connect_calls.append(os.environ.get("HERMES_KANBAN_HOME"))
        return mock.MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda *a: None,
            execute=mock.MagicMock(
                return_value=mock.MagicMock(fetchone=lambda: {"latest": 0}, fetchall=list)
            ),
        )

    def list_tasks(self, conn, **kwargs):
        return []

    def list_boards(self, include_archived=False):
        return [{"slug": "default", "name": "Default"}]

    def get_current_board(self):
        return "default"

    def clear_current_board(self):
        return None

    def known_assignees(self, conn):
        return []


def _load_bridge(monkeypatch, fake_kanban):
    fake_hermes_cli = types.ModuleType("hermes_cli")
    fake_hermes_cli.kanban_db = fake_kanban
    monkeypatch.setitem(sys.modules, "hermes_cli", fake_hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", fake_kanban)
    import importlib
    import app.domain.kanban_bridge as bridge

    return importlib.reload(bridge)


def test_handle_kanban_get_pins_active_profile_kanban_home(tmp_path, monkeypatch):
    default_home = tmp_path / "default_home"
    usera_home = default_home / "profiles" / "usera"
    userb_home = default_home / "profiles" / "userb"
    usera_home.mkdir(parents=True)
    userb_home.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(default_home))
    from app.domain import profiles as p

    monkeypatch.setattr(p, "_DEFAULT_HERMES_HOME", default_home)

    fake = _EnvTrackingKanban()
    bridge = _load_bridge(monkeypatch, fake)

    handler = mock.MagicMock()
    handler.headers = {}

    with mock.patch.object(bridge, "j", return_value=True):
        p.set_request_profile("usera")
        try:
            bridge.handle_kanban_get(handler, SimpleNamespace(path="/api/kanban/board", query=""))
        finally:
            p.clear_request_profile()

    assert fake.connect_calls[-1] == str(usera_home)

    fake.connect_calls.clear()
    with mock.patch.object(bridge, "j", return_value=True):
        p.set_request_profile("userb")
        try:
            bridge.handle_kanban_get(handler, SimpleNamespace(path="/api/kanban/stats", query=""))
        finally:
            p.clear_request_profile()

    assert fake.connect_calls[-1] == str(userb_home)


def test_kanban_config_payload_uses_webui_get_config(tmp_path, monkeypatch):
    default_home = tmp_path / "default_home"
    profile_home = default_home / "profiles" / "usera"
    profile_home.mkdir(parents=True)
    (profile_home / "config.yaml").write_text(
        "dashboard:\n  kanban:\n    default_tenant: profile-a\n    lane_by_profile: false\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(default_home))
    monkeypatch.delenv("HERMES_CONFIG_PATH", raising=False)
    from app.domain import profiles as p

    monkeypatch.setattr(p, "_DEFAULT_HERMES_HOME", default_home)

    fake = _EnvTrackingKanban()
    bridge = _load_bridge(monkeypatch, fake)

    import app.domain.config as config_mod

    config_mod.reload_config()

    p.set_request_profile("usera")
    try:
        with p.profile_request_context():
            payload = bridge._config_payload()
    finally:
        p.clear_request_profile()

    assert payload["default_tenant"] == "profile-a"
    assert payload["lane_by_profile"] is False
