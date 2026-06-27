"""System/admin service — thin layer over SystemRepository."""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from app.repositories.system import SystemRepository


class SystemService:
    def __init__(self, repository: SystemRepository | None = None) -> None:
        self._repo = repository or SystemRepository()

    def get_system_health(self) -> dict[str, Any]:
        return self._repo.get_system_health()

    def get_agent_health(self) -> dict[str, Any]:
        return self._repo.get_agent_health()

    def get_plugins(self) -> dict[str, Any]:
        return self._repo.get_plugins()

    def get_wiki_status(self) -> dict[str, Any]:
        return self._repo.get_wiki_status()

    def get_gateway_status(self) -> dict[str, Any]:
        return self._repo.get_gateway_status()

    def get_logs(
        self,
        *,
        file_key: str | None = None,
        tail: str | None = None,
        profile: str | None = None,
        username: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int | None]:
        return self._repo.get_logs(
            file_key=file_key,
            tail=tail,
            profile=profile,
            username=username,
            headers=headers,
        )

    def get_insights(
        self,
        *,
        days: int = 30,
        profile: str | None = None,
        username: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._repo.get_insights(
            days=days,
            profile=profile,
            username=username,
            headers=headers,
        )

    def shutdown(self) -> dict[str, str]:
        return self._repo.shutdown()

    def admin_reload(self) -> dict[str, str]:
        return self._repo.admin_reload()

    def transcribe(self, *, headers: dict[str, str], body: bytes) -> Response:
        return self._repo.transcribe(headers=headers, body=body)

    def log_client_event(
        self,
        *,
        body: bytes,
        headers: dict[str, str],
        client_host: str,
        client_port: int = 0,
    ) -> tuple[dict[str, Any], int | None]:
        return self._repo.log_client_event(
            body=body,
            headers=headers,
            client_host=client_host,
            client_port=client_port,
        )
