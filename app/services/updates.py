"""Updates service — thin layer over UpdatesRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.updates import UpdatesRepository


class UpdatesService:
    def __init__(self, repository: UpdatesRepository | None = None) -> None:
        self._repo = repository or UpdatesRepository()

    def check_for_updates(
        self,
        *,
        force: bool = False,
        simulate: bool = False,
        client_host: str = "127.0.0.1",
    ) -> dict[str, Any]:
        return self._repo.check_for_updates(
            force=force,
            simulate=simulate,
            client_host=client_host,
        )

    def summarize_updates(
        self,
        updates: dict[str, Any],
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        return self._repo.summarize_updates(updates, target=target)

    def apply_update(self, target: str) -> tuple[dict[str, Any], int | None]:
        target_value = str(target or "").strip()
        if target_value not in ("webui", "agent"):
            return {"error": 'target must be "webui" or "agent"'}, 400
        return self._repo.apply_update(target_value), None

    def apply_force_update(self, target: str) -> tuple[dict[str, Any], int | None]:
        target_value = str(target or "").strip()
        if target_value not in ("webui", "agent"):
            return {"error": 'target must be "webui" or "agent"'}, 400
        return self._repo.apply_force_update(target_value), None
