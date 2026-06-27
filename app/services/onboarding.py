"""Onboarding service — status, setup, probe, and OAuth flows."""
from __future__ import annotations
from typing import Any
from app.core.onboarding_gate import (
    ONBOARDING_OAUTH_FORBIDDEN_MSG,
    ONBOARDING_PROBE_FORBIDDEN_MSG,
    ONBOARDING_SETUP_FORBIDDEN_MSG,
    onboarding_client_allowed,
)
from app.repositories.onboarding import OnboardingRepository

class OnboardingService:
    def __init__(self, repository: OnboardingRepository | None = None) -> None:
        self._repo = repository or OnboardingRepository()

    def get_status(self) -> dict[str, Any]:
        return self._repo.get_status()

    def complete(self) -> dict[str, Any]:
        return self._repo.complete()

    def apply_setup(self, body: dict[str, Any], *, client_host: str, x_forwarded_for: str = "", x_real_ip: str = "") -> tuple[dict[str, Any], int | None]:
        if not onboarding_client_allowed(client_host=client_host, x_forwarded_for=x_forwarded_for, x_real_ip=x_real_ip):
            return {"error": ONBOARDING_SETUP_FORBIDDEN_MSG}, 403
        try:
            return self._repo.apply_setup(body), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except RuntimeError as exc:
            return {"error": str(exc)}, 500

    def probe(self, body: dict[str, Any], *, client_host: str, x_forwarded_for: str = "", x_real_ip: str = "") -> tuple[dict[str, Any], int | None]:
        if not onboarding_client_allowed(client_host=client_host, x_forwarded_for=x_forwarded_for, x_real_ip=x_real_ip):
            return {"error": ONBOARDING_PROBE_FORBIDDEN_MSG}, 403
        provider = str(body.get("provider") or "").strip().lower()
        base_url = str(body.get("base_url") or "")
        api_key = str(body.get("api_key") or "").strip() or None
        try:
            return self._repo.probe(provider, base_url, api_key), None
        except Exception as exc:
            return {"error": f"probe failed: {exc}"}, 500

    def oauth_start(self, body: dict[str, Any], *, client_host: str, x_forwarded_for: str = "", x_real_ip: str = "") -> tuple[dict[str, Any], int | None]:
        if not onboarding_client_allowed(client_host=client_host, x_forwarded_for=x_forwarded_for, x_real_ip=x_real_ip):
            return {"error": ONBOARDING_OAUTH_FORBIDDEN_MSG}, 403
        try:
            return self._repo.oauth_start(body), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except RuntimeError as exc:
            return {"error": str(exc)}, 500

    def oauth_poll(self, flow_id: str) -> tuple[dict[str, Any], int | None]:
        try:
            return self._repo.oauth_poll(flow_id), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except KeyError as exc:
            return {"error": str(exc)}, 404

    def oauth_cancel(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            return self._repo.oauth_cancel(body), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
