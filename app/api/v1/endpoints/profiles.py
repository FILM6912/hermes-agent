"""Native FastAPI profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.core.security import (
    AgentSoulAccessError,
    get_current_user,
)
from app.domain.profiles import ProfileAccessError
from app.schemas.profiles import (
    ProfileCreate,
    ProfileCreateResponse,
    ProfileDeleteRequest,
    ProfileDeleteResponse,
    ProfileListResponse,
    ProfileSyncRequest,
    ProfileSyncResponse,
    ProfileSwitchRequest,
    ProfileSwitchResponse,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
)
from app.services.profiles import ProfileService

router = APIRouter(tags=["profiles"])
_service = ProfileService()


@router.get("/profiles", response_model=ProfileListResponse)
def list_profiles(request: Request) -> ProfileListResponse:
    user = get_current_user(request)
    try:
        profiles = _service.list_profiles(user=user)
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ProfileListResponse(
        profiles=profiles,
        active=_service.get_active_profile_for_user(user=user),
    )


@router.post("/profile/create", response_model=ProfileCreateResponse)
def create_profile(body: ProfileCreate, request: Request) -> ProfileCreateResponse:
    user = get_current_user(request)
    try:
        profile = _service.create_profile(
            body.name,
            clone_from=body.clone_from,
            clone_config=body.clone_config,
            base_url=body.base_url,
            api_key=body.api_key,
            default_model=body.default_model,
            model_provider=body.model_provider,
            user=user,
        )
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProfileCreateResponse(profile=profile)


@router.post("/profile/update", response_model=ProfileUpdateResponse)
def update_profile(body: ProfileUpdateRequest, request: Request) -> ProfileUpdateResponse:
    user = get_current_user(request)
    patch = body.model_dump(exclude_unset=True)
    name = str(patch.pop("name", "") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        result = _service.update_profile_model(
            name,
            default_model=patch.get("default_model"),
            model_provider=patch.get("model_provider"),
            update_default="default_model" in patch,
            update_provider="model_provider" in patch,
            user=user,
        )
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProfileUpdateResponse(**result)


@router.post("/profile/delete", response_model=ProfileDeleteResponse)
def delete_profile(body: ProfileDeleteRequest, request: Request) -> ProfileDeleteResponse:
    user = get_current_user(request)
    try:
        result = _service.delete_profile(body.name, user=user)
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ProfileDeleteResponse(**result)


@router.post("/profile/sync-from-default", response_model=ProfileSyncResponse)
def sync_profile_from_default(
    body: ProfileSyncRequest,
    request: Request,
) -> ProfileSyncResponse:
    user = get_current_user(request)
    try:
        from app.core.security import ensure_agent_soul_access

        ensure_agent_soul_access(user)
    except AgentSoulAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        if body.name:
            result = _service.sync_profile_from_default(body.name, user=user)
        else:
            result = _service.sync_all_profiles_from_default(user=user)
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProfileSyncResponse(**result)


@router.post("/profile/switch", response_model=ProfileSwitchResponse)
def switch_profile(
    body: ProfileSwitchRequest,
    request: Request,
    response: Response,
) -> ProfileSwitchResponse:
    from app.domain.helpers import _sanitize_error, build_profile_cookie

    user = get_current_user(request)
    try:
        result = _service.switch_profile_client(body.name, user=user)
    except ProfileAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=_sanitize_error(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_sanitize_error(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.headers.append("set-cookie", build_profile_cookie(body.name))
    return ProfileSwitchResponse(**result)
