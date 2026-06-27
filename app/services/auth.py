"""Auth service — thin layer over AuthRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.auth import AuthRepository


class AuthService:
    def __init__(self, repository: AuthRepository | None = None) -> None:
        self._repo = repository or AuthRepository()

    def get_status(self, cookie_value: str | None = None) -> dict[str, Any]:
        return self._repo.get_status(cookie_value)

    def login(
        self,
        password: str,
        *,
        client_ip: str,
        email: str | None = None,
    ) -> tuple[dict[str, Any], int, str | None]:
        return self._repo.login(password, client_ip=client_ip, email=email)

    def logout(self, cookie_value: str | None) -> dict[str, Any]:
        return self._repo.logout(cookie_value)

    def passkey_authentication_options(
        self,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        return self._repo.passkey_authentication_options(headers)

    def passkey_login(
        self,
        body: dict[str, Any],
        *,
        client_ip: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int, str | None]:
        return self._repo.passkey_login(body, client_ip=client_ip, headers=headers)

    def passkey_registration_options(
        self,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        return self._repo.passkey_registration_options(headers)

    def passkey_register(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        return self._repo.passkey_register(body, headers)

    def passkey_delete(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        return self._repo.passkey_delete(body)

    def list_passkeys(self) -> dict[str, Any]:
        return self._repo.list_passkeys()
