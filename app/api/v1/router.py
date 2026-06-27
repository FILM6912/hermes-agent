"""Aggregate FastAPI v1 routers for Hermes WebUI."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    agent_actions,
    approval,
    auth,
    chat,
    commands,
    crons,
    dashboard,
    files,
    git,
    health,
    kanban,
    mcp,
    memory,
    models,
    notes,
    onboarding,
    personalities,
    pipeline_test,
    profiles,
    projects,
    providers,
    rollback,
    sessions,
    sessions_misc,
    settings,
    skills,
    system,
    terminal,
    updates,
    upload,
    workspace,
)

from app.document_api.integration import get_document_api_router

from app.api.storage_proxy import router as storage_proxy_router

api_v1_router = APIRouter(prefix="/api/v1")
# Native WebUI routes must register before the integrated document API router:
# documents_dynamic exposes /{document_name}/{file_name} at /api/v1 and would
# otherwise steal paths such as /api/v1/auth/status (auth + status).
api_v1_router.include_router(admin.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(profiles.router)
api_v1_router.include_router(models.router)
api_v1_router.include_router(providers.router)
api_v1_router.include_router(kanban.router)
api_v1_router.include_router(files.router)
api_v1_router.include_router(git.router)
api_v1_router.include_router(crons.router)
api_v1_router.include_router(onboarding.router)
api_v1_router.include_router(terminal.router)
api_v1_router.include_router(dashboard.router)
api_v1_router.include_router(approval.router)
api_v1_router.include_router(chat.router)
api_v1_router.include_router(sessions.router)
api_v1_router.include_router(workspace.router)
api_v1_router.include_router(settings.router)
api_v1_router.include_router(mcp.router)
api_v1_router.include_router(skills.router)
api_v1_router.include_router(memory.router)
api_v1_router.include_router(upload.router)
api_v1_router.include_router(projects.router)
api_v1_router.include_router(rollback.router)
api_v1_router.include_router(sessions_misc.router)
api_v1_router.include_router(system.router)
api_v1_router.include_router(updates.router)
api_v1_router.include_router(notes.router)
api_v1_router.include_router(commands.router)
api_v1_router.include_router(personalities.router)
api_v1_router.include_router(agent_actions.router)
api_v1_router.include_router(pipeline_test.router)

_doc_router = get_document_api_router()
if _doc_router.routes:
    api_v1_router.include_router(_doc_router)

root_router = APIRouter()
root_router.include_router(health.router)
root_router.include_router(storage_proxy_router)
root_router.include_router(api_v1_router)

# Back-compat alias for app.main (Agent 1 imported `router`)
router = root_router

__all__ = ["api_v1_router", "root_router", "router"]
