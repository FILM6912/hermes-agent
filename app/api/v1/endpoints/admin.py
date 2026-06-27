"""FastAPI admin endpoints for multi-user management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.dependencies import RolesManageDep, UsersManageDep, WorkspacesManageDep
from app.domain.users import UserError, UserNotFoundError
from pydantic import BaseModel, Field

from app.schemas.auth import McpApiKeyResponse
from app.schemas.users import (
    UserCreateRequest,
    UserDetailResponse,
    UserListResponse,
    UserMutationResponse,
    UserSummary,
    UserUpdateRequest,
)
from app.schemas.roles import (
    RoleCreateRequest,
    RoleListResponse,
    RoleMutationResponse,
    RoleSummary,
    RoleUpdateRequest,
    PermissionCatalogEntry,
)
from app.schemas.departments import (
    DepartmentCreateRequest,
    DepartmentListResponse,
    DepartmentMutationResponse,
    DepartmentSummary,
    DepartmentUpdateRequest,
)


class AdminWorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class AdminWorkspacePathRequest(BaseModel):
    path: str = Field(min_length=1)


class AdminWorkspaceRenameRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=64)


class AdminWorkspaceListResponse(BaseModel):
    workspaces: list[dict[str, str]]


from app.services.users import UserService

router = APIRouter(prefix="/admin", tags=["admin"])
_service = UserService()


@router.get("/workspaces", response_model=AdminWorkspaceListResponse)
def list_admin_workspaces(manager: WorkspacesManageDep) -> AdminWorkspaceListResponse:
    """Top-level folders under the shared workspace mount."""
    from app.domain.workspace import list_admin_shared_workspaces

    return AdminWorkspaceListResponse(
        workspaces=list_admin_shared_workspaces(owner_email=manager.user_id)
    )


@router.post("/workspaces", response_model=AdminWorkspaceListResponse, status_code=201)
def create_admin_workspace(
    body: AdminWorkspaceCreateRequest,
    manager: WorkspacesManageDep,
) -> AdminWorkspaceListResponse:
    from app.domain.workspace import admin_create_shared_workspace_folder

    try:
        admin_create_shared_workspace_folder(body.name, owner_email=manager.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from app.domain.workspace import list_admin_shared_workspaces

    return AdminWorkspaceListResponse(
        workspaces=list_admin_shared_workspaces(owner_email=manager.user_id)
    )


@router.patch("/workspaces", response_model=AdminWorkspaceListResponse)
def rename_admin_workspace(
    body: AdminWorkspaceRenameRequest,
    manager: WorkspacesManageDep,
) -> AdminWorkspaceListResponse:
    from app.domain.workspace import (
        admin_rename_shared_workspace_folder,
        list_admin_shared_workspaces,
    )

    try:
        admin_rename_shared_workspace_folder(
            body.path,
            body.name,
            owner_email=manager.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminWorkspaceListResponse(
        workspaces=list_admin_shared_workspaces(owner_email=manager.user_id)
    )


@router.delete("/workspaces", response_model=AdminWorkspaceListResponse)
def delete_admin_workspace(
    body: AdminWorkspacePathRequest,
    manager: WorkspacesManageDep,
) -> AdminWorkspaceListResponse:
    from app.domain.workspace import (
        admin_delete_shared_workspace_folder,
        list_admin_shared_workspaces,
    )

    try:
        admin_delete_shared_workspace_folder(body.path, owner_email=manager.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminWorkspaceListResponse(
        workspaces=list_admin_shared_workspaces(owner_email=manager.user_id)
    )


@router.get("/profiles")
def list_assignable_profiles(_users: UsersManageDep) -> dict:
    """All non-root Hermes profile ids (for admin user assignment UI)."""
    from app.domain.profiles import _is_root_profile, list_profiles_api

    names: list[str] = []
    for row in list_profiles_api():
        name = str(row.get("name") or "").strip()
        if name and not _is_root_profile(name):
            names.append(name)
    return {"profiles": sorted(set(names))}


@router.get("/users", response_model=UserListResponse)
def list_users(_users: UsersManageDep) -> UserListResponse:
    return UserListResponse(users=_service.list_users())


@router.get("/users/{email}", response_model=UserDetailResponse)
def get_user(email: str, _users: UsersManageDep) -> UserDetailResponse:
    try:
        return UserDetailResponse(**_service.get_user_detail(email))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/users", response_model=UserMutationResponse, status_code=201)
def create_user(body: UserCreateRequest, _users: UsersManageDep) -> UserMutationResponse:
    try:
        user = _service.create_user(
            body.email,
            password=body.password,
            role=body.role,
            profile_name=body.profile_name,
            profile_names=body.profile_names,
            display_name=body.display_name,
            department=body.department,
            position=body.position,
        )
    except UserError as exc:
        message = str(exc)
        status_code = 409 if "already" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return UserMutationResponse(user=UserSummary(**user))


@router.patch("/users/{email}", response_model=UserMutationResponse)
def update_user(
    email: str,
    body: UserUpdateRequest,
    _users: UsersManageDep,
) -> UserMutationResponse:
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    new_email = patch.pop("email", None)
    workspace_paths = patch.pop("workspace_paths", None)
    try:
        user = _service.update_user(
            email,
            new_email=new_email,
            workspace_paths=workspace_paths,
            **patch,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserError as exc:
        message = str(exc)
        status_code = 409 if "already" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return UserMutationResponse(user=UserSummary(**user))


@router.delete("/users/{email}", status_code=204)
def delete_user(email: str, _users: UsersManageDep) -> None:
    try:
        _service.delete_user(email)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/users/{email}/mcp-key", response_model=McpApiKeyResponse)
def admin_create_user_mcp_key(email: str, manager: UsersManageDep) -> McpApiKeyResponse:
    from app.domain.mcp_keys import generate_user_mcp_api_key
    from app.domain.users import UserError, UserNotFoundError

    try:
        plain = generate_user_mcp_api_key(email, actor=manager.user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return McpApiKeyResponse(mcp_api_key=plain)


@router.delete("/users/{email}/mcp-key", status_code=204)
def admin_revoke_user_mcp_key(email: str, manager: UsersManageDep) -> None:
    from app.domain.mcp_keys import revoke_user_mcp_api_key
    from app.domain.users import UserNotFoundError

    try:
        revoke_user_mcp_api_key(email, actor=manager.user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/roles", response_model=RoleListResponse)
def list_roles(_roles: RolesManageDep) -> RoleListResponse:
    from app.domain.roles import list_permission_catalog, list_roles as load_roles

    return RoleListResponse(
        roles=[RoleSummary(**row) for row in load_roles()],
        permissions=[
            PermissionCatalogEntry(**row) for row in list_permission_catalog()
        ],
    )


@router.post("/roles", response_model=RoleMutationResponse, status_code=201)
def create_role(body: RoleCreateRequest, _roles: RolesManageDep) -> RoleMutationResponse:
    from app.domain.roles import RoleError, create_role as create_role_record

    try:
        role = create_role_record(
            body.id,
            label=body.label,
            description=body.description,
            permissions=body.permissions,
            requires_profile=body.requires_profile,
        )
    except RoleError as exc:
        message = str(exc)
        status_code = 409 if "already" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return RoleMutationResponse(role=RoleSummary(**role))


@router.patch("/roles/{role_id}", response_model=RoleMutationResponse)
def update_role(
    role_id: str,
    body: RoleUpdateRequest,
    _roles: RolesManageDep,
) -> RoleMutationResponse:
    from app.domain.roles import RoleError, RoleNotFoundError, update_role as update_role_record

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        role = update_role_record(role_id, **patch)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RoleMutationResponse(role=RoleSummary(**role))


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: str, _roles: RolesManageDep) -> None:
    from app.domain.roles import RoleError, RoleNotFoundError, delete_role as delete_role_record

    try:
        delete_role_record(role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/departments", response_model=DepartmentListResponse)
def list_departments(_users: UsersManageDep) -> DepartmentListResponse:
    from app.domain.departments import list_departments as load_departments

    return DepartmentListResponse(
        departments=[DepartmentSummary(**row) for row in load_departments()]
    )


@router.post("/departments", response_model=DepartmentMutationResponse, status_code=201)
def create_department(
    body: DepartmentCreateRequest,
    _users: UsersManageDep,
) -> DepartmentMutationResponse:
    from app.domain.departments import DepartmentError, create_department as create_department_record

    try:
        department = create_department_record(
            body.id,
            label=body.label,
            description=body.description,
        )
    except DepartmentError as exc:
        message = str(exc)
        status_code = 409 if "already" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return DepartmentMutationResponse(department=DepartmentSummary(**department))


@router.patch("/departments/{department_id}", response_model=DepartmentMutationResponse)
def update_department(
    department_id: str,
    body: DepartmentUpdateRequest,
    _users: UsersManageDep,
) -> DepartmentMutationResponse:
    from app.domain.departments import (
        DepartmentError,
        DepartmentNotFoundError,
        update_department as update_department_record,
    )

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        department = update_department_record(department_id, **patch)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DepartmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DepartmentMutationResponse(department=DepartmentSummary(**department))


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(department_id: str, _users: UsersManageDep) -> None:
    from app.domain.departments import (
        DepartmentError,
        DepartmentNotFoundError,
        delete_department as delete_department_record,
    )

    try:
        delete_department_record(department_id)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DepartmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
