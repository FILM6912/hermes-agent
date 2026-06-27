"""Settings service — thin layer over SettingsRepository and api.config auth."""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from app.repositories.settings import SettingsRepository


class SettingsService:
    def __init__(self, repository: SettingsRepository | None = None) -> None:
        self._repo = repository or SettingsRepository()

    def get_public_settings(self, request: Request | None = None) -> dict:
        settings = dict(self._repo.load_settings())
        settings.pop("password_hash", None)
        settings["password_env_var"] = bool(
            os.getenv("HERMES_WEBUI_PASSWORD", "").strip()
        )
        if request is not None:
            try:
                from app.domain.users import resolve_request_user_access
                from app.domain.workspace import normalize_client_default_workspace

                normalize_client_default_workspace(
                    settings,
                    resolve_request_user_access(request),
                )
            except Exception:
                pass
        try:
            from app.domain.updates import AGENT_VERSION, WEBUI_VERSION

            settings["webui_version"] = WEBUI_VERSION
            settings["agent_version"] = AGENT_VERSION
        except Exception:
            pass
        return settings

    def save_settings(
        self,
        body: dict[str, Any],
        *,
        current_cookie: str | None = None,
    ) -> tuple[dict, str | None, int | None]:
        """Persist settings; return (payload, optional_auth_cookie, optional_http_status)."""
        from app.domain.auth import (
            create_session,
            is_auth_enabled,
            verify_session,
        )
        from app.domain.passkeys import clear_credentials, registered_credentials

        payload = dict(body)
        if "bot_name" in payload:
            payload["bot_name"] = (str(payload["bot_name"]) or "").strip() or "Hermes"

        auth_enabled_before = is_auth_enabled()
        logged_in_before = bool(current_cookie and verify_session(current_cookie))
        requested_password = bool(
            isinstance(payload.get("_set_password"), str)
            and payload.get("_set_password", "").strip()
        )
        requested_passwordless = bool(payload.pop("_passwordless", False))
        requested_clear_password = bool(
            payload.get("_clear_password") or requested_passwordless
        )
        if requested_passwordless:
            payload["_clear_password"] = True

        if requested_password or requested_clear_password:
            if os.getenv("HERMES_WEBUI_PASSWORD", "").strip():
                return (
                    {
                        "detail": (
                            "HERMES_WEBUI_PASSWORD env var is set — it overrides the "
                            "settings password. Unset the env var and restart the server "
                            "before changing the password here."
                        )
                    },
                    None,
                    409,
                )
        if requested_passwordless:
            from app.domain.auth import _passkey_feature_flag_enabled

            if not _passkey_feature_flag_enabled():
                return (
                    {
                        "detail": (
                            "Passkey support is disabled. Enable HERMES_WEBUI_PASSKEY "
                            "before going passwordless."
                        )
                    },
                    None,
                    409,
                )
            if not registered_credentials():
                return (
                    {
                        "detail": "Register a passkey before going passwordless.",
                    },
                    None,
                    409,
                )
        elif requested_clear_password:
            clear_credentials()

        saved = dict(self._repo.save_settings(payload))
        saved.pop("password_hash", None)

        auth_enabled_after = is_auth_enabled()
        auth_just_enabled = bool(
            requested_password and auth_enabled_after and not auth_enabled_before
        )
        logged_in_after = logged_in_before
        new_cookie: str | None = None

        if auth_just_enabled and not logged_in_before:
            new_cookie = create_session()
            logged_in_after = True

        saved["auth_enabled"] = auth_enabled_after
        saved["logged_in"] = logged_in_after
        saved["auth_just_enabled"] = auth_just_enabled
        return saved, new_cookie, None
