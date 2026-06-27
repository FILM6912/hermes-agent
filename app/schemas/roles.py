"""Role management request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.roles import validate_role_id


class PermissionCatalogEntry(BaseModel):
    id: str
    label: str


class RoleSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "user",
                "label": "User",
                "description": "Standard user",
                "permissions": {
                    "upload:file": True,
                    "chat:send": True,
                    "users:manage": False,
                },
                "requires_profile": True,
                "builtin": True,
            }
        }
    )

    id: str
    label: str
    description: str | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)
    requires_profile: bool = False
    builtin: bool = False
    created_at: float | None = None
    updated_at: float | None = None
    created_by: str | None = None
    updated_by: str | None = None


class RoleListResponse(BaseModel):
    roles: list[RoleSummary]
    permissions: list[PermissionCatalogEntry] = Field(default_factory=list)


class RoleCreateRequest(BaseModel):
    id: str | None = Field(default=None, min_length=3, max_length=32)
    label: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    permissions: dict[str, bool] = Field(min_length=1)
    requires_profile: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return validate_role_id(value)


class RoleUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    permissions: dict[str, bool] | None = None
    requires_profile: bool | None = None


class RoleMutationResponse(BaseModel):
    ok: bool = True
    role: RoleSummary
