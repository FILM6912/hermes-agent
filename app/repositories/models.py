"""Model catalog repository — wraps api.config model helpers."""

from __future__ import annotations

from typing import Any


class ModelsRepository:
    def get_available_models(self) -> dict[str, Any]:
        from app.domain.config import get_available_models

        return get_available_models()

    def get_live_models(self, provider: str | None = None) -> tuple[int, dict[str, Any]]:
        from urllib.parse import urlencode

        from app.core.legacy_handler import run_legacy_dispatch_sync
        from app.domain.routes import _handle_live_models

        query = urlencode({"provider": provider}) if provider else ""
        path = f"/api/models/live?{query}" if query else "/api/models/live"

        def _dispatch(handler, parsed) -> None:
            _handle_live_models(handler, parsed)

        response = run_legacy_dispatch_sync(method="GET", path=path, dispatch=_dispatch)
        import json

        payload = json.loads(response.body or b"{}")
        return response.status_code, payload

    def get_auxiliary_models(self) -> dict[str, Any]:
        from app.domain.config import get_auxiliary_models

        return get_auxiliary_models()

    def get_reasoning_status(
        self,
        *,
        model_id: str | None = None,
        provider_id: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        from app.domain.config import get_reasoning_status

        return get_reasoning_status(
            model_id=model_id,
            provider_id=provider_id,
            base_url=base_url,
        )

    def set_reasoning_display(self, show: bool) -> dict[str, Any]:
        from app.domain.config import set_reasoning_display

        return set_reasoning_display(show)

    def set_reasoning_effort(self, effort: str) -> dict[str, Any]:
        from app.domain.config import set_reasoning_effort

        return set_reasoning_effort(effort)

    def set_default_model(self, model_id: str) -> dict[str, Any]:
        from app.domain.config import set_hermes_default_model

        return set_hermes_default_model(model_id)

    def set_auxiliary_model(
        self,
        task: str,
        provider: str | None = None,
        model: str | None = None,
        *,
        update_provider: bool = True,
        update_model: bool = True,
    ) -> dict[str, Any]:
        from app.domain.config import set_auxiliary_model

        return set_auxiliary_model(
            task,
            provider,
            model,
            update_provider=update_provider,
            update_model=update_model,
        )
