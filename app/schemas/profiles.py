"""Profile request/response schemas."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class ProfileSummary(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "name": "default",
                "path": "/home/sd/.hermes",
                "is_default": True,
                "is_active": True,
                "gateway_running": True,
                "model": "gpt-5",
                "provider": "openai",
                "has_env": True,
                "skill_count": 12,
            }
        },
    )

    name: str
    path: str
    is_default: bool = False
    is_active: bool = False
    gateway_running: bool = False
    model: str | None = None
    provider: str | None = None
    has_env: bool = False
    skill_count: int = 0


class ProfileListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "profiles": [
                    {
                        "name": "default",
                        "path": "/home/sd/.hermes",
                        "is_default": True,
                        "is_active": True,
                        "gateway_running": True,
                        "model": "gpt-5",
                        "provider": "openai",
                        "has_env": True,
                        "skill_count": 12,
                    }
                ],
                "active": "default",
            }
        }
    )

    profiles: list[ProfileSummary]
    active: str


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1)
    clone_from: str | None = None
    clone_config: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    model_provider: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        if not _PROFILE_ID_RE.match(cleaned):
            raise ValueError(
                "Invalid profile name: lowercase letters, numbers, hyphens, underscores only"
            )
        return cleaned

    @field_validator("clone_from")
    @classmethod
    def validate_clone_from(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not _PROFILE_ID_RE.match(cleaned):
            raise ValueError("Invalid clone_from name")
        return cleaned

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return cleaned


class ProfileCreateResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "profile": {
                    "name": "film",
                    "path": "/home/sd/.hermes/profiles/film",
                    "is_default": False,
                    "is_active": False,
                    "gateway_running": False,
                    "model": "gpt-5-mini",
                    "provider": "openai",
                    "has_env": True,
                    "skill_count": 0,
                },
            }
        }
    )

    ok: bool = True
    profile: ProfileSummary


class ProfileDeleteRequest(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class ProfileDeleteResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"example": {"ok": True}},
    )

    ok: bool = True


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1)
    default_model: str | None = None
    model_provider: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        if cleaned != "default" and not _PROFILE_ID_RE.match(cleaned):
            raise ValueError(
                "Invalid profile name: lowercase letters, numbers, hyphens, underscores only"
            )
        return cleaned

    @field_validator("default_model", "model_provider")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProfileUpdateResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "profile": {
                    "name": "default",
                    "path": "/home/sd/.hermes",
                    "is_default": True,
                    "is_active": True,
                    "gateway_running": True,
                    "model": "gpt-5",
                    "provider": "openai",
                    "has_env": True,
                    "skill_count": 12,
                },
            }
        }
    )

    ok: bool = True
    profile: ProfileSummary


class ProfileSyncRequest(BaseModel):
    name: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned


class ProfileSyncAdded(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "config": ["config.yaml"],
                "mcp_servers": ["cursor-ide-browser"],
                "skills": ["tdd"],
                "files": ["SOUL.md"],
            }
        },
    )

    config: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ProfileSyncSkipped(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "config": [".env"],
                "mcp_servers": [],
                "skills": [],
                "files": [],
            }
        },
    )

    config: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ProfileSyncResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "ok": True,
                "name": "film",
                "added": {
                    "config": ["config.yaml"],
                    "mcp_servers": ["cursor-ide-browser"],
                    "skills": ["tdd"],
                    "files": ["SOUL.md"],
                },
                "skipped": {
                    "config": [".env"],
                    "mcp_servers": [],
                    "skills": [],
                    "files": [],
                },
                "profiles": [{"name": "default"}, {"name": "film"}],
                "error": None,
            }
        },
    )

    ok: bool = True
    name: str | None = None
    added: ProfileSyncAdded | dict[str, Any] | None = None
    skipped: ProfileSyncSkipped | dict[str, Any] | None = None
    profiles: list[dict[str, Any]] | None = None
    error: str | None = None


class ProfileSwitchRequest(BaseModel):
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class ProfileSwitchResponse(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "active": "film",
                "default_model": "gpt-5-mini",
                "default_model_provider": "openai",
                "default_workspace": "/home/sd/.hermes/workspace/film",
            }
        },
    )

    active: str
    default_model: str | None = None
    default_model_provider: str | None = None
    default_workspace: str | None = None
