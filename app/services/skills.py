"""Skills service — native FastAPI cutover for skill mutations."""

from __future__ import annotations

from typing import Any

from starlette.responses import Response

from app.repositories.skills import SkillsRepository


class SkillsService:
    def __init__(self, repository: SkillsRepository | None = None) -> None:
        self._repo = repository or SkillsRepository()

    def save(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_skill_save

            _handle_skill_save(handler, body)

        return self._repo.run_post(
            subpath="save",
            body=body,
            headers=headers,
            dispatch=_dispatch,
        )

    def delete(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_skill_delete

            _handle_skill_delete(handler, body)

        return self._repo.run_post(
            subpath="delete",
            body=body,
            headers=headers,
            dispatch=_dispatch,
        )

    def toggle(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_skill_toggle

            _handle_skill_toggle(handler, body)

        return self._repo.run_post(
            subpath="toggle",
            body=body,
            headers=headers,
            dispatch=_dispatch,
        )

    def install(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> Response:
        def _dispatch(handler, parsed) -> None:
            from app.domain.routes import _handle_skill_install

            _handle_skill_install(handler, body)

        return self._repo.run_post(
            subpath="install",
            body=body,
            headers=headers,
            dispatch=_dispatch,
        )
