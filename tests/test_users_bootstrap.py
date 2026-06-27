"""Tests for multi-user first-run admin bootstrap and promotion."""

from __future__ import annotations

import hashlib
import json

import pytest

from app.domain.users import UserError


@pytest.fixture(autouse=True)
def _fast_password_hash(monkeypatch):
    """PBKDF2-600k is too slow for unit tests; pin a deterministic fast hash."""

    def _fast(pw: str, *, salt: bytes | None = None) -> str:
        return hashlib.sha256(pw.encode()).hexdigest()

    monkeypatch.setattr("app.domain.auth._hash_password", _fast)
    monkeypatch.setattr("app.domain.users._hash_password", _fast)


@pytest.fixture
def isolated_users_state(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    state.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    import app.domain.config as cfg
    import app.domain.users as users_mod

    cfg.STATE_DIR = state
    cfg.SESSION_DIR = state / "sessions"
    users_mod.STATE_DIR = state
    users_mod.USERS_FILE = state / "users.json"
    users_mod.invalidate_users_cache()
    yield state
    users_mod.invalidate_users_cache()
    if users_mod.USERS_FILE.exists():
        users_mod.USERS_FILE.unlink()


def test_bootstrap_creates_admin_from_env(isolated_users_state, monkeypatch):
    import app.domain.users as users_mod

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_USER", "filmadmin")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_PASSWORD", "s3cret-bootstrap")

    result = users_mod.bootstrap_default_admin()
    assert result is not None
    assert result["username"] == "filmadmin"
    assert result["role"] == "admin"

    store = json.loads(users_mod.USERS_FILE.read_text(encoding="utf-8"))
    assert "filmadmin" in store["users"]
    assert store["users"]["filmadmin"]["password_hash"] != "s3cret-bootstrap"


def test_bootstrap_skips_when_users_json_exists(isolated_users_state, monkeypatch):
    """Restart must not recreate or overwrite users from env."""
    import app.domain.users as users_mod

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_USER", "firstadmin")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_PASSWORD", "first-pass")

    first = users_mod.bootstrap_default_admin()
    assert first is not None
    assert first["username"] == "firstadmin"

    monkeypatch.setenv("HERMES_WEBUI_ADMIN_USER", "env-overwrite")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_PASSWORD", "env-overwrite-pass")

    assert users_mod.bootstrap_default_admin() is None

    store = json.loads(users_mod.USERS_FILE.read_text(encoding="utf-8"))
    assert "firstadmin" in store["users"]
    assert "env-overwrite" not in store["users"]


def test_bootstrap_skips_without_multi_user_flag(isolated_users_state, monkeypatch):
    import app.domain.users as users_mod

    monkeypatch.delenv("HERMES_WEBUI_MULTI_USER", raising=False)
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_PASSWORD", "ignored")

    assert users_mod.bootstrap_default_admin() is None
    assert not users_mod.USERS_FILE.exists()


def test_bootstrap_skips_when_password_unset(isolated_users_state, monkeypatch, capsys):
    import app.domain.users as users_mod

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.delenv("HERMES_WEBUI_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_PASSWORD", raising=False)

    assert users_mod.bootstrap_default_admin() is None
    assert not users_mod.USERS_FILE.exists()

    captured = capsys.readouterr()
    assert "HERMES_WEBUI_ADMIN_PASSWORD" in captured.out or "HERMES_WEBUI_PASSWORD" in captured.out
    assert "s3cret" not in captured.out


def test_bootstrap_never_logs_password(isolated_users_state, monkeypatch, capsys):
    import app.domain.users as users_mod

    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ADMIN_PASSWORD", "do-not-log-me")

    users_mod.bootstrap_default_admin()
    captured = capsys.readouterr()
    assert "do-not-log-me" not in captured.out
    assert "do-not-log-me" not in captured.err


def test_promote_requires_current_password_when_auth_enabled(
    isolated_users_state, monkeypatch
):
    import app.domain.config as cfg
    import app.domain.users as users_mod

    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-pass")
    cfg.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    from app.domain.auth import _hash_password, _invalidate_password_hash_cache

    cfg.SETTINGS_FILE.write_text(
        json.dumps({"password_hash": _hash_password("legacy-pass")}),
        encoding="utf-8",
    )
    _invalidate_password_hash_cache()

    bad = users_mod.promote_install_to_multi_user(
        admin_username="admin",
        admin_password="new-admin-pass",
        current_password="wrong",
    )
    assert bad["status"] == "error"

    ok = users_mod.promote_install_to_multi_user(
        admin_username="admin",
        admin_password="new-admin-pass",
        current_password="legacy-pass",
    )
    assert ok["status"] == "created"
    assert users_mod.USERS_FILE.exists()


def test_user_role_requires_unique_profile(isolated_users_state):
    import app.domain.users as users_mod

    users_mod.create_user(
        "alice",
        role="user",
        profile_name="work",
        password="pw-alice",
    )
    with pytest.raises(UserError, match="already assigned"):
        users_mod.create_user(
            "bob",
            role="user",
            profile_name="work",
            password="pw-bob",
        )
