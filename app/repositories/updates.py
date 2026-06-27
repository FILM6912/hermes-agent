"""Updates repository — wraps api.updates helpers."""

from __future__ import annotations

from typing import Any


class UpdatesRepository:
    def check_for_updates(
        self,
        *,
        force: bool = False,
        simulate: bool = False,
        client_host: str = "127.0.0.1",
    ) -> dict[str, Any]:
        from app.domain.updates import check_for_updates

        _ = simulate, client_host
        return check_for_updates(force=force)

    def summarize_updates(
        self,
        updates: dict[str, Any],
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        from app.domain.updates import summarize_update_payload

        return summarize_update_payload(updates, target=target)

    def apply_update(self, target: str) -> dict[str, Any]:
        from app.domain.updates import apply_update

        return apply_update(target)

    def apply_force_update(self, target: str) -> dict[str, Any]:
        from app.domain.updates import apply_force_update

        return apply_force_update(target)
