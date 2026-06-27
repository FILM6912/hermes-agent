"""Provider catalog repository — wraps api.providers."""

from __future__ import annotations

from typing import Any


class ProvidersRepository:
    def list_providers(self) -> dict[str, Any]:
        from app.domain.providers import get_providers

        return get_providers()

    def get_provider_quota(
        self,
        provider_id: str | None = None,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        from app.domain.providers import get_provider_quota

        return get_provider_quota(provider_id, refresh=refresh)

    def set_provider_key(self, provider_id: str, api_key: str | None) -> dict[str, Any]:
        from app.domain.providers import set_provider_key

        return set_provider_key(provider_id, api_key)

    def remove_provider_key(self, provider_id: str) -> dict[str, Any]:
        from app.domain.providers import remove_provider_key

        return remove_provider_key(provider_id)

    def get_cost_history(
        self,
        provider_id: str | None = None,
        *,
        days: int = 7,
    ) -> dict[str, Any]:
        from app.domain.providers import get_provider_cost_history

        return get_provider_cost_history(provider_id, days)
