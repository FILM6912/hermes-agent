"""Unit tests for FastAPI phase 4 projects and rollback services."""

from __future__ import annotations


def test_projects_service_list_projects():
    from app.services.projects import ProjectService

    payload = ProjectService().list_projects()
    assert "projects" in payload
    assert isinstance(payload["projects"], list)
    assert "active_profile" in payload


def test_projects_service_delete_unknown():
    from app.services.projects import ProjectService

    payload, status = ProjectService().delete_project(project_id="nonexistent_fastapi_project")
    assert status == 404
    assert "error" in payload


def test_rollback_service_list_requires_workspace():
    from app.services.rollback import RollbackService

    payload, status = RollbackService().list_checkpoints(None)
    assert status == 400
    assert "workspace" in payload.get("error", "")


def test_rollback_service_restore_requires_params():
    from app.services.rollback import RollbackService

    payload, status = RollbackService().restore_checkpoint(None, None)
    assert status == 400
    assert "error" in payload
