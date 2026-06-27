"""Tests for dynamic department store."""

from __future__ import annotations

import pytest

from app.domain.departments import (
    DepartmentError,
    create_department,
    delete_department,
    department_exists,
    list_departments,
    update_department,
)


@pytest.fixture(autouse=True)
def _isolated_departments_store(tmp_path, monkeypatch):
    store = tmp_path / "departments.json"
    monkeypatch.setattr("app.domain.departments.DEPARTMENTS_FILE", store)
    monkeypatch.setattr("app.domain.departments.invalidate_departments_cache", lambda: None)
    monkeypatch.setattr("app.domain.departments._departments_cache", None)
    yield


def test_create_list_update_delete_department():
    created = create_department("hr", label="Human Resources", description="HR team")
    assert created["id"] == "hr"
    assert department_exists("hr")

    rows = list_departments()
    assert len(rows) == 1
    assert rows[0]["label"] == "Human Resources"

    updated = update_department("hr", label="HR")
    assert updated["label"] == "HR"

    delete_department("hr")
    assert not department_exists("hr")


def test_create_duplicate_department_raises():
    create_department("it", label="IT")
    with pytest.raises(DepartmentError, match="already exists"):
        create_department("it", label="IT again")


def test_create_department_without_id_generates_id():
    from app.domain.departments import generate_department_id, validate_department_id

    created = create_department(label="Auto Dept")
    assert created["id"]
    validate_department_id(created["id"])
    assert created["id"].startswith("d")
    assert department_exists(created["id"])
    assert created["label"] == "Auto Dept"

    generated = generate_department_id()
    assert generated.startswith("d")
    validate_department_id(generated)
