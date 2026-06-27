"""Auth request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthStatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "auth_enabled": True,
                "logged_in": True,
                "user_id": "film@example.com",
                "email": "film@example.com",
                "display_name": "Film",
                "department": "Engineering",
                "position": "Developer",
                "role": "admin",
                "profile_name": "default",
                "multi_user": True,
                "password_auth_enabled": True,
                "passwordless_enabled": False,
                "passkeys_enabled": True,
                "passkeys_count": 1,
                "passkey_feature_flag": True,
                "csrf_token": "csrf-example-token",
            }
        }
    )

    auth_enabled: bool
    logged_in: bool
    user_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    department: str | None = None
    position: str | None = None
    role: str | None = None
    permissions: dict[str, bool] = Field(default_factory=dict)
    profile_name: str | None = None
    profile_names: list[str] = Field(default_factory=list)
    multi_user: bool = False
    password_auth_enabled: bool
    passwordless_enabled: bool
    passkeys_enabled: bool
    passkeys_count: int
    passkey_feature_flag: bool
    csrf_token: str | None = None


class AccountProfileResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "film@example.com",
                "display_name": "Film",
                "department": "Engineering",
                "position": "Developer",
                "role": "admin",
                "profile_name": "default",
                "multi_user": True,
            }
        }
    )

    email: str | None = None
    display_name: str | None = None
    department: str | None = None
    position: str | None = None
    role: str | None = None
    profile_name: str | None = None
    profile_names: list[str] = Field(default_factory=list)
    multi_user: bool = False


class AccountUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)


class AuthMeResponse(BaseModel):
    """Corp Brain / external SPA profile contract (GET/PATCH /api/v1/auth/me)."""

    id: str
    email: str
    display_name: str = ""
    enabled: bool = True
    role: str
    roles: list[str] = Field(default_factory=list)
    permissions: dict[str, bool] = Field(default_factory=dict)
    department: str | None = None
    position: str | None = None
    profile_name: str | None = None
    profile_names: list[str] = Field(default_factory=list)


class AuthLoginResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = True
    access_token: str | None = None
    token_type: str | None = None
    csrf_token: str | None = None
    user_id: str | None = None
    email: str | None = None
    role: str | None = None
    profile_name: str | None = None


class McpApiKeyResponse(BaseModel):
    mcp_api_key: str = Field(description="Plain MCP Bearer key — shown once; store securely")
    has_mcp_api_key: bool = True
    message: str = "Store this key securely; it will not be shown again."


class AuthLoginRequest(BaseModel):
    password: str = ""
    email: str | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_username_field(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("email") and data.get("username"):
            data = dict(data)
            data["email"] = data["username"]
        return data


class PasskeyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class PasskeyDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
