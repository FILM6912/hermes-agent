"""Profile service — thin layer over ProfileRepository and api.profiles."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.domain import profiles as profiles_api
from app.domain.profiles import (
    active_profile_for_user,
    ensure_profile_create_allowed,
    ensure_profile_list_allowed,
    ensure_profile_management_allowed,
    ensure_profile_switch_allowed,
    filter_profiles_for_user,
)

from app.repositories.profiles import ProfileRepository

if TYPE_CHECKING:
    from app.core.security import CurrentUser


class ProfileService:
    def __init__(self, repository: ProfileRepository | None = None) -> None:
        self._repo = repository or ProfileRepository()

    def get_active_profile_name(self) -> str:
        return self._repo.get_active_profile_name()

    def get_active_hermes_home(self) -> Path:
        return self._repo.get_active_hermes_home()

    def get_hermes_home_for_profile(self, name: str) -> Path:
        return self._repo.get_hermes_home_for_profile(name)

    def list_profiles(self, user: "CurrentUser | None" = None) -> list:
        ensure_profile_list_allowed(user)
        return filter_profiles_for_user(self._repo.list_profiles(), user)

    def get_active_profile_for_user(self, user: "CurrentUser | None" = None) -> str:
        return active_profile_for_user(self.get_active_profile_name(), user)

    def create_profile(
        self,
        name: str,
        *,
        clone_from: str | None = None,
        clone_config: bool | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        model_provider: str | None = None,
        user: "CurrentUser | None" = None,
    ) -> dict:
        ensure_profile_create_allowed(user)
        return profiles_api.create_profile_api(
            name,
            clone_from=clone_from,
            clone_config=clone_config,
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            model_provider=model_provider,
        )

    def delete_profile(self, name: str, *, user: "CurrentUser | None" = None) -> dict:
        ensure_profile_management_allowed(user)
        profiles_api._validate_profile_name(name)
        return profiles_api.delete_profile_api(name)

    def update_profile_model(
        self,
        name: str,
        *,
        default_model: str | None = None,
        model_provider: str | None = None,
        update_default: bool = True,
        update_provider: bool = True,
        user: "CurrentUser | None" = None,
    ) -> dict:
        ensure_profile_management_allowed(user)
        return profiles_api.update_profile_model_api(
            name,
            default_model=default_model,
            model_provider=model_provider,
            update_default=update_default,
            update_provider=update_provider,
        )

    def sync_profile_from_default(
        self,
        name: str,
        *,
        user: "CurrentUser | None" = None,
    ) -> dict:
        ensure_profile_management_allowed(user)
        return sync_profile_from_default_api(name)

    def sync_all_profiles_from_default(self, *, user: "CurrentUser | None" = None) -> dict:
        ensure_profile_management_allowed(user)
        return sync_all_profiles_from_default_api()

    def switch_profile_client(
        self,
        name: str,
        *,
        user: "CurrentUser | None" = None,
    ) -> dict:
        """Per-client profile switch (cookie + thread-local, not process-wide)."""
        from app.domain.config import invalidate_models_cache_after_profile_switch
        from app.domain.profiles import (
            _profiles_match,
            _validate_profile_name,
            get_active_profile_name,
            set_request_profile,
            switch_profile,
        )

        ensure_profile_switch_allowed(name, user)

        if name != "default":
            _validate_profile_name(name)
        same_profile = _profiles_match(get_active_profile_name(), name)
        result = switch_profile(name, process_wide=False)
        if not same_profile:
            set_request_profile(name)
            invalidate_models_cache_after_profile_switch()
        return result

    # Re-export legacy helpers until dedicated service logic lands.
    switch_profile = staticmethod(profiles_api.switch_profile)
    init_profile_state = staticmethod(profiles_api.init_profile_state)
    create_profile_api = staticmethod(profiles_api.create_profile_api)
    delete_profile_api = staticmethod(profiles_api.delete_profile_api)
    list_profiles_api = staticmethod(profiles_api.list_profiles_api)


def sync_profile_from_default_api(name: str) -> dict:
    """Delegate to api.profiles.sync_profile_from_default_api."""
    return profiles_api.sync_profile_from_default_api(name)


def sync_all_profiles_from_default_api() -> dict:
    """Delegate to api.profiles.sync_all_profiles_from_default_api."""
    return profiles_api.sync_all_profiles_from_default_api()
