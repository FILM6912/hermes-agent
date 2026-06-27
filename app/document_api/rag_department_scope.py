"""Resolve department-scoped visibility for document RAG routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RagDepartmentScope:
    """When unrestricted is True, caller may see all departments."""

    unrestricted: bool
    # Canonical department id from ``webui_users.department_id`` (fallback: legacy ``department``).
    department_id: str | None = None


def _normalize_department(value: str | None) -> str | None:
    from app.domain.departments import normalize_department_ref

    return normalize_department_ref(value)


def user_department_from_store(email: str | None) -> str | None:
    """Return the user's department id from ``webui_users`` (``department_id`` or legacy ``department``)."""
    from app.domain.users import get_user

    cleaned = str(email or "").strip().lower()
    if not cleaned:
        return None
    user = get_user(cleaned)
    if user is None:
        return None
    return _normalize_department(user.department)


def resolve_rag_department_scope() -> RagDepartmentScope:
    from app.domain.roles import role_has_full_access
    from app.domain.users import is_multi_user_enabled
    from app.domain.workspace import get_request_user_access

    if not is_multi_user_enabled():
        return RagDepartmentScope(unrestricted=True)

    access = get_request_user_access()
    if access is None:
        return RagDepartmentScope(unrestricted=False, department_id=None)

    if not access.multi_user_enabled or role_has_full_access(access.role):
        return RagDepartmentScope(unrestricted=True)

    return RagDepartmentScope(
        unrestricted=False,
        department_id=_normalize_department(getattr(access, "department", None)),
    )


def row_visible_in_pending_scope(
    scope: RagDepartmentScope,
    row_department_id: str | None,
    *,
    created_by: str | None = None,
) -> bool:
    """Department filter for upload / ingest-pending / approve queues only."""
    if scope.unrestricted:
        return True
    viewer_dept = _normalize_department(scope.department_id)
    if not viewer_dept:
        return False
    row_dept = _normalize_department(row_department_id)
    if row_dept and row_dept == viewer_dept:
        return True
    if created_by:
        uploader_dept = user_department_from_store(created_by)
        if uploader_dept and uploader_dept == viewer_dept:
            return True
    return False


# Back-compat alias for pending-row checks in routes/tests.
row_visible_in_scope = row_visible_in_pending_scope


def filter_rows_by_department_scope(
    rows: Iterable[dict[str, Any]],
    scope: RagDepartmentScope,
    *,
    key: str = "department_id",
) -> list[dict[str, Any]]:
    if scope.unrestricted:
        return list(rows)
    return [
        row
        for row in rows
        if row_visible_in_pending_scope(
            scope,
            row.get(key),
            created_by=row.get("created_by"),
        )
    ]


def list_committed_folder_files() -> list[dict[str, Any]]:
    """All committed RAG documents — readable by anyone with ``rag:search``."""
    from app.document_api.services.folder_catalog import ensure_folder_table, list_folder_files

    ensure_folder_table()
    return list_folder_files()


def list_scoped_pending_ingest(scope: RagDepartmentScope) -> list[dict[str, Any]]:
    """Pending ingest rows visible to ``scope`` (same department peers only)."""
    from app.document_api.api.v1.routes.job_common import list_dashboard_pending_ingest

    rows = list_dashboard_pending_ingest()
    return filter_rows_by_department_scope(rows, scope)


def resolve_rag_actor_context() -> tuple[str | None, str | None]:
    """Return (actor_email, department) from ``webui_users`` for the current request."""
    from app.domain.workspace import get_request_user_access

    access = get_request_user_access()
    if access is None:
        return None, None
    actor = access.user_id or access.username
    department = _normalize_department(getattr(access, "department", None))
    return (str(actor).strip() if actor else None, department)


def assert_row_accessible(
    scope: RagDepartmentScope,
    row_department_id: str | None,
    *,
    created_by: str | None = None,
) -> None:
    from fastapi import HTTPException

    if not row_visible_in_pending_scope(scope, row_department_id, created_by=created_by):
        raise HTTPException(status_code=403, detail="Department access denied")


def transcript_row_visible(
    scope: RagDepartmentScope,
    *,
    created_by: str | None,
) -> bool:
    """Transcript rows are scoped by uploader department (no ``department_id`` column)."""
    return row_visible_in_pending_scope(scope, None, created_by=created_by)


def assert_transcript_row_accessible(
    scope: RagDepartmentScope,
    *,
    created_by: str | None,
) -> None:
    from fastapi import HTTPException

    if not transcript_row_visible(scope, created_by=created_by):
        raise HTTPException(status_code=403, detail="Department access denied")


def filter_transcript_rows_by_scope(
    rows: Iterable[dict[str, Any]],
    scope: RagDepartmentScope,
) -> list[dict[str, Any]]:
    if scope.unrestricted:
        return list(rows)
    return [
        row
        for row in rows
        if transcript_row_visible(scope, created_by=row.get("created_by"))
    ]
