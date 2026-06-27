"""Native FastAPI workspace Git endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.git import GitService

router = APIRouter(tags=["git"])
_service = GitService()


def _json(payload: dict[str, Any], status_code: int | None) -> JSONResponse:
    if status_code is not None:
        return JSONResponse(content=payload, status_code=status_code)
    return JSONResponse(content=payload)


class GitSessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None


class GitPathsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    path: str | None = None
    paths: list[str] | str | None = None


class GitDiscardRequest(GitPathsRequest):
    delete_untracked: bool = False


class GitCommitRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    message: str | None = None


class GitCommitSelectedRequest(GitCommitRequest):
    path: str | None = None
    paths: list[str] | str | None = None


class GitCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    ref: str | None = None
    mode: str | None = None
    new_branch: str | None = None
    track: bool = False
    dirty_mode: str = "block"


class GitStashCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    ref: str | None = None
    mode: str | None = None
    new_branch: str | None = None
    track: bool = False


@router.get("/git/status")
def git_status(session_id: str = Query(default="")) -> JSONResponse:
    payload, status_code = _service.git_status(session_id)
    return _json(payload, status_code)


@router.get("/git/branches")
def git_branches(session_id: str = Query(default="")) -> JSONResponse:
    payload, status_code = _service.git_branches(session_id)
    return _json(payload, status_code)


@router.get("/git/diff")
def git_diff(
    session_id: str = Query(default=""),
    path: str = Query(default=""),
    kind: str = Query(default="unstaged"),
) -> JSONResponse:
    payload, status_code = _service.git_diff(
        session_id=session_id,
        path=path,
        kind=kind,
    )
    return _json(payload, status_code)


@router.get("/git-info")
def git_info(session_id: str = Query(default="")) -> JSONResponse:
    payload, status_code = _service.git_info(session_id)
    return _json(payload, status_code)


@router.post("/git/stage")
def git_stage(body: GitPathsRequest) -> JSONResponse:
    payload, status_code = _service.git_stage(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/unstage")
def git_unstage(body: GitPathsRequest) -> JSONResponse:
    payload, status_code = _service.git_unstage(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/discard")
def git_discard(body: GitDiscardRequest) -> JSONResponse:
    payload, status_code = _service.git_discard(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/commit-message")
def git_commit_message(body: GitSessionRequest) -> JSONResponse:
    payload, status_code = _service.git_commit_message(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/commit-message-selected")
def git_commit_message_selected(body: GitPathsRequest) -> JSONResponse:
    payload, status_code = _service.git_commit_message_selected(
        body.model_dump(exclude_none=False)
    )
    return _json(payload, status_code)


@router.post("/git/commit")
def git_commit(body: GitCommitRequest) -> JSONResponse:
    payload, status_code = _service.git_commit(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/commit-selected")
def git_commit_selected(body: GitCommitSelectedRequest) -> JSONResponse:
    payload, status_code = _service.git_commit_selected(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/fetch")
def git_fetch(body: GitSessionRequest) -> JSONResponse:
    payload, status_code = _service.git_fetch(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/pull")
def git_pull(body: GitSessionRequest) -> JSONResponse:
    payload, status_code = _service.git_pull(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/push")
def git_push(body: GitSessionRequest) -> JSONResponse:
    payload, status_code = _service.git_push(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/checkout")
def git_checkout(body: GitCheckoutRequest) -> JSONResponse:
    payload, status_code = _service.git_checkout(body.model_dump(exclude_none=False))
    return _json(payload, status_code)


@router.post("/git/stash-checkout")
def git_stash_checkout(body: GitStashCheckoutRequest) -> JSONResponse:
    payload, status_code = _service.git_stash_checkout(body.model_dump(exclude_none=False))
    return _json(payload, status_code)
