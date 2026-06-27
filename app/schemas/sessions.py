"""Session summary schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    title: str = "Untitled"
    workspace: str | None = None
    model: str | None = None
    model_provider: str | None = None
    message_count: int = 0
    created_at: float | None = None
    updated_at: float | None = None
    last_message_at: float | None = None
    pinned: bool = False
    archived: bool = False
    project_id: str | None = None
    profile: str | None = None
    is_streaming: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary] = Field(default_factory=list)
