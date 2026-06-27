"""Tests for WebUI user account storage."""

from __future__ import annotations

import json

import pytest

import app.domain.users as users_domain
from app.repositories.users import UsersRepository


@pytest.fixture
def users_repo(tmp_path, monkeypatch):
    """Isolated users storage under a temporary state directory."""
    import os

    state_dir = tmp_path / "webui"
    state_dir.mkdir()
    db_path = state_dir / "webui.db"
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HERMES_HOME", str(state_dir))
    monkeypatch.setenv("HERMES_WEBUI_LOCAL_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.delenv("HERMES_WEBUI_DATABASE_URL", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_SUPABASE_DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_HOST", raising=False)

    from app.storage import connection as conn_mod
    from app.storage import config as cfg_mod
    from app.storage.repositories import users as users_repo_mod
    from app.storage.schema import init_storage

    monkeypatch.setattr("app.domain.config.STATE_DIR", state_dir)
    monkeypatch.setattr(users_domain, "STATE_DIR", state_dir)
    monkeypatch.setattr(users_domain, "USERS_FILE", state_dir / "users.json")
    monkeypatch.setattr(
        users_domain,
        "_SESSION_USERS_FILE",
        state_dir / ".session_users.json",
    )
    conn_mod.reset_shared_connection()
    cfg_mod.clear_database_url_cache()
    users_repo_mod.reset_users_repository()
    init_storage()
    users_domain.invalidate_users_cache()
    yield UsersRepository()
    users_domain.invalidate_users_cache()
    users_repo_mod.reset_users_repository()
    conn_mod.reset_shared_connection()
    cfg_mod.clear_database_url_cache()
    users_file = state_dir / "users.json"
    if users_file.exists():
        users_file.unlink()


def test_create_admin_and_user(users_repo):
    admin = users_repo.create_user(
        email="admin1@example.com",
        role="admin",
        password_hash="a" * 64,
    )
    assert admin["email"] == "admin1@example.com"
    assert admin["role"] == "admin"
    assert admin["profile_name"] is None
    assert admin["created_at"] is not None

    user = users_repo.create_user(
        email="alice@example.com",
        role="user",
        profile_name="alice",
        password_hash="b" * 64,
    )
    assert user["email"] == "alice@example.com"
    assert user["role"] == "user"
    assert user["profile_name"] == "alice"


def test_get_list_update_delete(users_repo):
    users_repo.create_user(
        email="bob@example.com",
        role="user",
        profile_name="bob",
        password_hash="c" * 64,
    )

    loaded = users_repo.get_user("bob@example.com")
    assert loaded is not None
    assert loaded["profile_name"] == "bob"

    users = users_repo.list_users()
    assert [item["email"] for item in users] == ["bob@example.com"]

    updated = users_repo.update_user(
        "bob@example.com",
        password_hash="d" * 64,
    )
    assert updated["email"] == "bob@example.com"

    users_repo.delete_user("bob@example.com")
    assert users_repo.get_user("bob@example.com") is None


def test_duplicate_email_rejected(users_repo):
    users_repo.create_user(
        email="carol@example.com",
        role="user",
        profile_name="carol",
        password_hash="e" * 64,
    )
    with pytest.raises(users_domain.UserError, match="already exists"):
        users_repo.create_user(
            email="carol@example.com",
            role="user",
            profile_name="carol2",
            password_hash="f" * 64,
        )


def test_profile_name_unique_for_user_role(users_repo):
    users_repo.create_user(
        email="dana@example.com",
        role="user",
        profile_name="shared",
        password_hash="g" * 64,
    )
    with pytest.raises(users_domain.UserError, match="already assigned"):
        users_repo.create_user(
            email="erin@example.com",
            role="user",
            profile_name="shared",
            password_hash="h" * 64,
        )


def test_user_role_defaults_profile_from_email(users_repo):
    user = users_repo.create_user(
        email="frank@example.com",
        role="user",
        password_hash="i" * 64,
    )
    assert user["profile_name"] == "frank"


def test_admin_cannot_have_profile_name(users_repo):
    with pytest.raises(users_domain.UserError, match="must not have a profile_name|role=admin"):
        users_repo.create_user(
            email="gina@example.com",
            role="admin",
            profile_name="gina",
            password_hash="j" * 64,
        )


def test_update_profile_enforces_one_to_one(users_repo):
    users_repo.create_user(
        email="heidi@example.com",
        role="user",
        profile_name="heidi",
        password_hash="k" * 64,
    )
    users_repo.create_user(
        email="ivan@example.com",
        role="user",
        profile_name="ivan",
        password_hash="l" * 64,
    )

    with pytest.raises(users_domain.UserError, match="already assigned"):
        users_repo.update_user("ivan@example.com", profile_name="heidi")


def test_missing_user_errors(users_repo):
    with pytest.raises(users_domain.UserNotFoundError):
        users_repo.update_user("missing@example.com", password_hash="m" * 64)
    with pytest.raises(users_domain.UserNotFoundError):
        users_repo.delete_user("missing@example.com")


def test_users_file_persisted_under_state_dir(users_repo, tmp_path):
    users_repo.create_user(
        email="jane@example.com",
        role="user",
        profile_name="jane",
        password_hash="n" * 64,
    )

    users_file = tmp_path / "webui" / "users.json"
    assert users_file.exists()
    assert users_repo.get_user("jane@example.com")["profile_name"] == "jane"


def test_load_prunes_empty_email_user_keys(users_repo, tmp_path):
    """Corrupt rows keyed by '' (lost email bug) are removed on load; valid rows are repaired."""
    email = "keeper@example.com"
    users_file = tmp_path / "webui" / "users.json"
    users_file.write_text(
        json.dumps(
            {
                "version": 1,
                "users": {
                    "": {
                        "role": "admin",
                        "password_hash": "deadbeef",
                        "created_at": 1.0,
                        "updated_at": 1.0,
                    },
                    email: {
                        "username": email,
                        "role": "admin",
                        "password_hash": "cafebabe",
                        "created_at": 2.0,
                        "updated_at": 2.0,
                    },
                },
                "profile_bindings": {"orphan": ""},
            }
        ),
        encoding="utf-8",
    )
    users_domain.invalidate_users_cache()

    users = users_repo.list_users()
    assert [u["email"] for u in users] == [email]

    on_disk = json.loads(users_file.read_text(encoding="utf-8"))
    assert "" not in on_disk["users"]
    assert email in on_disk["users"]
    assert on_disk["users"][email].get("email") == email
    assert "orphan" not in on_disk.get("profile_bindings", {})
