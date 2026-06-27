"""Long-tail session endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.services.sessions import SessionService
from app.domain.users import resolve_request_user_access

router = APIRouter(tags=["sessions"])
_session_service = SessionService()


class SessionDraftRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    text: str | None = None
    files: list | None = None


class SessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    workspace: str | None = None
    model: str | None = None
    model_provider: str | None = None


class SessionArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    archived: bool = True


class SessionMoveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    project_id: str | None = None


class SessionImportCliRequest(BaseModel):
    session_id: str | None = None


class SessionTruncateRequest(BaseModel):
    session_id: str | None = None
    keep_count: int | None = None


class SessionDuplicateRequest(BaseModel):
    session_id: str | None = None


class SessionClearRequest(BaseModel):
    session_id: str | None = None


class SessionConversationRoundsRequest(BaseModel):
    session_id: str | None = None
    since: float | None = None


class SessionHandoffSummaryRequest(BaseModel):
    session_id: str | None = None
    since: float | None = None


class SessionToolsetsRequest(BaseModel):
    session_id: str | None = None
    toolsets: list[str] | None = None


class SessionImportRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class SessionRetryRequest(BaseModel):
    session_id: str | None = None


class SessionUndoRequest(BaseModel):
    session_id: str | None = None


def _session_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        message = str(exc) or "Session not found"
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _legacy_error_detail(payload: dict[str, Any]) -> str:
    return str(payload.get("error") or payload.get("detail") or "Request failed")


@router.post("/session/draft")
def session_draft(body: SessionDraftRequest) -> dict[str, Any]:
    try:
        return _session_service.save_composer_draft(
            session_id=body.session_id or "",
            text=body.text,
            files=body.files,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/update")
def session_update(body: SessionUpdateRequest) -> dict[str, Any]:
    try:
        patch = body.model_dump(exclude_unset=True)
        session_id = str(patch.pop("session_id", "") or "").strip()
        return _session_service.update_session(
            session_id=session_id,
            body=patch,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/truncate")
def session_truncate(body: SessionTruncateRequest) -> dict[str, Any]:
    try:
        return _session_service.truncate_session(
            session_id=body.session_id or "",
            keep_count=body.keep_count,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/archive")
def session_archive(body: SessionArchiveRequest) -> dict[str, Any]:
    try:
        return _session_service.archive_session(
            session_id=body.session_id or "",
            archived=body.archived,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/move")
def session_move(body: SessionMoveRequest) -> dict[str, Any]:
    try:
        return _session_service.move_session(
            session_id=body.session_id or "",
            project_id=body.project_id,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/duplicate")
def session_duplicate(body: SessionDuplicateRequest) -> dict[str, Any]:
    try:
        return _session_service.duplicate_session(session_id=body.session_id or "")
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/import_cli")
def session_import_cli(body: SessionImportCliRequest) -> dict[str, Any]:
    try:
        return _session_service.import_cli(session_id=body.session_id or "")
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/clear")
def session_clear(body: SessionClearRequest) -> dict[str, Any]:
    try:
        return _session_service.clear_session(session_id=body.session_id or "")
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/conversation-rounds")
def session_conversation_rounds(body: SessionConversationRoundsRequest) -> dict[str, Any]:
    try:
        return _session_service.conversation_rounds(
            session_id=body.session_id or "",
            since=body.since,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/handoff-summary")
def session_handoff_summary(body: SessionHandoffSummaryRequest) -> dict[str, Any]:
    try:
        payload, status = _session_service.handoff_summary(
            session_id=body.session_id or "",
            since=body.since,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc
    if status >= 400:
        raise HTTPException(status_code=status, detail=_legacy_error_detail(payload))
    return payload


@router.post("/session/toolsets")
def session_toolsets(body: SessionToolsetsRequest) -> dict[str, Any]:
    try:
        return _session_service.set_toolsets(
            session_id=body.session_id or "",
            toolsets=body.toolsets,
        )
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.get("/session/lineage/report")
def session_lineage_report(session_id: str = Query(default="")) -> dict[str, Any]:
    try:
        return _session_service.lineage_report(session_id=session_id)
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.get("/sessions/search")
def sessions_search(
    request: Request,
    q: str = Query(default=""),
    content: str = Query(default="1"),
    depth: int = Query(default=5),
) -> dict[str, Any]:
    return _session_service.search_sessions(
        q=q,
        content_search=content == "1",
        depth=depth,
        access=resolve_request_user_access(request),
    )


@router.post("/session/import")
def session_import(body: SessionImportRequest) -> dict[str, Any]:
    try:
        return _session_service.import_session(body.model_dump(exclude_unset=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/session/status")
def session_status_endpoint(session_id: str = Query(default="")) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    from app.domain.models import get_session  # noqa: PLC0415
    from app.domain.routes import _clear_stale_stream_state  # noqa: PLC0415
    from app.domain.session_ops import session_status

    try:
        _clear_stale_stream_state(get_session(session_id, metadata_only=True))
        return session_status(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.get("/session/usage")
def session_usage_endpoint(session_id: str = Query(default="")) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    from app.domain.session_ops import session_usage

    try:
        return session_usage(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.post("/session/retry")
def session_retry(body: SessionRetryRequest) -> dict[str, Any]:
    try:
        return _session_service.retry_last_turn(session_id=body.session_id or "")
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc


@router.post("/session/undo")
def session_undo(body: SessionUndoRequest) -> dict[str, Any]:
    try:
        return _session_service.undo_last_turn(session_id=body.session_id or "")
    except (ValueError, KeyError) as exc:
        raise _session_service_error(exc) from exc
