"""Unit tests for FastAPI phase 4 dashboard/approval/terminal services."""

from __future__ import annotations

import uuid


def test_dashboard_service_delegates_to_probe(monkeypatch):
    from app.services.dashboard import DashboardService

    service = DashboardService()
    monkeypatch.setattr(
        "app.domain.dashboard_probe.get_dashboard_status",
        lambda config_data=None: {"running": False, "enabled": "auto"},
    )
    monkeypatch.setattr(
        "app.domain.dashboard_probe.get_dashboard_config",
        lambda config_data=None: {"enabled": "auto", "url": ""},
    )
    monkeypatch.setattr(
        "app.domain.dashboard_probe.save_dashboard_config",
        lambda payload: {"enabled": payload["enabled"], "url": payload.get("url", "")},
    )

    assert service.get_status() == {"running": False, "enabled": "auto"}
    assert service.get_config() == {"enabled": "auto", "url": ""}
    assert service.save_config({"enabled": "never", "url": ""}) == {
        "enabled": "never",
        "url": "",
    }


def test_approval_service_pending_and_inject():
    from app.domain.routes import _lock, _pending
    from app.services.approval import ApprovalService

    service = ApprovalService()
    sid = f"test_approval_service_{uuid.uuid4().hex}"

    assert service.get_pending(sid) == {"pending": None, "pending_count": 0}

    payload, status = service.inject_test(session_id=sid, pattern_key="demo", command="echo hi")
    assert status == 200
    assert payload == {"ok": True, "session_id": sid}

    pending = service.get_pending(sid)
    assert pending["pending_count"] == 1
    assert pending["pending"]["command"] == "echo hi"
    assert pending["pending"]["pattern_key"] == "demo"

    with _lock:
        _pending.pop(sid, None)


def test_approval_service_respond_requires_session_id():
    from app.services.approval import ApprovalService

    payload, status = ApprovalService().respond(session_id="", choice="deny")
    assert status == 400
    assert payload["error"] == "session_id is required"


def test_approval_service_respond_rejects_invalid_choice():
    from app.services.approval import ApprovalService

    payload, status = ApprovalService().respond(session_id="sid", choice="maybe")
    assert status == 400
    assert "Invalid choice" in payload["error"]


def test_terminal_service_start_requires_session_id():
    from app.services.terminal import TerminalService

    payload, status = TerminalService().start(session_id="")
    assert status == 400
    assert payload["error"] == "session_id required"


def test_terminal_service_input_rejects_oversized_payload():
    from app.services.terminal import TerminalService

    payload, status = TerminalService().write_input(
        session_id="sid",
        data="x" * 9000,
    )
    assert status == 413
    assert payload["error"] == "input too large"
