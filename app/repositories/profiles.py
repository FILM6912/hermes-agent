"""Profile home resolution repository — wraps api.profiles."""

from __future__ import annotations

from pathlib import Path

from app.domain import profiles as profiles_api


class ProfileRepository:
    """Hermes profile directory resolution and listing."""

    def get_active_profile_name(self) -> str:
        return profiles_api.get_active_profile_name()

    def get_active_hermes_home(self) -> Path:
        return profiles_api.get_active_hermes_home()

    def get_hermes_home_for_profile(self, name: str) -> Path:
        return profiles_api.get_hermes_home_for_profile(name)

    def list_profiles(self) -> list:
        return profiles_api.list_profiles_api()

    def resolve_profile_home(self, name: str) -> Path:
        return profiles_api.get_hermes_home_for_profile(name)
