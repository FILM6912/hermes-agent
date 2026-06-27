"""Tests for RAG department visibility scope."""

from __future__ import annotations

from app.document_api.rag_department_scope import (
    RagDepartmentScope,
    filter_rows_by_department_scope,
    row_visible_in_scope,
)


def test_row_visible_in_scope():
    admin = RagDepartmentScope(unrestricted=True)
    hr = RagDepartmentScope(unrestricted=False, department_id="hr")
    none = RagDepartmentScope(unrestricted=False, department_id=None)

    assert row_visible_in_scope(admin, "hr")
    assert row_visible_in_scope(hr, "hr")
    assert row_visible_in_scope(hr, "HR")
    assert not row_visible_in_scope(hr, "it")
    assert not row_visible_in_scope(hr, None)
    assert not row_visible_in_scope(none, "hr")


def test_row_visible_when_uploader_shares_department():
    from unittest.mock import patch

    hr = RagDepartmentScope(unrestricted=False, department_id="hr")
    with patch(
        "app.document_api.rag_department_scope.user_department_from_store",
        return_value="hr",
    ):
        assert row_visible_in_scope(hr, None, created_by="peer@example.com")
        assert row_visible_in_scope(hr, "it", created_by="peer@example.com")


def test_resolve_rag_department_scope_without_bound_access():
    from unittest.mock import patch

    from app.document_api.rag_department_scope import resolve_rag_department_scope

    with patch("app.domain.users.is_multi_user_enabled", return_value=True), patch(
        "app.domain.workspace.get_request_user_access",
        return_value=None,
    ):
        scope = resolve_rag_department_scope()
    assert scope.unrestricted is False
    assert scope.department_id is None


def test_resolve_rag_department_scope_uses_webui_users_department():
    from unittest.mock import patch

    from app.document_api.rag_department_scope import resolve_rag_department_scope
    from app.domain.users import UserAccess

    access = UserAccess(
        multi_user_enabled=True,
        user_id="alice@example.com",
        username="alice@example.com",
        role="user",
        department="Test",
    )
    with patch("app.domain.users.is_multi_user_enabled", return_value=True), patch(
        "app.domain.workspace.get_request_user_access",
        return_value=access,
    ):
        scope = resolve_rag_department_scope()
    assert scope.unrestricted is False
    assert scope.department_id == "test"


def test_filter_rows_by_department_scope():
    from unittest.mock import patch

    rows = [
        {"file_name": "a.pdf", "department_id": "hr", "created_by": "alice@example.com"},
        {"file_name": "b.pdf", "department_id": "it", "created_by": "bob@example.com"},
        {"file_name": "c.pdf", "department_id": None, "created_by": "carol@example.com"},
    ]
    hr_scope = RagDepartmentScope(unrestricted=False, department_id="hr")
    filtered = filter_rows_by_department_scope(rows, hr_scope)
    assert len(filtered) == 1
    assert filtered[0]["file_name"] == "a.pdf"

    with patch(
        "app.document_api.rag_department_scope.user_department_from_store",
        side_effect=lambda email: "hr" if email == "carol@example.com" else None,
    ):
        filtered = filter_rows_by_department_scope(rows, hr_scope)
    assert {row["file_name"] for row in filtered} == {"a.pdf", "c.pdf"}
