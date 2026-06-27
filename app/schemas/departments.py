"""Department management request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.departments import validate_department_id


class DepartmentSummary(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "hr",
                "label": "Human Resources",
                "description": "HR department",
            }
        }
    )

    id: str
    label: str
    description: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    created_by: str | None = None
    updated_by: str | None = None


class DepartmentListResponse(BaseModel):
    departments: list[DepartmentSummary]


class DepartmentCreateRequest(BaseModel):
    id: str | None = Field(default=None, min_length=2, max_length=32)
    label: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return validate_department_id(value)


class DepartmentUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)


class DepartmentMutationResponse(BaseModel):
    ok: bool = True
    department: DepartmentSummary
