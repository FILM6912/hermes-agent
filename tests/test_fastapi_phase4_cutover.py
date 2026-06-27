"""Unit and integration tests for FastAPI phase 4 native cutover services."""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request

from app.services.agent_actions import AgentActionsService
from app.services.approval import ApprovalService
from app.services.commands import CommandsService
from app.services.notes import NotesService
from app.services.personalities import PersonalitiesService
from app.services.providers import ProviderService
from app.services.sessions import SessionService

REPO_ROOT = pathlib.Path(__file__).parent.parent


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
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read()), exc.code


def test_phase4_endpoints_use_services_not_legacy_bridge():
    for rel_path in (
        "app/api/v1/endpoints/agent_actions.py",
        "app/api/v1/endpoints/commands.py",
        "app/api/v1/endpoints/notes.py",
        "app/api/v1/endpoints/personalities.py",
    ):
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "dispatch_legacy_route" not in source
        assert "_service." in source


def test_commands_service_list_commands():
    service = CommandsService()
    payload = service.list_commands()
    assert "commands" in payload
    assert isinstance(payload["commands"], list)


def test_commands_service_exec_requires_command():
    service = CommandsService()
    payload, status = service.exec_command("")
    assert status == 400
    assert "required" in payload.get("error", "").lower()


def test_commands_service_exec_unknown_plugin_command(monkeypatch):
    service = CommandsService()

    def _raise(_command: str):
        raise KeyError("missing")

    monkeypatch.setattr("app.domain.commands.execute_plugin_command", _raise)
    payload, status = service.exec_command("/missing-plugin-cmd")
    assert status == 404
    assert "not found" in payload.get("error", "").lower()


def test_personalities_service_list_personalities():
    service = PersonalitiesService()
    payload = service.list_personalities()
    assert "personalities" in payload
    assert isinstance(payload["personalities"], list)


def test_personalities_service_set_requires_session_id():
    service = PersonalitiesService()
    payload, status = service.set_personality(session_id="", name="")
    assert status == 400
    assert "session_id" in payload.get("error", "").lower()


def test_personalities_service_set_missing_session():
    service = PersonalitiesService()
    payload, status = service.set_personality(session_id="nonexistent123", name="")
    assert status == 404
    assert "not found" in payload.get("error", "").lower()


def test_agent_actions_background_status_requires_session_id():
    service = AgentActionsService()
    payload, status = service.background_status("")
    assert status == 400
    assert "session_id" in payload.get("error", "").lower()


def test_approval_service_clarify_pending_empty():
    service = ApprovalService()
    payload = service.get_clarify_pending("no_such_session")
    assert payload == {"pending": None}


def test_approval_service_clarify_respond_requires_session_id():
    service = ApprovalService()
    payload, status = service.clarify_respond(session_id="", response="yes")
    assert status == 400
    assert "session_id" in payload.get("error", "")


def test_sessions_service_compress_status_idle():
    service = SessionService()
    payload, status = service.compress_status("test_idle_sid")
    assert status == 200
    assert payload.get("status") == "idle"
    assert payload.get("ok") is True


def test_providers_service_cost_history_returns_dict():
    service = ProviderService()
    payload = service.get_cost_history(None, days=7)
    assert isinstance(payload, dict)


def test_agent_actions_background_status_empty_results():
    service = AgentActionsService()
    payload, status = service.background_status("test-session-id")
    assert status == 200
    assert payload == {"results": []}


def test_notes_service_list_sources_returns_response():
    service = NotesService()
    response = service.list_sources(headers={})
    assert response.status_code == 200
    body = json.loads(response.body)
    assert "sources" in body


def test_notes_service_search_returns_response():
    service = NotesService()
    response = service.search(query_params={"q": "test"}, headers={})
    assert response.status_code in {200, 404, 400, 502}
    body = json.loads(response.body)
    assert "results" in body or "error" in body


def test_v1_commands_endpoint(base_url):
    payload, status = _get_json("/api/v1/commands", base_url=base_url)
    assert status == 200
    assert "commands" in payload


def test_v1_personalities_endpoint(base_url):
    payload, status = _get_json("/api/v1/personalities", base_url=base_url)
    assert status == 200
    assert "personalities" in payload


def test_v1_notes_sources_endpoint(base_url):
    payload, status = _get_json("/api/v1/notes/sources", base_url=base_url)
    assert status == 200


def test_v1_commands_exec_requires_command(base_url):
    payload, status = _get_json(
        "/api/v1/commands/exec",
        base_url=base_url,
        method="POST",
        body={"command": ""},
    )
    assert status == 400
    assert "required" in payload.get("error", "").lower()


def test_v1_background_status_requires_session_id(base_url):
    payload, status = _get_json("/api/v1/background/status", base_url=base_url)
    assert status == 400
    assert "session_id" in payload.get("error", "").lower()


def test_v1_personality_set_requires_session(base_url):
    payload, status = _get_json(
        "/api/v1/personality/set",
        base_url=base_url,
        method="POST",
        body={"session_id": "missing-session-id", "name": ""},
    )
    assert status == 404
    assert "not found" in payload.get("error", "").lower()
