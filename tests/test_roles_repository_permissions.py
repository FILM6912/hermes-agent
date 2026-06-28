"""Regression tests for webui_roles permissions JSON map storage."""

from __future__ import annotations

import json

from app.domain.roles import (
    PERMISSION_CATALOG,
    coerce_permissions_map,
    permissions_from_enabled_list,
    permissions_map_has_any,
    permission_granted,
)
from app.storage.dialect import POSTGRES, SQLITE
from app.storage.repositories.roles import _permissions_for_write, _row_to_domain


def test_coerce_permissions_map_accepts_list_and_dict() -> None:
    assert coerce_permissions_map(["*"]) == {"*": True}
    assert permission_granted(coerce_permissions_map(["workspace:read"]), "workspace:read") is True
    assert coerce_permissions_map(
        {"users:manage": True, "profiles:manage": False},
    ) == {"users:manage": True, "profiles:manage": False}


def test_permissions_from_enabled_list_builds_full_map() -> None:
    mapped = permissions_from_enabled_list(["upload:file"])
    assert mapped["upload:file"] is True
    assert mapped["users:manage"] is False
    assert "*" not in mapped


def test_permissions_for_write_uses_json_object_on_postgres() -> None:
    value = _permissions_for_write(
        {"users:manage": True, "profiles:manage": False},
        POSTGRES,
    )
    assert json.loads(value) == {"users:manage": True, "profiles:manage": False}


def test_permissions_for_write_uses_json_text_on_sqlite() -> None:
    value = _permissions_for_write({"workspace:read": True}, SQLITE)
    assert json.loads(value) == {"workspace:read": True}


def test_row_to_domain_keeps_permissions_as_json_map() -> None:
    row = {
        "id": "admin",
        "label": "Administrator",
        "description": None,
        "permissions": {"*": True},
        "requires_profile": 0,
        "builtin": 1,
        "created_at": None,
        "updated_at": None,
        "created_by": "system",
        "updated_by": "system",
    }
    domain = _row_to_domain(row)
    assert domain["permissions"] == {"*": True}


def test_permissions_map_has_any() -> None:
    assert permissions_map_has_any({"users:manage": True}) is True
    assert permissions_map_has_any({"users:manage": False}) is False
    assert permissions_map_has_any({key: False for key in PERMISSION_CATALOG if key != "*"}) is False
