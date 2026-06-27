"""Audit actor resolution for WebUI storage writes."""

from __future__ import annotations

from app.domain.users import UserAccess
from app.domain.workspace import clear_request_user_access, set_request_user_access
from app.storage.audit import actor_or_system, current_actor_email


def test_current_actor_email_prefers_request_context_over_fallback():
    token = set_request_user_access(
        UserAccess(
            multi_user_enabled=True,
            user_id="admin@aitech.co.th",
            username="admin@aitech.co.th",
            role="admin",
        )
    )
    try:
        assert (
            current_actor_email(fallback="user@aitech.co.th")
            == "admin@aitech.co.th"
        )
        assert (
            actor_or_system(fallback="user@aitech.co.th") == "admin@aitech.co.th"
        )
    finally:
        clear_request_user_access(token)


def test_current_actor_email_uses_fallback_when_no_request_context():
    assert current_actor_email(fallback="user@aitech.co.th") == "user@aitech.co.th"


def test_actor_or_system_defaults_to_system_without_context_or_fallback():
    assert actor_or_system() == "system"
