"""Native FastAPI session endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from app.services.sse_streams import (
    build_gateway_stream_response,
    build_session_events_stream_response,
)
from app.services.sessions import SessionService
from app.domain.users import resolve_request_user_access, session_allowed_for_access

router = APIRouter(tags=["sessions"])
_service = SessionService()


class SessionNewRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    workspace: str | None = None
    model: str | None = None
    model_provider: str | None = None
    profile: str | None = None
    project_id: str | None = None
    prev_session_id: str | None = None
    worktree: bool | str | None = None


class SessionRenameRequest(BaseModel):
    session_id: str
    title: str


class SessionIdRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None


class SessionPinRequest(BaseModel):
    session_id: str
    pinned: bool = True


class SessionBranchRequest(BaseModel):
    session_id: str
    keep_count: int | None = None
    title: str | None = None


class SessionCompressRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    focus_topic: str | None = None
    topic: str | None = None


class SessionWorktreeRemoveRequest(BaseModel):
    session_id: str
    force: bool = False


class SessionYoloRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    enabled: bool = True


def _yolo_helpers():
    try:
        from tools.approval import (  # noqa: PLC0415
            disable_session_yolo,
            enable_session_yolo,
            is_session_yolo_enabled,
        )
    except ImportError:
        return (
            lambda *_a, **_k: None,
            lambda *_a, **_k: None,
            lambda *_a, **_k: False,
        )
    return enable_session_yolo, disable_session_yolo, is_session_yolo_enabled


@router.get("/session/yolo")
def get_session_yolo(session_id: str = Query(default="")) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    _, _, is_enabled = _yolo_helpers()
    return {"yolo_enabled": is_enabled(session_id)}


@router.post("/session/yolo")
def post_session_yolo(body: SessionYoloRequest) -> dict[str, Any]:
    enable, disable, is_enabled = _yolo_helpers()
    sid = body.session_id
    if body.enabled:
        enable(sid)
        try:
            from tools.approval import _lock, _pending  # noqa: PLC0415

            with _lock:
                _pending.pop(sid, None)
        except Exception:
            pass
        try:
            from app.domain.routes import resolve_gateway_approval  # noqa: PLC0415

            resolve_gateway_approval(sid, "once", resolve_all=True)
        except Exception:
            pass
    else:
        disable(sid)
    return {"ok": True, "yolo_enabled": body.enabled}


@router.get("/sessions/events", include_in_schema=False)
async def sessions_events(request: Request) -> Response:
    """SSE stream for session list changes."""
    return build_session_events_stream_response(request=request)


@router.get("/sessions/gateway/stream", include_in_schema=False)
async def sessions_gateway_stream(request: Request) -> Response:
    """SSE stream for gateway session sync."""
    probe = request.query_params.get("probe", "").lower() in {"1", "true", "yes"}
    return build_gateway_stream_response(probe=probe, request=request)


@router.get("/sessions")
def list_sessions(
    request: Request,
    all_profiles: str | None = Query(default=None),
) -> dict[str, Any]:
    flag = (all_profiles or "").strip().lower()
    access = resolve_request_user_access(request)
    return _service.list_sidebar(
        all_profiles=flag in ("1", "true", "yes", "on"),
        access=access,
    )


@router.get("/session")
def get_session_detail(
    request: Request,
    session_id: str = Query(default="", alias="session_id"),
    messages: str = Query(default="1"),
    resolve_model: str | None = Query(default=None),
    msg_limit: str | None = Query(default=None),
    msg_before: str | None = Query(default=None),
) -> dict[str, Any]:
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    access = resolve_request_user_access(request)
    load_messages = messages != "0"
    resolve_model_default = "1" if load_messages else "0"
    resolve_model_flag = (resolve_model if resolve_model is not None else resolve_model_default) != "0"
    try:
        parsed_msg_limit = max(1, int(msg_limit)) if msg_limit else None
    except (ValueError, TypeError):
        parsed_msg_limit = None
    try:
        parsed_msg_before = int(msg_before) if msg_before else None
    except (ValueError, TypeError):
        parsed_msg_before = None

    from app.domain.models import get_session
    from app.domain.routes import (  # noqa: PLC0415 — shared legacy contract helper
        SessionDetailNotFound,
        build_session_detail_payload,
    )

    try:
        session = get_session(session_id, metadata_only=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    if not session_allowed_for_access(getattr(session, "profile", None), access):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        payload = build_session_detail_payload(
            session_id,
            load_messages=load_messages,
            resolve_model=resolve_model_flag,
            msg_limit=parsed_msg_limit,
            msg_before=parsed_msg_before,
        )
    except SessionDetailNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return {"session": payload}


@router.post("/session/new")
def create_session(body: SessionNewRequest, request: Request) -> dict[str, Any]:
    access = resolve_request_user_access(request)
    try:
        return _service.create_session(
            workspace=body.workspace,
            model=body.model,
            model_provider=body.model_provider,
            profile=body.profile,
            project_id=body.project_id,
            prev_session_id=body.prev_session_id,
            worktree=body.worktree,
            access=access,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/session/rename")
def rename_session(body: SessionRenameRequest) -> dict[str, Any]:
    try:
        return _service.rename_session(session_id=body.session_id, title=body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.post("/session/delete")
def delete_session(body: SessionIdRequest) -> dict[str, Any]:
    try:
        return _service.delete_session(session_id=body.session_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/session/pin")
def pin_session(body: SessionPinRequest) -> dict[str, Any]:
    try:
        return _service.pin_session(session_id=body.session_id, pinned=body.pinned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.post("/sessions/cleanup")
def cleanup_sessions() -> dict[str, Any]:
    from app.domain.config import LOCK, SESSIONS, SESSION_INDEX_FILE
    from app.domain.models import SESSION_DIR, Session

    cleaned = 0
    for path in SESSION_DIR.glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            loaded = Session.load(path.stem)
            should_delete = (
                loaded and loaded.title == "Untitled" and len(loaded.messages) == 0
            )
            if should_delete:
                with LOCK:
                    SESSIONS.pop(path.stem, None)
                path.unlink(missing_ok=True)
                cleaned += 1
        except Exception:
            pass
    if SESSION_INDEX_FILE.exists():
        SESSION_INDEX_FILE.unlink(missing_ok=True)
    return {"ok": True, "cleaned": cleaned}


@router.post("/sessions/cleanup_zero_message")
def cleanup_zero_message_sessions() -> dict[str, Any]:
    from app.domain.config import LOCK, SESSIONS, SESSION_INDEX_FILE
    from app.domain.models import SESSION_DIR, Session

    cleaned = 0
    for path in SESSION_DIR.glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            loaded = Session.load(path.stem)
            should_delete = loaded and len(loaded.messages) == 0
            if should_delete:
                with LOCK:
                    SESSIONS.pop(path.stem, None)
                path.unlink(missing_ok=True)
                cleaned += 1
        except Exception:
            pass
    if SESSION_INDEX_FILE.exists():
        SESSION_INDEX_FILE.unlink(missing_ok=True)
    return {"ok": True, "cleaned": cleaned}


@router.get("/session/export")
def export_session(session_id: str = Query(default="")) -> Response:
    content, headers, status = _service.export_session(session_id)
    if status == 400:
        raise HTTPException(status_code=400, detail="session_id is required")
    if status == 404:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(content=content, headers=headers, media_type=headers.get("Content-Type"))


@router.post("/session/branch")
def branch_session(body: SessionBranchRequest) -> dict[str, Any]:
    if not isinstance(body.session_id, str):
        raise HTTPException(status_code=400, detail="session_id must be a string")
    keep_count = body.keep_count
    if keep_count is not None:
        try:
            keep_count = int(keep_count)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="keep_count must be an integer") from exc
        if keep_count < 0:
            raise HTTPException(status_code=400, detail="keep_count must be non-negative")
    try:
        return _service.branch_session(
            session_id=body.session_id,
            keep_count=keep_count,
            title=body.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@router.get("/session/compress/status")
def session_compress_status(session_id: str = Query(default="")) -> Response:
    payload, status = _service.compress_status(session_id)
    return Response(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status,
        media_type="application/json",
    )


@router.post("/session/compress/start")
def session_compress_start(body: SessionCompressRequest) -> Response:
    payload, status = _service.compress_start(
        {
            "session_id": body.session_id,
            "focus_topic": body.focus_topic,
            "topic": body.topic,
        }
    )
    return Response(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status,
        media_type="application/json",
    )


@router.post("/session/compress")
def session_compress(body: SessionCompressRequest) -> Response:
    payload, status = _service.compress(
        {
            "session_id": body.session_id,
            "focus_topic": body.focus_topic,
            "topic": body.topic,
        }
    )
    return Response(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status,
        media_type="application/json",
    )


@router.get("/session/recovery/audit")
def session_recovery_audit() -> dict[str, Any]:
    return _service.recovery_audit()


@router.post("/session/recovery/repair-safe")
def session_recovery_repair_safe() -> Response:
    result, status = _service.recovery_repair_safe()
    return Response(
        content=json.dumps(result).encode("utf-8"),
        status_code=status,
        media_type="application/json",
    )


@router.get("/session/worktree/status")
def session_worktree_status(session_id: str = Query(default="")) -> dict[str, Any]:
    try:
        return _service.worktree_status(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        from app.domain.routes import _sanitize_error  # noqa: PLC0415

        raise HTTPException(status_code=500, detail=_sanitize_error(exc)) from exc


@router.post("/session/worktree/remove")
def session_worktree_remove(body: SessionWorktreeRemoveRequest) -> dict[str, Any]:
    if not body.session_id or not isinstance(body.session_id, str) or not body.session_id.strip():
        raise HTTPException(status_code=400, detail="session_id must be a non-empty string")
    try:
        return _service.worktree_remove(body.session_id.strip(), force=bool(body.force))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except Exception as exc:
        from app.domain.routes import _sanitize_error  # noqa: PLC0415

        raise HTTPException(status_code=500, detail=_sanitize_error(exc)) from exc

