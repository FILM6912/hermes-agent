"""Smoke tests for the FastAPI application entrypoint (app.main:app)."""

import json
import pathlib
import urllib.error
import urllib.request

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
APP_MAIN = REPO_ROOT / "app" / "main.py"

pytestmark = pytest.mark.skipif(
    not APP_MAIN.exists(),
    reason="app/main.py not present yet (FastAPI migration in progress)",
)


def _get_json(path: str, *, base_url: str, method: str = "GET", body: dict | None = None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read()), exc.code, dict(exc.headers)


def test_app_imports():
    from app.main import app

    assert app is not None


def _route_paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _clear_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()


def test_create_app_registers_legacy_api_catchalls_when_legacy_api_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_LEGACY_API", "1")
    _clear_settings_cache()
    from app.main import create_app

    app = create_app()
    paths = _route_paths(app)
    assert "/api/v1/{path:path}" in paths
    assert "/api/{path:path}" in paths
    _clear_settings_cache()


def test_create_app_omits_legacy_api_catchalls_when_legacy_api_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_LEGACY_API", "0")
    _clear_settings_cache()
    from app.main import create_app

    app = create_app()
    paths = _route_paths(app)
    assert "/api/v1/{path:path}" not in paths
    assert "/api/{path:path}" not in paths
    _clear_settings_cache()


def test_unmatched_v1_api_returns_404_when_legacy_api_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_LEGACY_API", "0")
    _clear_settings_cache()
    from app.main import create_app
    from starlette.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/no-such-native-route-xyz")
    assert response.status_code == 404
    _clear_settings_cache()


def test_health_endpoint(base_url):
    with urllib.request.urlopen(base_url + "/health", timeout=10) as resp:
        payload = json.loads(resp.read())
    assert payload.get("status") == "ok"


def test_v1_auth_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/auth/status", base_url=base_url)
    assert status == 200
    assert payload["auth_enabled"] is False
    assert payload["logged_in"] is False
    assert "password_auth_enabled" in payload
    assert "passkeys_count" in payload


def test_v1_auth_login_when_auth_disabled(base_url):
    payload, status, _ = _get_json(
        "/api/v1/auth/login",
        base_url=base_url,
        method="POST",
        body={"password": "anything"},
    )
    assert status == 200
    assert payload.get("ok") is True


def test_v1_auth_logout(base_url):
    payload, status, _ = _get_json(
        "/api/v1/auth/logout",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 200
    assert payload.get("ok") is True


def test_v1_auth_passkeys_when_feature_disabled(base_url):
    payload, status, _ = _get_json(
        "/api/v1/auth/passkeys",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 200
    assert payload.get("credentials") == []
    assert payload.get("disabled") is True


def test_v1_auth_passkey_options_when_feature_disabled(base_url):
    payload, status, _ = _get_json(
        "/api/v1/auth/passkey/options",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 404
    assert "disabled" in payload.get("error", "").lower()


def test_v1_models_endpoint(base_url):
    with urllib.request.urlopen(base_url + "/api/v1/models", timeout=10) as resp:
        payload = json.loads(resp.read())
    assert resp.status == 200
    assert "groups" in payload
    assert "default_model" in payload
    assert "active_provider" in payload
    assert isinstance(payload["groups"], list)
    assert len(payload["groups"]) >= 1


def test_v1_models_live_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/models/live", base_url=base_url)
    assert status == 200
    assert "models" in payload
    assert isinstance(payload["models"], list)


def test_v1_providers_endpoint(base_url):
    with urllib.request.urlopen(base_url + "/api/v1/providers", timeout=10) as resp:
        payload = json.loads(resp.read())
    assert resp.status == 200
    assert "providers" in payload
    assert isinstance(payload["providers"], list)
    assert len(payload["providers"]) >= 1


def test_v1_providers_set_key_missing_provider(base_url):
    payload, status, _ = _get_json(
        "/api/v1/providers",
        base_url=base_url,
        method="POST",
        body={"api_key": "sk-test"},
    )
    assert status == 400
    assert "required" in payload.get("error", "").lower()


def test_v1_providers_delete_missing_provider(base_url):
    payload, status, _ = _get_json(
        "/api/v1/providers/delete",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "required" in payload.get("error", "").lower()


def test_v1_model_set_unknown_scope(base_url):
    payload, status, _ = _get_json(
        "/api/v1/model/set",
        base_url=base_url,
        method="POST",
        body={"scope": "unknown", "task": "compression"},
    )
    assert status == 400
    assert "unknown scope" in payload.get("error", "").lower()


def test_v1_core_endpoints_avoid_legacy_dispatch():
    """Phase 3 core modules must call services, not dispatch_legacy_route."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    for name in ("profiles.py", "sessions.py", "workspace.py", "settings.py"):
        source = (endpoints / name).read_text(encoding="utf-8")
        assert "dispatch_legacy_route" not in source, name


def test_v1_sessions_misc_avoid_legacy_dispatch():
    """Phase 4 sessions_misc must call SessionService directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    source = (endpoints / "sessions_misc.py").read_text(encoding="utf-8")
    assert "dispatch_legacy_route" not in source
    assert "_session_service.truncate_session(" in source
    assert "_session_service.duplicate_session(" in source
    assert "_session_service.clear_session(" in source
    assert "_session_service.conversation_rounds(" in source
    assert "_session_service.handoff_summary(" in source
    assert "_session_service.set_toolsets(" in source
    assert "_session_service.retry_last_turn(" in source
    assert "_session_service.undo_last_turn(" in source
    assert "_session_service.lineage_report(" in source


def test_v1_system_updates_avoid_legacy_dispatch():
    """Phase 4 system/updates must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    system = (endpoints / "system.py").read_text(encoding="utf-8")
    updates = (endpoints / "updates.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in system, "system.py"
    assert "dispatch_legacy_route" not in updates, "updates.py"
    assert "_service.get_system_health()" in system
    assert "_service.get_agent_health()" in system
    assert "_service.get_plugins()" in system
    assert "_service.get_gateway_status()" in system
    assert "_service.get_wiki_status()" in system
    assert "_service.get_insights(" in system
    assert "_service.get_logs(" in system
    assert "_service.shutdown()" in system
    assert "_service.admin_reload()" in system
    assert "_service.check_for_updates(" in updates
    assert "_service.summarize_updates(" in updates
    assert "_service.apply_update(" in updates
    assert "_service.apply_force_update(" in updates
    assert '"/api/system/health"' not in system
    assert '"/api/updates/check"' not in updates


def test_v1_dashboard_approval_terminal_avoid_legacy_dispatch():
    """Phase 4 dashboard/approval/terminal control routes must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    dashboard = (endpoints / "dashboard.py").read_text(encoding="utf-8")
    approval = (endpoints / "approval.py").read_text(encoding="utf-8")
    terminal = (endpoints / "terminal.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in dashboard, "dashboard.py"
    assert "dispatch_legacy_route" not in terminal, "terminal.py"
    assert "_service.get_status()" in dashboard
    assert "_service.get_config()" in dashboard
    assert "_service.save_config(" in dashboard
    assert "_service.get_pending(" in approval
    assert "_service.respond(" in approval
    assert "_service.inject_test(" in approval
    assert "_service.get_clarify_pending(" in approval
    assert "_service.clarify_respond(" in approval
    assert "_service.inject_clarify_test(" in approval
    assert "_service.start(" in terminal
    assert "_service.write_input(" in terminal
    assert "_service.resize(" in terminal
    assert "_service.close(" in terminal
    assert '"/api/dashboard/status"' not in dashboard
    assert '"/api/terminal/start"' not in terminal
    assert '"/api/approval/respond"' not in approval
    assert '"/api/clarify/pending"' not in approval
    assert '"/api/clarify/respond"' not in approval


def test_v1_sessions_compress_avoid_legacy_dispatch():
    """Session compress routes must call SessionService directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    sessions = (endpoints / "sessions.py").read_text(encoding="utf-8")
    assert "run_legacy_dispatch_sync" not in sessions, "sessions.py"
    assert "_service.compress_status(" in sessions
    assert "_service.compress_start(" in sessions
    assert "_service.compress(" in sessions
    assert '"/api/session/compress/status"' not in sessions


def test_v1_endpoints_legacy_dispatch_count_is_zero():
    """All v1 endpoint modules must avoid legacy bridge helpers."""
    endpoints_dir = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    legacy_hits: list[str] = []
    for path in sorted(endpoints_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for needle in ("dispatch_legacy_route", "run_legacy_dispatch_sync", "handle_legacy_sse"):
            if needle in source:
                legacy_hits.append(f"{path.name}:{needle}")
    assert legacy_hits == [], legacy_hits


def test_v1_models_providers_auth_avoid_legacy_dispatch():
    """Phase 3 models/providers/auth must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    models = (endpoints / "models.py").read_text(encoding="utf-8")
    providers = (endpoints / "providers.py").read_text(encoding="utf-8")
    auth = (endpoints / "auth.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in models, "models.py"
    assert "dispatch_legacy_route" not in providers, "providers.py"
    assert "dispatch_legacy_route" not in auth, "auth.py"
    assert "_service.get_available_models()" in models
    assert "_service.get_live_models(" in models
    assert "_service.get_auxiliary_models()" in models
    assert "_service.get_reasoning_status(" in models
    assert "_service.set_model(" in models
    assert "_service.set_default_model(" in models
    assert "_service.set_reasoning(" in models
    assert "_service.list_providers()" in providers
    assert "_service.get_provider_quota(" in providers
    assert "_service.get_cost_history(" in providers
    assert "_service.set_provider_key(" in providers
    assert "_service.remove_provider_key(" in providers
    assert "_service.get_status(" in auth
    assert "_service.login(" in auth
    assert "_service.logout(" in auth
    assert "_service.passkey_authentication_options(" in auth
    assert "_service.passkey_login(" in auth
    assert "_service.list_passkeys(" in auth
    assert '"/api/auth/status"' not in auth
    assert '"/api/auth/login"' not in auth
    assert '"/api/model/set"' not in models
    assert '"/api/providers"' not in providers
    assert '@router.get("/models")' in models
    assert '@router.get("/providers")' in providers
    assert "return _service.get_available_models()" in models
    assert "return _service.list_providers()" in providers


def test_v1_memory_upload_avoid_legacy_dispatch():
    """Phase 4 memory/upload must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    memory = (endpoints / "memory.py").read_text(encoding="utf-8")
    upload = (endpoints / "upload.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in memory, "memory.py"
    assert "dispatch_legacy_route" not in upload, "upload.py"
    assert "_service.read_memory()" in memory
    assert "_service.write_memory(" in memory
    assert "_service.upload_multipart(" in upload
    assert "_service.upload_extract_multipart(" in upload
    assert '"/api/memory"' not in memory
    assert '"/api/upload"' not in upload


def test_v1_mcp_skills_kanban_avoid_legacy_dispatch():
    """Phase 4 mcp/skills/kanban SSE must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    mcp = (endpoints / "mcp.py").read_text(encoding="utf-8")
    skills = (endpoints / "skills.py").read_text(encoding="utf-8")
    kanban = (endpoints / "kanban.py").read_text(encoding="utf-8")
    sse_streams = (REPO_ROOT / "app" / "services" / "sse_streams.py").read_text(
        encoding="utf-8"
    )

    assert "run_legacy_dispatch_sync" not in mcp, "mcp.py"
    assert "run_legacy_dispatch_sync" not in skills, "skills.py"
    assert "handle_legacy_sse" not in kanban, "kanban.py"
    assert "_service.list_servers(" in mcp
    assert "_service.list_tools(" in mcp
    assert "_service.save(" in skills
    assert "_service.delete(" in skills
    assert "_service.toggle(" in skills
    assert "build_kanban_stream_response(" in kanban
    assert "async def iter_kanban_sse_bytes(" in sse_streams
    assert "def build_kanban_stream_response(" in sse_streams


def test_v1_profiles_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/profiles", base_url=base_url)
    assert status == 200
    assert "profiles" in payload
    assert "active" in payload
    assert isinstance(payload["profiles"], list)


def test_v1_settings_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/settings", base_url=base_url)
    assert status == 200
    assert "bot_name" in payload or "auth_enabled" in payload


def test_v1_workspaces_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/workspaces", base_url=base_url)
    assert status == 200
    assert "workspaces" in payload
    assert "last" in payload
    assert isinstance(payload["workspaces"], list)


def test_v1_sessions_list_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/sessions", base_url=base_url)
    assert status == 200
    assert "sessions" in payload
    assert "active_profile" in payload
    assert isinstance(payload["sessions"], list)


def test_v1_profile_switch_endpoint(base_url):
    payload, status, headers = _get_json(
        "/api/v1/profile/switch",
        base_url=base_url,
        method="POST",
        body={"name": "default"},
    )
    assert status == 200
    assert payload["active"] == "default"
    set_cookie = headers.get("Set-Cookie") or headers.get("set-cookie")
    assert set_cookie is not None


def test_v1_kanban_boards_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/kanban/boards", base_url=base_url)
    if status == 503:
        assert "kanban unavailable" in payload.get("error", "")
        return
    assert status == 200
    assert "boards" in payload


def test_v1_session_compress_status_idle(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/compress/status?session_id=test_idle_sid",
        base_url=base_url,
    )
    assert status == 200
    assert payload.get("status") == "idle"
    assert payload.get("ok") is True


def test_v1_session_export_requires_session_id(base_url):
    payload, status, _ = _get_json("/api/v1/session/export", base_url=base_url)
    assert status == 400
    assert "session_id" in payload.get("detail", "")


def test_v1_session_export_unknown_session(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/export?session_id=nosuchsession",
        base_url=base_url,
    )
    assert status == 404


def test_v1_session_branch_unknown_session(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/branch",
        base_url=base_url,
        method="POST",
        body={"session_id": "nonexistent_branch_sid"},
    )
    assert status == 404


def test_v1_session_recovery_audit(base_url):
    payload, status, _ = _get_json("/api/v1/session/recovery/audit", base_url=base_url)
    assert status == 200
    assert "status" in payload


def test_v1_session_worktree_status_unknown_session(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/worktree/status?session_id=nosuchsession",
        base_url=base_url,
    )
    assert status == 404


def test_v1_onboarding_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/onboarding/status", base_url=base_url)
    assert status == 200
    assert "completed" in payload
    assert "settings" in payload
    assert "system" in payload


def test_v1_crons_list_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/crons", base_url=base_url)
    assert status == 200
    assert "jobs" in payload
    assert isinstance(payload["jobs"], list)


def test_v1_crons_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/crons/status", base_url=base_url)
    assert status == 200
    assert "running" in payload


def test_v1_crons_delivery_options_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/crons/delivery-options", base_url=base_url)
    assert status == 200
    assert "platforms" in payload
    assert isinstance(payload["platforms"], list)


def test_v1_crons_history_requires_job_id(base_url):
    payload, status, _ = _get_json("/api/v1/crons/history", base_url=base_url)
    assert status == 400
    assert "job_id" in payload.get("error", "")


def test_v1_crons_avoid_legacy_dispatch():
    """Phase 4 crons module must use CronsService, not dispatch_legacy_route."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    crons = (endpoints / "crons.py").read_text(encoding="utf-8")
    services = (REPO_ROOT / "app" / "services" / "crons.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in crons, "crons.py"
    assert "CronsService" in crons
    assert "_service.list_crons()" in crons
    assert "_service.cron_create(" in crons
    assert "class CronsService" in services
    assert "cron_profile_context" in services
    assert "dispatch_legacy_route" not in services, "crons service"


def test_v1_git_status_requires_session(base_url):
    payload, status, _ = _get_json("/api/v1/git/status", base_url=base_url)
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_file_read_requires_session(base_url):
    payload, status, _ = _get_json("/api/v1/file", base_url=base_url)
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_chat_start_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/chat/start",
        base_url=base_url,
        method="POST",
        body={"message": "hello"},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_chat_start_requires_message(base_url):
    session_payload, session_status, _ = _get_json(
        "/api/v1/session/new",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert session_status == 200
    session_id = session_payload["session"]["session_id"]

    payload, status, _ = _get_json(
        "/api/v1/chat/start",
        base_url=base_url,
        method="POST",
        body={"session_id": session_id, "message": ""},
    )
    assert status == 400
    assert "message" in payload.get("error", "")


def test_v1_chat_cancel_requires_stream_id(base_url):
    payload, status, _ = _get_json("/api/v1/chat/cancel", base_url=base_url)
    assert status == 400
    assert "stream_id" in payload.get("error", "")


def test_v1_chat_cancel_nonexistent_stream(base_url):
    payload, status, _ = _get_json(
        "/api/v1/chat/cancel?stream_id=nonexistent_fastapi_test",
        base_url=base_url,
    )
    assert status == 200
    assert payload.get("ok") is True
    assert payload.get("cancelled") is False
    assert payload.get("stream_id") == "nonexistent_fastapi_test"


def test_v1_chat_steer_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/chat/steer",
        base_url=base_url,
        method="POST",
        body={"text": "Use Python instead"},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_chat_steer_requires_text(base_url):
    payload, status, _ = _get_json(
        "/api/v1/chat/steer",
        base_url=base_url,
        method="POST",
        body={"session_id": "sid_fastapi_steer_test"},
    )
    assert status == 400
    assert "text" in payload.get("error", "")


def test_v1_chat_steer_no_cached_agent(base_url):
    payload, status, _ = _get_json(
        "/api/v1/chat/steer",
        base_url=base_url,
        method="POST",
        body={"session_id": "sid_fastapi_steer_test", "text": "Use Python instead"},
    )
    assert status == 200
    assert payload.get("accepted") is False
    assert payload.get("fallback") == "no_cached_agent"


def test_v1_skills_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/skills", base_url=base_url)
    assert status == 200
    assert "skills" in payload
    assert isinstance(payload["skills"], list)


def test_v1_skills_content_requires_name(base_url):
    payload, status, _ = _get_json("/api/v1/skills/content", base_url=base_url)
    assert status == 400
    assert payload.get("detail") == "name required"


def test_v1_mcp_servers_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/mcp/servers", base_url=base_url)
    assert status == 200
    assert "servers" in payload
    assert isinstance(payload["servers"], list)
    assert payload.get("toggle_supported") is True


def test_v1_mcp_tools_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/mcp/tools", base_url=base_url)
    assert status == 200
    assert "tools" in payload
    assert isinstance(payload["tools"], list)
    assert "total" in payload


def test_v1_dashboard_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/dashboard/status", base_url=base_url)
    assert status == 200
    assert "running" in payload


def test_v1_dashboard_config_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/dashboard/config", base_url=base_url)
    assert status == 200
    assert "enabled" in payload


def test_v1_approval_pending_endpoint(base_url):
    payload, status, _ = _get_json(
        "/api/v1/approval/pending?session_id=no_such_session",
        base_url=base_url,
    )
    assert status == 200
    assert payload.get("pending") is None
    assert payload.get("pending_count") == 0


def test_v1_clarify_pending_endpoint(base_url):
    payload, status, _ = _get_json(
        "/api/v1/clarify/pending?session_id=no_such_session",
        base_url=base_url,
    )
    assert status == 200
    assert payload.get("pending") is None


def test_v1_approval_respond_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/approval/respond",
        base_url=base_url,
        method="POST",
        body={"choice": "deny"},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_clarify_respond_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/clarify/respond",
        base_url=base_url,
        method="POST",
        body={"response": "yes"},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_terminal_start_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/terminal/start",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_v1_crons_create_requires_fields(base_url):
    payload, status, _ = _get_json(
        "/api/v1/crons/create",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "prompt" in payload.get("error", "") or "schedule" in payload.get("error", "")


def test_v1_onboarding_complete_endpoint(base_url):
    payload, status, _ = _get_json(
        "/api/v1/onboarding/complete",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 200
    assert "completed" in payload


def test_v1_onboarding_avoids_legacy_dispatch():
    """Phase 4 onboarding endpoints must call OnboardingService directly."""
    onboarding_ep = (
        REPO_ROOT / "app" / "api" / "v1" / "endpoints" / "onboarding.py"
    ).read_text(encoding="utf-8")
    assert "dispatch_legacy_route" not in onboarding_ep
    assert "OnboardingService" in onboarding_ep
    assert "_service.get_status()" in onboarding_ep
    assert "_service.complete()" in onboarding_ep
    assert "_service.apply_setup(" in onboarding_ep
    assert "_service.probe(" in onboarding_ep
    assert "_service.oauth_start(" in onboarding_ep
    assert "_service.oauth_poll(" in onboarding_ep
    assert "_service.oauth_cancel(" in onboarding_ep


def test_v1_onboarding_oauth_poll_requires_flow_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/onboarding/oauth/poll",
        base_url=base_url,
    )
    assert status == 400
    assert "flow_id" in payload.get("error", "")


def test_v1_onboarding_probe_invalid_url(base_url):
    payload, status, _ = _get_json(
        "/api/v1/onboarding/probe",
        base_url=base_url,
        method="POST",
        body={"provider": "ollama", "base_url": "ftp://bad"},
    )
    assert status == 200
    assert payload.get("ok") is False
    assert payload.get("error") == "invalid_url"


def test_v1_memory_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/memory", base_url=base_url)
    assert status == 200
    assert "memory" in payload
    assert "user" in payload
    assert "soul" in payload
    assert "memory_path" in payload
    assert "user_path" in payload
    assert "soul_path" in payload


def test_v1_memory_write_invalid_section(base_url):
    payload, status, _ = _get_json(
        "/api/v1/memory/write",
        base_url=base_url,
        method="POST",
        body={"section": "invalid", "content": "test"},
    )
    assert status == 400
    assert "error" in payload


def test_v1_projects_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/projects", base_url=base_url)
    assert status == 200
    assert "projects" in payload
    assert isinstance(payload["projects"], list)
    assert "active_profile" in payload


def test_v1_projects_delete_unknown(base_url):
    payload, status, _ = _get_json(
        "/api/v1/projects/delete",
        base_url=base_url,
        method="POST",
        body={"project_id": "nonexistent_fastapi_project"},
    )
    assert status == 404
    assert "error" in payload


def test_v1_projects_rollback_avoid_legacy_dispatch():
    """Phase 4 projects/rollback must call services directly."""
    endpoints = REPO_ROOT / "app" / "api" / "v1" / "endpoints"
    projects = (endpoints / "projects.py").read_text(encoding="utf-8")
    rollback = (endpoints / "rollback.py").read_text(encoding="utf-8")

    assert "dispatch_legacy_route" not in projects, "projects.py"
    assert "dispatch_legacy_route" not in rollback, "rollback.py"
    assert "_service.list_projects(" in projects
    assert "_service.create_project(" in projects
    assert "_service.rename_project(" in projects
    assert "_service.delete_project(" in projects
    assert "_service.list_checkpoints(" in rollback
    assert "_service.get_checkpoint_diff(" in rollback
    assert "_service.restore_checkpoint(" in rollback
    assert '"/api/projects"' not in projects
    assert '"/api/rollback/list"' not in rollback


def test_v1_rollback_list_requires_workspace(base_url):
    payload, status, _ = _get_json("/api/v1/rollback/list", base_url=base_url)
    assert status == 400
    assert "workspace" in payload.get("error", "")


def test_v1_rollback_diff_requires_params(base_url):
    payload, status, _ = _get_json("/api/v1/rollback/diff", base_url=base_url)
    assert status == 400
    assert "workspace" in payload.get("error", "")


def test_v1_rollback_restore_requires_body(base_url):
    payload, status, _ = _get_json(
        "/api/v1/rollback/restore",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "error" in payload


def test_v1_upload_requires_multipart(base_url):
    payload, status, _ = _get_json(
        "/api/v1/upload",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "error" in payload


def test_v1_provider_quota_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/provider/quota", base_url=base_url)
    assert status == 200
    assert "providers" in payload or "error" in payload or "quota" in payload


def test_v1_plugins_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/plugins", base_url=base_url)
    assert status == 200
    assert "plugins" in payload or "hooks" in payload


def test_v1_gateway_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/gateway/status", base_url=base_url)
    assert status == 200


def test_v1_wiki_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/wiki/status", base_url=base_url)
    assert status == 200
    assert "status" in payload


def test_v1_system_health_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/system/health", base_url=base_url)
    assert status == 200
    assert "status" in payload


def test_v1_health_agent_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/health/agent", base_url=base_url)
    assert status == 200


def test_v1_reasoning_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/reasoning", base_url=base_url)
    assert status == 200


def test_v1_model_auxiliary_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/model/auxiliary", base_url=base_url)
    assert status == 200


def test_v1_updates_check_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/updates/check", base_url=base_url)
    assert status == 200


def test_v1_commands_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/commands", base_url=base_url)
    assert status == 200
    assert "commands" in payload


def test_v1_personalities_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/personalities", base_url=base_url)
    assert status == 200
    assert "personalities" in payload


def test_v1_notes_sources_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/notes/sources", base_url=base_url)
    assert status == 200


def test_v1_commands_exec_requires_command(base_url):
    payload, status, _ = _get_json(
        "/api/v1/commands/exec",
        base_url=base_url,
        method="POST",
        body={"command": ""},
    )
    assert status == 400
    assert "required" in payload.get("error", "").lower()


def test_v1_background_status_requires_session_id(base_url):
    payload, status, _ = _get_json("/api/v1/background/status", base_url=base_url)
    assert status == 400
    assert "session_id" in payload.get("error", "").lower()


def test_v1_personality_set_requires_session(base_url):
    payload, status, _ = _get_json(
        "/api/v1/personality/set",
        base_url=base_url,
        method="POST",
        body={"session_id": "missing-session-id", "name": ""},
    )
    assert status == 404
    assert "not found" in payload.get("error", "").lower()


def test_v1_phase4_endpoints_use_services_not_legacy_bridge():
    repo_root = pathlib.Path(__file__).parent.parent
    for rel_path in (
        "app/api/v1/endpoints/agent_actions.py",
        "app/api/v1/endpoints/commands.py",
        "app/api/v1/endpoints/notes.py",
        "app/api/v1/endpoints/personalities.py",
    ):
        source = (repo_root / rel_path).read_text(encoding="utf-8")
        assert "dispatch_legacy_route" not in source
        assert "_service." in source


def test_v1_session_move_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/move",
        base_url=base_url,
        method="POST",
        body={"project_id": None},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_update_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/update",
        base_url=base_url,
        method="POST",
        body={"model": "openai/gpt-5.4-mini"},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_draft_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/draft",
        base_url=base_url,
        method="POST",
        body={"text": "hello"},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_archive_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/archive",
        base_url=base_url,
        method="POST",
        body={"archived": True},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_import_cli_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/import_cli",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_delete_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/delete",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_rename_requires_fields(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/rename",
        base_url=base_url,
        method="POST",
        body={"session_id": "abc123"},
    )
    assert status == 422 or status == 400


def test_v1_session_update_unknown_session(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/update",
        base_url=base_url,
        method="POST",
        body={"session_id": "nosuchsession", "model": "openai/gpt-5.4-mini"},
    )
    assert status == 404
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "not found" in message


def test_v1_session_draft_roundtrip(base_url):
    session_payload, session_status, _ = _get_json(
        "/api/v1/session/new",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert session_status == 200
    session_id = session_payload["session"]["session_id"]
    draft_payload, draft_status, _ = _get_json(
        "/api/v1/session/draft",
        base_url=base_url,
        method="POST",
        body={"session_id": session_id, "text": "composer draft", "files": []},
    )
    assert draft_status == 200
    assert draft_payload.get("ok") is True
    assert draft_payload.get("draft", {}).get("text") == "composer draft"


def test_v1_session_truncate_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/truncate",
        base_url=base_url,
        method="POST",
        body={"keep_count": 0},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_truncate_requires_keep_count(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/truncate",
        base_url=base_url,
        method="POST",
        body={"session_id": "abc123"},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "keep_count" in message


def test_v1_session_duplicate_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/duplicate",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_clear_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/clear",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_conversation_rounds_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/conversation-rounds",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_handoff_summary_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/handoff-summary",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_toolsets_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/toolsets",
        base_url=base_url,
        method="POST",
        body={"toolsets": ["bash"]},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_retry_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/retry",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_undo_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/undo",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_lineage_report_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/session/lineage/report",
        base_url=base_url,
    )
    assert status == 400
    message = (payload.get("error") or payload.get("detail") or "").lower()
    assert "session_id" in message


def test_v1_session_clear_roundtrip(base_url):
    session_payload, session_status, _ = _get_json(
        "/api/v1/session/new",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert session_status == 200
    session_id = session_payload["session"]["session_id"]
    clear_payload, clear_status, _ = _get_json(
        "/api/v1/session/clear",
        base_url=base_url,
        method="POST",
        body={"session_id": session_id},
    )
    assert clear_status == 200
    assert clear_payload.get("ok") is True
    assert clear_payload.get("session", {}).get("title") == "Untitled"


def test_v1_file_save_requires_session_or_workspace(base_url):
    payload, status, _ = _get_json(
        "/api/v1/file/save",
        base_url=base_url,
        method="POST",
        body={"path": "test.txt", "content": "hello"},
    )
    assert status == 400
    message = payload.get("error", "").lower()
    assert "session_id" in message or "workspace" in message


def test_v1_git_stage_requires_session_id(base_url):
    payload, status, _ = _get_json(
        "/api/v1/git/stage",
        base_url=base_url,
        method="POST",
        body={"paths": ["README.md"]},
    )
    assert status == 400
    assert "session_id" in payload.get("error", "").lower()


def test_v1_chat_stream_status_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/chat/stream/status", base_url=base_url)
    assert status == 200
    assert "status" in payload or "stream_id" in payload or payload.get("ok") is not None


def test_v1_sessions_search_endpoint(base_url):
    payload, status, _ = _get_json("/api/v1/sessions/search?q=test", base_url=base_url)
    assert status == 200
    assert "sessions" in payload


def test_v1_transcribe_requires_multipart(base_url):
    payload, status, _ = _get_json(
        "/api/v1/transcribe",
        base_url=base_url,
        method="POST",
        body={},
    )
    assert status == 400
    assert "error" in payload
