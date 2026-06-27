"""Slash-command service — list and execute plugin commands."""

from __future__ import annotations

from typing import Any


class CommandsService:
    def list_commands(self) -> dict[str, Any]:
        from app.domain.commands import list_commands

        return {"commands": list_commands()}

    def exec_command(self, command: str) -> tuple[dict[str, Any], int]:
        from app.domain.commands import execute_plugin_command
        from app.domain.routes import _sanitize_error

        normalized = str(command or "").strip()
        if not normalized:
            return {"error": "command is required"}, 400
        try:
            return {"output": execute_plugin_command(normalized)}, 200
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except KeyError:
            return {"error": "Plugin command not found"}, 404
        except RuntimeError as exc:
            return {"error": _sanitize_error(exc)}, 500
