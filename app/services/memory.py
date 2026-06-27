"""Memory service — thin layer over MemoryRepository."""

from __future__ import annotations

from typing import Any

from app.repositories.memory import MemoryRepository


class MemoryService:
    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self._repo = repository or MemoryRepository()

    def read_memory(self) -> dict[str, Any]:
        return self._repo.read_memory()

    def write_memory(
        self,
        *,
        section: str | None,
        content: str | None,
    ) -> tuple[dict[str, Any], int | None]:
        from app.domain.helpers import require

        body = {"section": section, "content": content}
        try:
            require(body, "section", "content")
        except ValueError as exc:
            return {"error": str(exc)}, 400
        return self._repo.write_memory(str(section), str(content))
