"""Native FastAPI skills endpoints (SkillsService mutations)."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import Response

from app.services.skills import SkillsService

router = APIRouter(tags=["skills"])
_service = SkillsService()


@contextmanager
def _request_profile_scope(request: Request) -> Iterator[None]:
    """Keep profile cookie context on the request thread (sync routes use a worker pool)."""
    from app.domain.helpers import get_profile_cookie
    from app.domain.profiles import clear_request_profile, set_request_profile

    class _Shim:
        headers = request.headers

    profile = get_profile_cookie(_Shim())
    if profile:
        set_request_profile(profile)
    try:
        yield
    finally:
        clear_request_profile()


@router.get("/skills")
async def list_skills(
    request: Request,
    category: str | None = Query(default=None),
) -> dict[str, Any]:
    from app.domain.routes import _active_skills_dir, _skills_list_from_dir

    with _request_profile_scope(request):
        from app.core.security import get_current_user

        user = get_current_user(request)
        data = _skills_list_from_dir(
            _active_skills_dir(),
            category=category,
            user=user,
        )
        return {"skills": data.get("skills", [])}


@router.get("/skills/content")
async def skill_content(
    request: Request,
    name: str = Query(default=""),
    file: str = Query(default=""),
) -> dict[str, Any]:
    if not name:
        raise HTTPException(status_code=400, detail="name required")

    with _request_profile_scope(request):
        if file:
            from app.domain.routes import (
                _active_skill_search_dirs,
                _active_skills_dir,
                _find_skill_in_dirs,
            )

            if re.search(r"[*?\[\]]", name):
                raise HTTPException(status_code=400, detail="Invalid skill name")
            skills_dir = _active_skills_dir()
            skill_dir, _skill_md = _find_skill_in_dirs(
                name, _active_skill_search_dirs(skills_dir)
            )
            if not skill_dir:
                raise HTTPException(status_code=404, detail="Skill not found")
            target = (skill_dir / file).resolve()
            try:
                target.relative_to(skill_dir.resolve())
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid file path")
            if not target.exists() or not target.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            return {
                "content": target.read_text(encoding="utf-8"),
                "path": file,
            }

        from app.domain.routes import _skill_view_from_active_dir

        data = _skill_view_from_active_dir(name)
        if not isinstance(data.get("linked_files"), dict):
            data["linked_files"] = {}
        return data


async def _parse_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


@router.post("/skills/save")
async def save_skill(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.save(body, headers=dict(request.headers))


@router.post("/skills/delete")
async def delete_skill(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.delete(body, headers=dict(request.headers))


@router.post("/skills/toggle")
async def toggle_skill(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.toggle(body, headers=dict(request.headers))


@router.get("/skills/hub/preview")
async def skills_hub_preview(
    request: Request,
    identifier: str = Query(default=""),
) -> dict[str, Any]:
    from app.domain.skill_hub_preview import fetch_hub_skill_preview

    with _request_profile_scope(request):
        data = fetch_hub_skill_preview(identifier)
        if not data.get("success"):
            detail = str(data.get("error") or "Skill not found")
            status = 400 if detail == "identifier required" else 404
            raise HTTPException(status_code=status, detail=detail)
        return data


@router.get("/skills/hub/search")
async def skills_hub_search(
    request: Request,
    q: str = Query(default=""),
    source: str = Query(default="skills-sh"),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, Any]:
    query = (q or "").strip()
    if not query:
        return {"results": [], "query": query, "source": source}
    try:
        from tools.skills_hub import GitHubAuth, create_source_router, unified_search
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="skills hub unavailable") from exc

    from app.domain.skill_hub_search import (
        group_hub_search_results,
        hub_search_limit,
        is_repo_hub_query,
        serialize_hub_search_meta,
    )

    effective_limit = hub_search_limit(query, limit)
    with _request_profile_scope(request):
        auth = GitHubAuth()
        sources = create_source_router(auth)
        metas = unified_search(query, sources, source_filter=source, limit=effective_limit)
        results = [serialize_hub_search_meta(meta) for meta in metas]
        payload: dict[str, Any] = {
            "results": results,
            "query": query,
            "source": source,
            "limit": effective_limit,
        }
        if is_repo_hub_query(query) or len({r.get("repo") for r in results if r.get("repo")}) == 1:
            payload["groups"] = group_hub_search_results(results)
        return payload


@router.post("/skills/install")
async def install_skill(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.install(body, headers=dict(request.headers))
