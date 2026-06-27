"""User management request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.users import validate_email_format


class UserProfileBinding(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "film"}}
    )

    name: str


class UserWorkspaceEntry(BaseModel):
    name: str
    path: str


class UserProfileEntry(BaseModel):
    name: str
    path: str = ""


class UserSessionSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"total": 42, "active": 3, "archived": 12}}
    )

    total: int = 0
    active: int = 0
    archived: int = 0


class UserSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "film@example.com",
                "role": "admin",
                "profile_name": "default",
                "display_name": "Film",
                "department": "Engineering",
                "position": "Developer",
                "created_at": 1748845200.0,
            }
        }
    )

    email: str
    role: str
    profile_name: str | None = None
    profile_names: list[str] = Field(default_factory=list)
    display_name: str | None = None
    department: str | None = None
    position: str | None = None
    workspace_path: str | None = None
    workspaces: list[UserWorkspaceEntry] = Field(default_factory=list)
    available_workspaces: list[UserWorkspaceEntry] = Field(default_factory=list)
    assigned_profiles: list[UserProfileEntry] = Field(default_factory=list)
    enabled: bool = True
    has_mcp_api_key: bool = False
    created_at: float | None = None
    updated_at: float | None = None
    created_by: str | None = None
    updated_by: str | None = None


class UserListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "users": [
                    {
                        "email": "film@example.com",
                        "role": "admin",
                        "profile_name": "default",
                        "display_name": "Film",
                        "department": "Engineering",
                        "position": "Developer",
                        "created_at": 1748845200.0,
                    }
                ]
            }
        }
    )

    users: list[UserSummary]


class UserDetailResponse(UserSummary):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "film@example.com",
                "role": "admin",
                "profile_name": "default",
                "display_name": "Film",
                "department": "Engineering",
                "position": "Developer",
                "created_at": 1748845200.0,
                "profile": {"name": "default"},
                "session_summary": {"total": 42, "active": 3, "archived": 12},
            }
        }
    )

    profile: UserProfileBinding | None = None
    session_summary: UserSessionSummary = Field(default_factory=UserSessionSummary)


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1)
    role: str = "user"
    profile_name: str | None = None
    profile_names: list[str] | None = None
    display_name: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_format(value)

    @field_validator("profile_names")
    @classmethod
    def validate_profile_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            name = str(item or "").strip()
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned

    @field_validator("profile_name", "display_name", "department", "position")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class UserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=254)
    role: str | None = None
    profile_name: str | None = None
    profile_names: list[str] | None = None
    password: str | None = Field(default=None, min_length=1)
    display_name: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    workspace_paths: list[str] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_email_format(value)

    @field_validator("profile_names")
    @classmethod
    def validate_profile_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            name = str(item or "").strip()
            if name and name not in cleaned:
                cleaned.append(name)
        return cleaned

    @field_validator("workspace_paths")
    @classmethod
    def validate_workspace_paths(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for item in value:
            token = str(item or "").strip()
            if token and token not in cleaned:
                cleaned.append(token)
        return cleaned

    @field_validator("profile_name", "display_name", "department", "position")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def require_profile_for_scoped_role(self) -> UserUpdateRequest:
        from app.domain.roles import role_requires_profile

        if self.role is not None and role_requires_profile(self.role):
            if self.profile_name == "":
                raise ValueError("profile_name is required for profile-scoped roles")
        return self


class UserMutationResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "ok": True,
                "user": {
                    "email": "film@example.com",
                    "role": "user",
                    "profile_name": "film",
                    "display_name": "Film",
                    "department": "Engineering",
                    "position": "Developer",
                    "created_at": 1748845200.0,
                },
            }
        },
    )

    ok: bool = True
    user: UserSummary


class BootstrapAdminRequest(BaseModel):
    admin_email: str | None = None
    admin_password: str | None = None
    current_password: str | None = None


class BootstrapAdminResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "status": "ok",
                "email": "admin@example.com",
                "message": "Admin account created",
            }
        },
    )

    status: str
    email: str | None = None
    reason: str | None = None
    error: str | None = None
    message: str | None = None
