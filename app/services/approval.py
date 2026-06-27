"""Approval service — wraps legacy approval queue helpers in api.routes."""

from __future__ import annotations

from typing import Any

_VALID_CHOICES = frozenset({"once", "session", "always", "deny"})


class ApprovalService:
    def get_pending(self, session_id: str) -> dict[str, Any]:
        from app.domain.routes import _approval_head_snapshot

        sid = str(session_id or "")
        pending, total = _approval_head_snapshot(sid)
        if pending:
            return {"pending": pending, "pending_count": total}
        return {"pending": None, "pending_count": 0}

    def respond(
        self,
        *,
        session_id: str,
        choice: str = "deny",
        approval_id: str = "",
    ) -> tuple[dict[str, Any], int]:
        sid = str(session_id or "")
        if not sid:
            return {"error": "session_id is required"}, 400
        if choice not in _VALID_CHOICES:
            return {"error": f"Invalid choice: {choice}"}, 400

        from app.domain.routes import _resolve_approval_legacy
        from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

        if runtime_adapter_enabled():
            adapter = LegacyJournalRuntimeAdapter(approval_delegate=_resolve_approval_legacy)
            ok = adapter.respond_approval(sid, approval_id, choice).accepted
        else:
            ok = _resolve_approval_legacy(sid, approval_id, choice)
        return {"ok": ok, "choice": choice}, 200

    def inject_test(
        self,
        *,
        session_id: str,
        pattern_key: str = "test_pattern",
        command: str = "rm -rf /tmp/test",
    ) -> tuple[dict[str, Any], int]:
        sid = str(session_id or "")
        if not sid:
            return {"error": "session_id required"}, 400

        from app.domain.routes import submit_pending

        submit_pending(
            sid,
            {
                "command": command,
                "pattern_key": pattern_key,
                "pattern_keys": [pattern_key],
                "description": "test pattern",
            },
        )
        return {"ok": True, "session_id": sid}, 200

    def get_clarify_pending(self, session_id: str) -> dict[str, Any]:
        from app.domain.clarify import get_pending as get_clarify_pending

        sid = str(session_id or "")
        pending = get_clarify_pending(sid)
        if pending:
            return {"pending": pending}
        return {"pending": None}

    def clarify_respond(
        self,
        *,
        session_id: str,
        response: str | None = None,
        answer: str | None = None,
        choice: str | None = None,
        clarify_id: str = "",
    ) -> tuple[dict[str, Any], int]:
        sid = str(session_id or "")
        if not sid:
            return {"error": "session_id is required"}, 400
        resolved = response
        if resolved is None:
            resolved = answer
        if resolved is None:
            resolved = choice
        text = str(resolved or "").strip()
        if not text:
            return {"error": "response is required"}, 400

        from app.domain.routes import _resolve_clarify_legacy
        from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

        cid = str(clarify_id or "")
        if runtime_adapter_enabled():
            adapter = LegacyJournalRuntimeAdapter(clarify_delegate=_resolve_clarify_legacy)
            ok = adapter.respond_clarify(sid, cid, text).accepted
        else:
            ok = _resolve_clarify_legacy(sid, cid, text)
        if not ok:
            return {
                "ok": False,
                "error": (
                    "Clarification prompt expired or not found. "
                    "The agent may have already proceeded."
                ),
                "stale": True,
            }, 409
        return {"ok": True, "response": text}, 200

    def inject_clarify_test(
        self,
        *,
        session_id: str,
        question: str = "Which option?",
        choices: list[str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        sid = str(session_id or "")
        if not sid:
            return {"error": "session_id required"}, 400

        from app.domain.clarify import submit_pending as submit_clarify_pending

        submit_clarify_pending(
            sid,
            {
                "question": question,
                "choices_offered": choices or [],
                "session_id": sid,
                "kind": "clarify",
            },
        )
        return {"ok": True, "session_id": sid}, 200
