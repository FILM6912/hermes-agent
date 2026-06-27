"""Department scope for transcript audio rows."""

from __future__ import annotations

from app.document_api.rag_department_scope import (
    RagDepartmentScope,
    filter_transcript_rows_by_scope,
    transcript_row_visible,
)


def test_transcript_row_visible_same_department_peer() -> None:
    scope = RagDepartmentScope(unrestricted=False, department_id="dept-a")
    assert transcript_row_visible(scope, created_by="peer@example.com") is False


def test_admin_sees_all_transcript_rows() -> None:
    scope = RagDepartmentScope(unrestricted=True)
    rows = [
        {"id": "1", "created_by": "a@x.com"},
        {"id": "2", "created_by": "b@y.com"},
    ]
    assert filter_transcript_rows_by_scope(rows, scope) == rows


def test_transcript_report_permissions_in_catalog() -> None:
    from app.domain.roles import PERMISSION_CATALOG

    for key in (
        "transcript-report:read",
        "transcript-report:create",
        "transcript-report:edit",
        "transcript-report:delete",
    ):
        assert key in PERMISSION_CATALOG
