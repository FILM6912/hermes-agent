"""Users repository — wraps app.domain.users."""

from __future__ import annotations

from typing import Any

from app.domain import users as users_domain


class UsersRepository:
    def is_multi_user_mode(self) -> bool:
        return users_domain.is_multi_user_mode()

    def list_users(self) -> list[dict[str, Any]]:
        return users_domain.list_users()

    def get_user(self, email: str) -> dict[str, Any] | None:
        return users_domain.get_user_public(email)

    def create_user(
        self,
        email: str,
        *,
        password: str | None = None,
        password_hash: str | None = None,
        role: str = "user",
        profile_name: str | None = None,
        profile_names: list[str] | None = None,
        display_name: str | None = None,
        department: str | None = None,
        position: str | None = None,
    ) -> dict[str, Any]:
        return users_domain.create_user(
            email,
            password=password,
            password_hash=password_hash,
            role=role,
            profile_name=profile_name,
            profile_names=profile_names,
            display_name=display_name,
            department=department,
            position=position,
        )

    def update_user(
        self,
        email: str,
        *,
        new_email: str | None = None,
        role: str | None = None,
        profile_name: str | None = None,
        profile_names: list[str] | None = None,
        password: str | None = None,
        password_hash: str | None = None,
        display_name: str | None = None,
        department: str | None = None,
        position: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if new_email is not None:
            fields["new_email"] = new_email
        if role is not None:
            fields["role"] = role
        if profile_name is not None:
            fields["profile_name"] = profile_name
        if profile_names is not None:
            fields["profile_names"] = profile_names
        if password is not None:
            fields["password"] = password
        if password_hash is not None:
            fields["password_hash"] = password_hash
        if display_name is not None:
            fields["display_name"] = display_name
        if department is not None:
            fields["department"] = department
        if position is not None:
            fields["position"] = position
        if enabled is not None:
            fields["enabled"] = enabled
        return users_domain.update_user(email, **fields)

    def delete_user(self, email: str) -> None:
        users_domain.delete_user(email)

    def bootstrap_default_admin(self) -> dict[str, Any] | None:
        return users_domain.bootstrap_default_admin()

    def promote_install_to_multi_user(
        self,
        *,
        admin_email: str | None = None,
        admin_password: str | None = None,
        current_password: str | None = None,
    ) -> dict[str, Any]:
        return users_domain.promote_install_to_multi_user(
            admin_username=admin_email,
            admin_password=admin_password,
            current_password=current_password,
        )


UserRepository = UsersRepository

__all__ = ["UserRepository", "UsersRepository"]
