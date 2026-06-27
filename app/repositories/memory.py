"""Memory repository — reads and writes Hermes memory markdown files."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MemoryRepository:
    def _memory_paths(self) -> tuple[Path, Path, Path]:
        try:
            from app.domain.profiles import get_active_hermes_home

            home = get_active_hermes_home()
            mem_dir = home / "memories"
        except ImportError:
            home = Path.home() / ".hermes"
            mem_dir = home / "memories"
        return mem_dir / "MEMORY.md", mem_dir / "USER.md", home / "SOUL.md"

    def read_memory(self) -> dict[str, Any]:
        from app.domain.helpers import _redact_text
        from app.domain.routes import _external_notes_sources_enabled

        mem_file, user_file, soul_file = self._memory_paths()
        memory = (
            mem_file.read_text(encoding="utf-8", errors="replace")
            if mem_file.exists()
            else ""
        )
        user = (
            user_file.read_text(encoding="utf-8", errors="replace")
            if user_file.exists()
            else ""
        )
        soul = (
            soul_file.read_text(encoding="utf-8", errors="replace")
            if soul_file.exists()
            else ""
        )
        return {
            "memory": _redact_text(memory),
            "user": _redact_text(user),
            "soul": _redact_text(soul),
            "memory_path": str(mem_file),
            "user_path": str(user_file),
            "soul_path": str(soul_file),
            "memory_mtime": mem_file.stat().st_mtime if mem_file.exists() else None,
            "user_mtime": user_file.stat().st_mtime if user_file.exists() else None,
            "soul_mtime": soul_file.stat().st_mtime if soul_file.exists() else None,
            "external_notes_enabled": _external_notes_sources_enabled(),
        }

    def write_memory(self, section: str, content: str) -> tuple[dict[str, Any], int | None]:
        mem_file, user_file, soul_file = self._memory_paths()
        mem_dir = mem_file.parent
        mem_dir.mkdir(parents=True, exist_ok=True)
        if section == "memory":
            target = mem_file
        elif section == "user":
            target = user_file
        elif section == "soul":
            target = soul_file
        else:
            return (
                {"error": 'section must be "memory", "user", or "soul"'},
                400,
            )
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "section": section, "path": str(target)}, None
