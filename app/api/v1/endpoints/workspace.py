"""Native FastAPI workspace endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.domain.users import resolve_request_user_access, session_allowed_for_access
from app.domain.workspace import (
    list_all_profile_workspaces,
    load_workspaces,
    profile_workspace_dir,
    resolve_profile_workspace,
    save_workspaces,
    validate_workspace_to_add,
)

router = APIRouter(tags=["workspace"])


class WorkspaceAddRequest(BaseModel):
    path: str
    name: str = ""
    create: bool = False
    parent: str = ""


class WorkspacePathRequest(BaseModel):
    path: str


class WorkspaceRenameRequest(BaseModel):
    path: str
    name: str


class WorkspaceReorderRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


@router.get("/workspaces")
def list_workspaces(request: Request) -> dict[str, Any]:
    # Aggregate one entry per profile so the picker can list/switch across
    # profiles, not just the active profile's single auto-managed workspace.
    # Non-admin accounts see all workspaces registered for their user account.
    from app.domain.workspace import (
        format_workspace_api_entry,
        get_last_workspace,
        is_virtual_workspace_path,
        nested_workspaces_enabled,
        _uses_account_workspace_registry,
    )

    access = resolve_request_user_access(request)
    workspaces = list_all_profile_workspaces(access=access)
    last = get_last_workspace()
    if nested_workspaces_enabled() and _uses_account_workspace_registry(access):
        try:
            from app.domain.profiles import get_hermes_home_for_profile
            from app.domain.workspace import _account_workspace_slug_for_access

            bound = (
                _account_workspace_slug_for_access(access)
                or access.profile_name
                or "default"
            )
            profile_home = get_hermes_home_for_profile(bound)
            include_disk = False
        except Exception:
            profile_home = None
            include_disk = False
    elif nested_workspaces_enabled() and access.is_admin:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
            include_disk = True
        except Exception:
            profile_home = None
            include_disk = False
    else:
        profile_home = None
        include_disk = False
    if profile_home is not None and workspaces and is_virtual_workspace_path(
        workspaces[0].get("path")
    ):
        workspaces = [
            format_workspace_api_entry(item, profile_home=profile_home, include_disk_path=include_disk)
            for item in workspaces
        ]
    if nested_workspaces_enabled() and is_virtual_workspace_path(last):
        pass
    elif nested_workspaces_enabled() and profile_home is not None:
        from app.domain.workspace import disk_path_to_virtual

        mapped = disk_path_to_virtual(last, profile_home)
        if mapped:
            last = mapped
    return {
        "workspaces": workspaces,
        "last": last,
        "nested_workspaces": nested_workspaces_enabled(),
    }


@router.get("/workspaces/suggest")
def suggest_workspaces(prefix: str = Query(default="")) -> dict[str, Any]:
    from app.domain.workspace import list_workspace_suggestions

    return {
        "suggestions": list_workspace_suggestions(prefix),
        "prefix": prefix,
    }


@router.get("/list")
def list_directory(
    request: Request,
    session_id: str = Query(default=""),
    workspace: str = Query(default=""),
    path: str = Query(default="."),
) -> dict[str, Any]:
    from app.domain.models import get_cli_sessions, get_session
    from app.domain.workspace import (
        dir_signature,
        ensure_profile_workspace_exists,
        list_dir,
        resolve_trusted_workspace,
        workspace_allowed_for_access,
    )

    sid = session_id.strip()
    ws_param = workspace.strip()
    if not sid and not ws_param:
        raise HTTPException(status_code=400, detail="session_id or workspace is required")

    access = resolve_request_user_access(request)
    workspace_path = ""
    if ws_param:
        if not workspace_allowed_for_access(ws_param, access):
            raise HTTPException(status_code=403, detail="Workspace not allowed")
        workspace_path = ws_param
    else:
        session_profile = None
        try:
            session = get_session(sid)
            workspace_path = session.workspace
            session_profile = getattr(session, "profile", None)
        except KeyError:
            cli_meta = None
            for row in get_cli_sessions():
                if row["session_id"] == sid:
                    cli_meta = row
                    break
            if not cli_meta:
                raise HTTPException(status_code=404, detail="Session not found")
            workspace_path = cli_meta.get("workspace", "")
            session_profile = cli_meta.get("profile")
        if not session_allowed_for_access(session_profile, access):
            raise HTTPException(status_code=404, detail="Session not found")

    if workspace_path:
        # A profile's own canonical workspace can be missing after a layout
        # migration or wiped container state; recreate it (trusted, system-
        # managed) so listing the profile root does not hard-error.
        try:
            ws_root = resolve_trusted_workspace(workspace_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ensure_profile_workspace_exists(ws_root)
    else:
        ws_root = None
    try:
        if ws_root is None:
            raise HTTPException(status_code=400, detail="workspace is required")
        entries = list_dir(ws_root, path)
        return {
            "entries": entries,
            "signature": dir_signature(ws_root, path, entries),
            "path": path,
        }
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _profile_home_for_workspace_request(request: Request, access) -> Path:
    from app.domain.profiles import get_active_hermes_home, get_hermes_home_for_profile
    from app.domain.workspace import _uses_account_workspace_registry, nested_workspaces_enabled

    if nested_workspaces_enabled():
        if _uses_account_workspace_registry(access):
            bound = getattr(access, "profile_name", None) or "default"
            return get_hermes_home_for_profile(bound)
        if getattr(access, "is_admin", False):
            return get_active_hermes_home()
    if getattr(access, "restricts_profiles", False):
        bound = getattr(access, "profile_name", None) or "default"
        return get_hermes_home_for_profile(bound)
    return get_active_hermes_home()


@router.post("/workspaces/add")
def add_workspace(request: Request, body: WorkspaceAddRequest) -> dict[str, Any]:
    from app.domain.routes import (  # noqa: PLC0415
        MAX_WORKSPACES_PER_PROFILE,
        _is_blocked_system_path,
        _strip_surrounding_quotes,
    )
    from app.domain.workspace import (
        add_nested_workspace,
        build_virtual_workspace_path,
        disk_path_to_virtual,
        format_workspace_api_entry,
        is_virtual_workspace_path,
        load_workspaces_for_profile,
        nested_workspaces_enabled,
        save_workspaces_for_profile,
        virtual_path_to_disk,
    )

    access = resolve_request_user_access(request)
    path_str = _strip_surrounding_quotes(body.path.strip())
    name = body.name.strip()
    parent = _strip_surrounding_quotes(body.parent.strip()) if body.parent else ""

    if nested_workspaces_enabled():
        profile_home = _profile_home_for_workspace_request(request, access)
        try:
            if is_virtual_workspace_path(path_str):
                virtual_path = path_str
                display_name = name or Path(virtual_path).name
                disk = virtual_path_to_disk(virtual_path, profile_home)
                if body.create:
                    disk.mkdir(parents=True, exist_ok=True)
                workspaces = load_workspaces_for_profile(profile_home)
                if any(item.get("path") == virtual_path for item in workspaces):
                    raise HTTPException(status_code=400, detail="Workspace already in list")
                workspaces.append({"path": virtual_path, "name": display_name})
                save_workspaces_for_profile(profile_home, workspaces)
            elif path_str and not Path(path_str).is_absolute() and "/" not in path_str.strip("/"):
                folder_segment = path_str
                entry = add_nested_workspace(
                    name=folder_segment,
                    parent=parent or None,
                    profile_home=profile_home,
                    create=body.create or True,
                )
                virtual_path = entry["path"]
                if name and name != entry.get("name"):
                    workspaces = load_workspaces_for_profile(profile_home)
                    for item in workspaces:
                        if item.get("path") == virtual_path:
                            item["name"] = name
                            break
                    save_workspaces_for_profile(profile_home, workspaces)
                    entry["name"] = name
            else:
                if not path_str:
                    raise HTTPException(status_code=400, detail="path or name is required")
                candidate = Path(path_str).expanduser().resolve()
                if _is_blocked_system_path(candidate):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Path points to a system directory: {candidate}",
                    )
                try:
                    canonical = profile_workspace_dir(profile_home).resolve()
                    candidate.relative_to(canonical)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=403,
                        detail="Nested workspaces must stay inside your profile workspace",
                    ) from exc
                mapped = disk_path_to_virtual(candidate, profile_home)
                if not mapped:
                    raise HTTPException(status_code=400, detail="Path is outside profile workspace")
                virtual_path = mapped
                if body.create:
                    candidate.mkdir(parents=True, exist_ok=True)
                workspaces = load_workspaces_for_profile(profile_home)
                if any(item.get("path") == virtual_path for item in workspaces):
                    raise HTTPException(status_code=400, detail="Workspace already in list")
                workspaces.append(
                    {"path": virtual_path, "name": name or candidate.name},
                )
                save_workspaces_for_profile(profile_home, workspaces)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        nested = load_workspaces_for_profile(profile_home)
        formatted = [
            format_workspace_api_entry(
                item,
                profile_home=profile_home,
                include_disk_path=not access.restricts_profiles,
            )
            for item in nested
        ]
        return {"ok": True, "workspaces": formatted, "path": virtual_path}

    if not path_str:
        raise HTTPException(status_code=400, detail="path is required")
    candidate = Path(path_str).expanduser().resolve()
    if _is_blocked_system_path(candidate):
        raise HTTPException(
            status_code=400,
            detail=f"Path points to a system directory: {candidate}",
        )
    if body.create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not create directory: {exc}",
            ) from exc
    try:
        resolved = validate_workspace_to_add(path_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    workspaces = load_workspaces()
    if len(workspaces) >= MAX_WORKSPACES_PER_PROFILE:
        raise HTTPException(
            status_code=400,
            detail=(
                "Each profile can only have one workspace. "
                "It is created automatically under the profile directory."
            ),
        )
    if any(item["path"] == str(resolved) for item in workspaces):
        raise HTTPException(status_code=400, detail="Workspace already in list")
    workspaces.append({"path": str(resolved), "name": name or resolved.name})
    save_workspaces(workspaces)
    return {"ok": True, "workspaces": list_all_profile_workspaces(access=access)}


@router.post("/workspaces/remove")
def remove_workspace(request: Request, body: WorkspacePathRequest) -> dict[str, Any]:
    from app.domain.workspace import (
        format_workspace_api_entry,
        is_virtual_workspace_path,
        load_workspaces_for_profile,
        nested_workspaces_enabled,
        remove_nested_workspace,
        VIRTUAL_WORKSPACE_ROOT,
    )

    path_str = body.path.strip()
    if not path_str:
        raise HTTPException(status_code=400, detail="path is required")
    access = resolve_request_user_access(request)
    if nested_workspaces_enabled() and is_virtual_workspace_path(path_str):
        if path_str == VIRTUAL_WORKSPACE_ROOT:
            raise HTTPException(
                status_code=400,
                detail="The profile workspace root cannot be removed",
            )
        profile_home = _profile_home_for_workspace_request(request, access)
        try:
            nested = remove_nested_workspace(path_str, profile_home=profile_home)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        formatted = [
            format_workspace_api_entry(
                item,
                profile_home=profile_home,
                include_disk_path=not access.restricts_profiles,
            )
            for item in nested
        ]
        return {"ok": True, "workspaces": formatted}
    raise HTTPException(
        status_code=400,
        detail=(
            "The profile workspace cannot be removed. Each profile keeps one "
            "auto-created workspace."
        ),
    )


@router.post("/workspaces/rename")
def rename_workspace(request: Request, body: WorkspaceRenameRequest) -> dict[str, Any]:
    from app.domain.workspace import (
        VIRTUAL_WORKSPACE_ROOT,
        format_workspace_api_entry,
        is_virtual_workspace_path,
        load_workspaces_for_profile,
        nested_workspaces_enabled,
    )

    path_str = body.path.strip()
    name = body.name.strip()
    if not path_str or not name:
        raise HTTPException(status_code=400, detail="path and name are required")
    access = resolve_request_user_access(request)
    if nested_workspaces_enabled() and is_virtual_workspace_path(path_str):
        if path_str.rstrip("/") == VIRTUAL_WORKSPACE_ROOT:
            raise HTTPException(
                status_code=400,
                detail="The profile workspace root cannot be renamed",
            )
        profile_home = _profile_home_for_workspace_request(request, access)
        workspaces = load_workspaces_for_profile(profile_home)
        for item in workspaces:
            if item.get("path") == path_str:
                item["name"] = name
                break
        else:
            raise HTTPException(status_code=404, detail="Workspace not found")
        from app.domain.workspace import save_workspaces_for_profile

        save_workspaces_for_profile(profile_home, workspaces)
        formatted = [
            format_workspace_api_entry(
                item,
                profile_home=profile_home,
                include_disk_path=not access.restricts_profiles,
            )
            for item in workspaces
        ]
        return {"ok": True, "workspaces": formatted}
    # The picker now lists absolute, resolved paths across profiles, while the
    # active profile's saved entry may still be the relative ``./workspace``.
    # Match on the resolved path so renaming the active profile's workspace keeps
    # working regardless of which spelling the client sends.
    try:
        target = resolve_profile_workspace(path_str)
    except Exception:
        target = None
    workspaces = load_workspaces()
    for item in workspaces:
        item_path = item.get("path", "")
        matched = item_path == path_str
        if not matched and target is not None and item_path:
            try:
                matched = resolve_profile_workspace(item_path) == target
            except Exception:
                matched = False
        if matched:
            item["name"] = name
            break
    else:
        raise HTTPException(status_code=404, detail="Workspace not found")
    save_workspaces(workspaces)
    access = resolve_request_user_access(request)
    return {"ok": True, "workspaces": list_all_profile_workspaces(access=access)}


@router.post("/workspaces/reorder")
def reorder_workspaces(request: Request, body: WorkspaceReorderRequest) -> dict[str, Any]:
    if not body.paths:
        raise HTTPException(status_code=400, detail="paths is required and must be a list")
    workspaces = load_workspaces()
    by_path = {item["path"]: item for item in workspaces}
    reordered: list[dict] = []
    seen: set[str] = set()
    for raw in body.paths:
        path = raw.strip()
        if path in by_path and path not in seen:
            reordered.append(by_path[path])
            seen.add(path)
    for item in workspaces:
        if item["path"] not in seen:
            reordered.append(item)
    save_workspaces(reordered)
    access = resolve_request_user_access(request)
    return {"ok": True, "workspaces": list_all_profile_workspaces(access=access)}
