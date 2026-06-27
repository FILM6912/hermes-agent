"""Terminal control service — wraps api.terminal lifecycle helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.helpers import _sanitize_error, require


class TerminalService:
    def _session_and_workspace(self, session_id: str) -> tuple[str, Path]:
        from app.domain.models import get_session
        from app.domain.workspace import resolve_trusted_workspace

        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        try:
            session = get_session(sid)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        workspace = resolve_trusted_workspace(getattr(session, "workspace", "") or "")
        return sid, workspace

    def start(
        self,
        *,
        session_id: str,
        rows: int = 24,
        cols: int = 80,
        restart: bool = False,
    ) -> tuple[dict[str, Any], int]:
        try:
            sid, workspace = self._session_and_workspace(session_id)
            from app.domain.terminal import start_terminal

            term = start_terminal(
                sid,
                workspace,
                rows=int(rows or 24),
                cols=int(cols or 80),
                restart=bool(restart),
            )
            return {
                "ok": True,
                "session_id": sid,
                "workspace": term.workspace,
                "running": term.is_alive(),
            }, 200
        except KeyError as exc:
            return {"error": str(exc)}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            return {"error": _sanitize_error(exc)}, 500

    def write_input(self, *, session_id: str, data: str = "") -> tuple[dict[str, Any], int]:
        try:
            require({"session_id": session_id}, "session_id")
            payload = str(data or "")
            if len(payload) > 8192:
                return {"error": "input too large"}, 413
            from app.domain.terminal import write_terminal

            write_terminal(session_id, payload)
            return {"ok": True}, 200
        except KeyError as exc:
            return {"error": str(exc)}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            return {"error": _sanitize_error(exc)}, 500

    def resize(
        self,
        *,
        session_id: str,
        rows: int = 24,
        cols: int = 80,
    ) -> tuple[dict[str, Any], int]:
        try:
            require({"session_id": session_id}, "session_id")
            from app.domain.terminal import resize_terminal

            resize_terminal(
                session_id,
                rows=int(rows or 24),
                cols=int(cols or 80),
            )
            return {"ok": True}, 200
        except KeyError as exc:
            return {"error": str(exc)}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except Exception as exc:
            return {"error": _sanitize_error(exc)}, 500

    def close(self, *, session_id: str) -> tuple[dict[str, Any], int]:
        try:
            require({"session_id": session_id}, "session_id")
            from app.domain.terminal import close_terminal

            closed = close_terminal(session_id)
            return {"ok": True, "closed": closed}, 200
        except ValueError as exc:
            return {"error": str(exc)}, 400
