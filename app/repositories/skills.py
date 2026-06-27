"""Skills repository — wraps api.routes skill mutation handlers."""

from __future__ import annotations

import json
from typing import Any, Callable

from starlette.responses import Response

from app.core.legacy_handler import run_legacy_dispatch_sync


def _skills_legacy_path(subpath: str) -> str:
    normalized = subpath.strip("/")
    return f"/api/skills/{normalized}" if normalized else "/api/skills"


class SkillsRepository:
    def run_post(
        self,
        *,
        subpath: str,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
        dispatch: Callable[..., bool | None],
    ) -> Response:
        return run_legacy_dispatch_sync(
            method="POST",
            path=_skills_legacy_path(subpath),
            headers=headers,
            body=json.dumps(body).encode("utf-8"),
            dispatch=dispatch,
        )
