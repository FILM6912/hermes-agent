"""Model catalog service — thin layer over ModelsRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.models import ModelsRepository


class ModelService:
    def __init__(self, repository: ModelsRepository | None = None) -> None:
        self._repo = repository or ModelsRepository()

    def get_available_models(self) -> dict[str, Any]:
        return self._repo.get_available_models()

    def get_live_models(self, provider: str | None = None) -> tuple[int, dict[str, Any]]:
        return self._repo.get_live_models(provider=provider)

    def get_auxiliary_models(self) -> dict[str, Any]:
        return self._repo.get_auxiliary_models()

    def get_reasoning_status(
        self,
        *,
        model_id: str | None = None,
        provider_id: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        return self._repo.get_reasoning_status(
            model_id=model_id,
            provider_id=provider_id,
            base_url=base_url,
        )

    def set_reasoning(
        self,
        *,
        display: str | None = None,
        effort: str | None = None,
    ) -> tuple[dict[str, Any], int | None]:
        if display is not None:
            flag = str(display).strip().lower()
            if flag in ("show", "on", "true", "1"):
                return self._repo.set_reasoning_display(True), None
            if flag in ("hide", "off", "false", "0"):
                return self._repo.set_reasoning_display(False), None
            return {"error": f"display must be show|hide|on|off (got '{display}')"}, 400
        if effort is not None:
            try:
                return self._repo.set_reasoning_effort(effort), None
            except ValueError as exc:
                return {"error": str(exc)}, 400
            except RuntimeError as exc:
                return {"error": str(exc)}, 500
        return {"error": "reasoning: must supply 'display' or 'effort'"}, 400

    def set_default_model(self, model: str | None) -> tuple[dict[str, Any], int | None]:
        try:
            return self._repo.set_default_model(str(model or "")), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except RuntimeError as exc:
            return {"error": str(exc)}, 500

    def set_model(self, **patch: Any) -> tuple[dict[str, Any], int | None]:
        scope_value = str(patch.get("scope") or "").strip()
        if scope_value == "auxiliary":
            task = str(patch.get("task") or "").strip()
            try:
                return (
                    self._repo.set_auxiliary_model(
                        task,
                        provider=patch.get("provider"),
                        model=patch.get("model"),
                        update_provider="provider" in patch,
                        update_model="model" in patch,
                    ),
                    None,
                )
            except Exception as exc:
                return {"error": str(exc)}, 400
        if scope_value == "main":
            try:
                return self._repo.set_default_model(str(patch.get("model") or "").strip()), None
            except ValueError as exc:
                return {"error": str(exc)}, 400
        return {"error": f"unknown scope: {scope_value}"}, 400
