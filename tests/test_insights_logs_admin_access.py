"""Insights and Logs honor ``insights:read`` / ``logs:read`` in multi-user mode."""

from __future__ import annotations

import importlib
import json
import pathlib
import time

import pytest
from starlette.testclient import TestClient

from app.domain.auth import COOKIE_NAME, _hash_password, create_session
from app.domain.users import create_user, invalidate_users_cache
from app.main import create_app

PANELS_JS = (pathlib.Path(__file__).parent.parent / "static-legacy" / "panels.js").read_text(
    encoding="utf-8"
)
INDEX_HTML = (pathlib.Path(__file__).parent.parent / "static-legacy" / "index.html").read_text(
    encoding="utf-8"
)


@pytest.fixture
def insights_logs_env(tmp_path, monkeypatch):
    state = tmp_path / "webui"
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir(parents=True)
    session_dir = state / "sessions"
    session_dir.mkdir(parents=True)
    roles_path = state / "roles.json"
    (hermes_home / "profiles" / "alice").mkdir(parents=True)
    (hermes_home / "profiles" / "bob").mkdir(parents=True)
    (hermes_home / "logs").mkdir(parents=True)
    (hermes_home / "profiles" / "alice" / "logs").mkdir(parents=True)
    (hermes_home / "profiles" / "bob" / "logs").mkdir(parents=True)

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "legacy-secret")
    monkeypatch.setattr("app.domain.roles.ROLES_FILE", roles_path)
    monkeypatch.setattr("app.domain.roles._use_supabase_store", lambda: False)

    import app.domain.config as config
    import app.domain.auth as auth
    import app.domain.users as users
    import app.domain.profiles as profiles
    import app.domain.routes as routes
    import app.domain.roles as roles

    importlib.reload(config)
    auth = importlib.reload(auth)
    users = importlib.reload(users)
    profiles = importlib.reload(profiles)
    roles = importlib.reload(roles)

    config.SESSION_DIR = session_dir
    config.SESSION_INDEX_FILE = session_dir / "_index.json"
    monkeypatch.setattr(routes, "SESSION_DIR", session_dir)

    auth._sessions.clear()
    profiles._DEFAULT_HERMES_HOME = hermes_home
    profiles._active_profile = "default"
    profiles._profiles_list_cache = None
    profiles._invalidate_root_profile_cache()
    profiles.get_hermes_home_for_profile = lambda name: (
        hermes_home
        if name in (None, "", "default")
        else hermes_home / "profiles" / name
    )

    roles.invalidate_roles_cache()
    roles.ensure_default_roles()

    now = time.time()
    index = [
        {
            "session_id": "alice-sess",
            "profile": "alice",
            "updated_at": now,
            "created_at": now,
            "message_count": 3,
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.01,
            "model": "m1",
        },
        {
            "session_id": "bob-sess",
            "profile": "bob",
            "updated_at": now,
            "created_at": now,
            "message_count": 9,
            "input_tokens": 900,
            "output_tokens": 90,
            "estimated_cost": 0.09,
            "model": "m2",
        },
    ]
    (session_dir / "_index.json").write_text(json.dumps(index), encoding="utf-8")
    (hermes_home / "profiles" / "alice" / "logs" / "agent.log").write_text(
        "alice-log-marker\n",
        encoding="utf-8",
    )
    (hermes_home / "profiles" / "bob" / "logs" / "agent.log").write_text(
        "bob-log-marker\n",
        encoding="utf-8",
    )

    invalidate_users_cache()
    create_user("admin", role="admin", password_hash=_hash_password("admin-pass"))
    create_user(
        "alice",
        role="user",
        profile_name="alice",
        password_hash=_hash_password("alice-pass"),
    )
    create_user(
        "bob",
        role="user",
        profile_name="bob",
        password_hash=_hash_password("bob-pass"),
    )

    yield {
        "auth": auth,
        "hermes_home": hermes_home,
        "session_dir": session_dir,
        "roles": roles,
    }

    invalidate_users_cache()
    auth._sessions.clear()


def _cookie(auth_mod, *, user_id: str, role: str) -> dict[str, str]:
    token = create_session(user_id=user_id, role=role)
    return {"Cookie": f"{COOKIE_NAME}={token}"}


@pytest.fixture
def client(insights_logs_env):
    return TestClient(create_app())


def test_regular_user_insights_forbidden(client, insights_logs_env):
    response = client.get(
        "/api/v1/insights?days=30",
        headers=_cookie(insights_logs_env["auth"], user_id="alice", role="user"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: insights:read"


def test_regular_user_logs_forbidden(client, insights_logs_env):
    response = client.get(
        "/api/v1/logs?file=agent&tail=200",
        headers=_cookie(insights_logs_env["auth"], user_id="alice", role="user"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: logs:read"


def test_user_with_logs_read_can_view_own_logs(client, insights_logs_env):
    insights_logs_env["roles"].update_role("user", permissions={"logs:read": True})
    response = client.get(
        "/api/v1/logs?file=agent&tail=200&profile=alice",
        headers=_cookie(insights_logs_env["auth"], user_id="alice", role="user"),
    )
    assert response.status_code == 200
    payload = response.json()
    joined = "\n".join(payload.get("lines") or [])
    assert "alice-log-marker" in joined


def test_user_with_logs_read_still_forbidden_on_insights(client, insights_logs_env):
    insights_logs_env["roles"].update_role("user", permissions={"logs:read": True})
    response = client.get(
        "/api/v1/insights?days=30",
        headers=_cookie(insights_logs_env["auth"], user_id="alice", role="user"),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: insights:read"


def test_user_with_insights_read_can_view_insights(client, insights_logs_env):
    insights_logs_env["roles"].update_role("user", permissions={"insights:read": True})
    response = client.get(
        "/api/v1/insights?days=30&profile=alice",
        headers=_cookie(insights_logs_env["auth"], user_id="alice", role="user"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_sessions"] == 1
    assert payload.get("profile") == "alice"


def test_admin_insights_combined_all_profiles(client, insights_logs_env):
    response = client.get(
        "/api/v1/insights?days=30",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_sessions"] == 2
    assert payload["total_messages"] == 12
    assert payload.get("profile") is None


def test_builtin_admin_accesses_insights_logs_without_explicit_flags(client, insights_logs_env):
    """Built-in admin role keeps Insights/Logs even when those flags are revoked."""
    insights_logs_env["roles"].update_role(
        "admin",
        permissions={"insights:read": False, "logs:read": False, "users:manage": False, "roles:manage": False},
    )
    insights = client.get(
        "/api/v1/insights?days=30",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    logs = client.get(
        "/api/v1/logs?file=agent&tail=200",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    assert insights.status_code == 200
    assert logs.status_code == 200
    insights_logs_env["roles"].update_role("admin", permissions={"*": True})


def test_admin_insights_filtered_by_username(client, insights_logs_env):
    response = client.get(
        "/api/v1/insights?days=30&username=alice",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_sessions"] == 1
    assert payload["total_messages"] == 3
    assert payload.get("profile") == "alice"


def test_admin_insights_filtered_by_profile(client, insights_logs_env):
    response = client.get(
        "/api/v1/insights?days=30&profile=bob",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_sessions"] == 1
    assert payload["total_messages"] == 9
    assert payload.get("profile") == "bob"


def test_ui_hides_insights_logs_for_non_admin_multi_user():
    assert "_canAccessInsightsLogs" in PANELS_JS
    assert "_applyInsightsLogsPanelRestrictions" in PANELS_JS
    assert "insightsLogsScope" in INDEX_HTML
    assert "insights_logs_scope_all" in PANELS_JS


def test_admin_logs_filtered_by_profile(client, insights_logs_env):
    response = client.get(
        "/api/v1/logs?file=agent&tail=200&profile=alice",
        headers=_cookie(insights_logs_env["auth"], user_id="admin", role="admin"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("profile") == "alice"
    joined = "\n".join(payload.get("lines") or [])
    assert "alice-log-marker" in joined
    assert "bob-log-marker" not in joined
