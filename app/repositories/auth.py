"""Auth repository — wraps api.auth and api.passkeys helpers."""

from __future__ import annotations

from typing import Any


class _HeaderHandler:
    """Minimal handler adapter for passkey rp_context helpers."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class AuthRepository:
    def get_status(self, cookie_value: str | None = None) -> dict[str, Any]:
        from app.domain.auth import get_auth_status_payload

        return get_auth_status_payload(cookie_value)

    def login(
        self,
        password: str,
        *,
        client_ip: str,
        email: str | None = None,
    ) -> tuple[dict[str, Any], int, str | None]:
        from app.domain.auth import (
            _check_login_rate,
            _record_login_attempt,
            access_token_response_field,
            create_session,
            csrf_token_response_field,
            is_auth_enabled,
            verify_password,
        )
        from app.domain.users import is_multi_user_enabled, users_file_exists, verify_user_password
        from app.storage.repositories.sessions import ensure_sessions_migrated

        ensure_sessions_migrated()
        if not is_auth_enabled():
            return {"ok": True, "message": "Auth not enabled"}, 200, None
        if not _check_login_rate(client_ip):
            return (
                {"error": "Too many attempts. Try again in a minute."},
                429,
                None,
            )

        if is_multi_user_enabled() and users_file_exists():
            if not email:
                _record_login_attempt(client_ip)
                return {"error": "Email required"}, 401, None
            user = verify_user_password(email, password)
            if user is None:
                _record_login_attempt(client_ip)
                return {"error": "Invalid email or password"}, 401, None
            cookie = create_session(user_id=user.email, role=user.role)
            return (
                {
                    "ok": True,
                    "user_id": user.email,
                    "email": user.email,
                    "role": user.role,
                    "profile_name": user.profile_name,
                    "profile_names": list(user.assigned_profile_names()),
                    "display_name": user.display_name,
                    "department": user.department,
                    "position": user.position,
                    **csrf_token_response_field(cookie),
                    **access_token_response_field(cookie),
                },
                200,
                cookie,
            )

        if not verify_password(password):
            _record_login_attempt(client_ip)
            return {"error": "Invalid password"}, 401, None
        cookie = create_session()
        return (
            {
                "ok": True,
                "user_id": "legacy",
                "role": "admin",
                **csrf_token_response_field(cookie),
                **access_token_response_field(cookie),
            },
            200,
            cookie,
        )

    def logout(self, cookie_value: str | None) -> dict[str, Any]:
        from app.domain.auth import invalidate_session
        from app.storage.repositories.sessions import ensure_sessions_migrated

        ensure_sessions_migrated()
        if cookie_value:
            invalidate_session(cookie_value)
        return {"ok": True}

    def passkey_authentication_options(
        self,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        from app.domain.auth import _passkey_feature_flag_enabled, is_auth_enabled
        from app.domain.passkeys import PasskeyError, authentication_options

        if not _passkey_feature_flag_enabled():
            return (
                {
                    "error": (
                        "Passkey support is disabled. Set HERMES_WEBUI_PASSKEY=1 or "
                        "webui_passkey_enabled: true to enable."
                    )
                },
                404,
            )
        if not is_auth_enabled():
            return {"error": "Auth not enabled"}, 400
        try:
            return {"ok": True, "publicKey": authentication_options(_HeaderHandler(headers))}, 200
        except PasskeyError as exc:
            return {"error": str(exc)}, 400

    def passkey_login(
        self,
        body: dict[str, Any],
        *,
        client_ip: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int, str | None]:
        from app.domain.auth import (
            _check_login_rate,
            _passkey_feature_flag_enabled,
            _record_login_attempt,
            access_token_response_field,
            create_session,
            csrf_token_response_field,
            is_auth_enabled,
        )
        from app.domain.passkeys import PasskeyError, finish_login

        if not _passkey_feature_flag_enabled():
            return {"error": "Passkey support is disabled."}, 404, None
        if not is_auth_enabled():
            return {"error": "Auth not enabled"}, 400, None
        if not _check_login_rate(client_ip):
            return {"error": "Too many attempts. Try again in a minute."}, 429, None
        try:
            finish_login(body, _HeaderHandler(headers))
        except PasskeyError as exc:
            _record_login_attempt(client_ip)
            return {"error": str(exc)}, 401, None
        cookie = create_session()
        return (
            {
                "ok": True,
                "user_id": "legacy",
                "role": "admin",
                **csrf_token_response_field(cookie),
                **access_token_response_field(cookie),
            },
            200,
            cookie,
        )

    def passkey_registration_options(self, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import registration_options

        if not _passkey_feature_flag_enabled():
            return {"error": "Passkey support is disabled."}, 404
        return {"ok": True, "publicKey": registration_options(_HeaderHandler(headers))}, 200

    def passkey_register(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import PasskeyError, finish_registration, registered_credentials

        if not _passkey_feature_flag_enabled():
            return {"error": "Passkey support is disabled."}, 404
        try:
            result = finish_registration(body, _HeaderHandler(headers))
            result["credentials"] = registered_credentials()
            return result, 200
        except PasskeyError as exc:
            return {"error": str(exc)}, 400

    def passkey_delete(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        from app.domain.auth import _passkey_feature_flag_enabled, get_password_hash
        from app.domain.passkeys import PasskeyError, delete_credential, registered_credentials

        if not _passkey_feature_flag_enabled():
            return {"error": "Passkey support is disabled."}, 404
        try:
            credential_id = str(body.get("id") or "")
            creds = registered_credentials()
            if (
                get_password_hash() is None
                and len(creds) <= 1
                and any(c.get("id") == credential_id for c in creds)
            ):
                return (
                    {
                        "error": (
                            "Set a password or disable auth before removing the last passkey."
                        )
                    },
                    409,
                )
            return delete_credential(credential_id), 200
        except PasskeyError as exc:
            return {"error": str(exc)}, 404

    def list_passkeys(self) -> dict[str, Any]:
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import registered_credentials

        if not _passkey_feature_flag_enabled():
            return {"credentials": [], "disabled": True}
        return {"credentials": registered_credentials()}
