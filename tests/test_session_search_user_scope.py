"""Tests for per-user session_search scoping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from app.domain.session_search_scope import (
    UserScopedSessionDB,
    normalize_session_owner_id,
    owned_webui_session_ids_for_user,
    session_row_visible_to_user,
    session_search_scoping_enabled,
    stamp_session_owner,
    webui_session_row_visible,
    wrap_session_db_for_access,
)
from app.domain.users import UserAccess


def test_session_search_scoping_enabled_for_multi_user_account():
    access = UserAccess(
        multi_user_enabled=True,
        user_id="film@example.com",
        role="user",
        profile_name="film",
    )
    assert session_search_scoping_enabled(access) is True
    assert normalize_session_owner_id(access) == "film@example.com"


def test_session_search_scoping_disabled_for_legacy_mode():
    access = UserAccess(multi_user_enabled=False)
    assert session_search_scoping_enabled(access) is False
    assert wrap_session_db_for_access(object(), access) is not None


def test_session_row_visible_prefers_state_db_user_id():
    owned = frozenset({"s1"})
    assert session_row_visible_to_user(
        {"id": "s1", "user_id": "alice", "source": "webui"},
        user_id="alice",
        owned_webui_ids=owned,
    )
    assert not session_row_visible_to_user(
        {"id": "s1", "user_id": "bob", "source": "webui"},
        user_id="alice",
        owned_webui_ids=owned,
    )


def test_session_row_visible_allows_owned_webui_without_state_user_id():
    owned = frozenset({"s-webui"})
    assert session_row_visible_to_user(
        {"id": "s-webui", "source": "webui"},
        user_id="alice",
        owned_webui_ids=owned,
    )
    assert not session_row_visible_to_user(
        {"id": "s-other", "source": "webui"},
        user_id="alice",
        owned_webui_ids=owned,
    )


def test_user_scoped_session_db_filters_search_messages():
    inner = mock.Mock()
    inner.search_messages.return_value = [
        {"session_id": "owned", "source": "webui"},
        {"session_id": "foreign", "source": "webui"},
    ]
    inner.get_session.side_effect = lambda sid: {
        "id": sid,
        "source": "webui",
        "user_id": "alice" if sid == "owned" else "bob",
    }

    scoped = UserScopedSessionDB(
        inner,
        user_id="alice",
        owned_webui_ids=frozenset(),
    )
    rows = scoped.search_messages(query="hello")
    assert [row["session_id"] for row in rows] == ["owned"]


def test_stamp_session_owner_sets_metadata_once():
    session = SimpleNamespace(owner_user_id=None)
    access = UserAccess(
        multi_user_enabled=True,
        user_id="film@example.com",
        role="user",
        profile_name="film",
    )
    assert stamp_session_owner(session, access) is True
    assert session.owner_user_id == "film@example.com"
    assert stamp_session_owner(session, access) is False


def test_webui_session_row_visible_matches_owner_user_id():
    access = UserAccess(
        multi_user_enabled=True,
        user_id="film@example.com",
        role="user",
        profile_name="film",
    )
    assert webui_session_row_visible({"owner_user_id": "film@example.com"}, access)
    assert not webui_session_row_visible({"owner_user_id": "other@example.com"}, access)


def test_owned_webui_session_ids_for_user(monkeypatch):
    monkeypatch.setattr(
        "app.domain.models.all_sessions",
        lambda: [
            {"session_id": "a", "owner_user_id": "alice@example.com", "profile": "alice"},
            {"session_id": "b", "owner_user_id": "bob@example.com", "profile": "bob"},
            {"session_id": "legacy", "profile": "alice"},
        ],
    )
    ids = owned_webui_session_ids_for_user("alice@example.com", profile="alice")
    assert ids == frozenset({"a"})
