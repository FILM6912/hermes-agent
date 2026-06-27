"""Provider service — thin layer over ProvidersRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.providers import ProvidersRepository


class ProviderService:
    def __init__(self, repository: ProvidersRepository | None = None) -> None:
        self._repo = repository or ProvidersRepository()

    def list_providers(self) -> dict[str, Any]:
        return self._repo.list_providers()

    def get_provider_quota(
        self,
        provider_id: str | None = None,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        return self._repo.get_provider_quota(provider_id, refresh=refresh)

    def set_provider_key(
        self,
        provider_id: str | None,
        api_key: str | None,
    ) -> tuple[dict[str, Any], int | None]:
        provider = (provider_id or "").strip().lower()
        if not provider:
            return {"error": "provider is required"}, 400
        key = None if api_key is None else str(api_key).strip() or None
        result = self._repo.set_provider_key(provider, key)
        if not result.get("ok"):
            return {"error": result.get("error", "Unknown error")}, 400
        return result, None

    def remove_provider_key(self, provider_id: str | None) -> tuple[dict[str, Any], int | None]:
        provider = (provider_id or "").strip().lower()
        if not provider:
            return {"error": "provider is required"}, 400
        result = self._repo.remove_provider_key(provider)
        if not result.get("ok"):
            return {"error": result.get("error", "Unknown error")}, 400
        return result, None

    def get_cost_history(
        self,
        provider_id: str | None = None,
        *,
        days: str | int | None = 7,
    ) -> dict[str, Any]:
        provider = (provider_id or "").strip() or None
        days_raw = str(days or "7").strip()
        try:
            parsed_days = max(1, min(int(days_raw), 365))
        except (ValueError, TypeError):
            parsed_days = 7
        return self._repo.get_cost_history(provider, days=parsed_days)
