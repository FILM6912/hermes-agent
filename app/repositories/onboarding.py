"""Onboarding repository — wraps api.onboarding and api.oauth."""
from __future__ import annotations
from typing import Any

class OnboardingRepository:
    def get_status(self) -> dict[str, Any]:
        from app.domain.onboarding import get_onboarding_status
        return get_onboarding_status()

    def apply_setup(self, body: dict[str, Any]) -> dict[str, Any]:
        from app.domain.onboarding import apply_onboarding_setup
        return apply_onboarding_setup(body)

    def complete(self) -> dict[str, Any]:
        from app.domain.onboarding import complete_onboarding
        return complete_onboarding()

    def probe(self, provider: str, base_url: str, api_key: str | None) -> dict[str, Any]:
        from app.domain.onboarding import probe_provider_endpoint
        return probe_provider_endpoint(provider, base_url, api_key)

    def oauth_start(self, body: dict[str, Any]) -> dict[str, Any]:
        from app.domain.oauth import start_onboarding_oauth_flow
        return start_onboarding_oauth_flow(body)

    def oauth_poll(self, flow_id: str) -> dict[str, Any]:
        from app.domain.oauth import poll_onboarding_oauth_flow
        return poll_onboarding_oauth_flow(flow_id)

    def oauth_cancel(self, body: dict[str, Any]) -> dict[str, Any]:
        from app.domain.oauth import cancel_onboarding_oauth_flow
        return cancel_onboarding_oauth_flow(body)
