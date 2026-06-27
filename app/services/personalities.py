"""Personality catalog and per-session personality selection."""

from __future__ import annotations

from typing import Any


class PersonalitiesService:
    def list_personalities(self) -> dict[str, Any]:
        from app.domain.config import get_config, reload_config

        reload_config()
        cfg = get_config()
        agent_cfg = cfg.get("agent", {})
        raw_personalities = agent_cfg.get("personalities", {})
        personalities: list[dict[str, str]] = []
        if isinstance(raw_personalities, dict):
            for name, value in raw_personalities.items():
                desc = ""
                if isinstance(value, dict):
                    desc = str(value.get("description", "") or "")
                elif isinstance(value, str):
                    desc = value[:80] + ("..." if len(value) > 80 else "")
                personalities.append({"name": name, "description": desc})
        return {"personalities": personalities}

    def set_personality(
        self,
        *,
        session_id: str,
        name: str,
    ) -> tuple[dict[str, Any], int]:
        from app.domain.config import _get_session_agent_lock, get_config, reload_config
        from app.domain.helpers import require
        from app.domain.models import get_session
        from app.domain.routes import _ensure_full_session_before_mutation

        body = {"session_id": session_id, "name": name}
        try:
            require(body, "session_id")
        except ValueError as exc:
            return {"error": str(exc)}, 400
        if "name" not in body:
            return {"error": "Missing required field: name"}, 400

        sid = body["session_id"]
        personality_name = str(body["name"]).strip()
        try:
            session = get_session(sid)
            session = _ensure_full_session_before_mutation(sid, session)
        except KeyError:
            return {"error": "Session not found"}, 404

        prompt = ""
        if personality_name:
            reload_config()
            cfg = get_config()
            agent_cfg = cfg.get("agent", {})
            raw_personalities = agent_cfg.get("personalities", {})
            if (
                not isinstance(raw_personalities, dict)
                or personality_name not in raw_personalities
            ):
                return {
                    "error": f'Personality "{personality_name}" not found in config.yaml',
                }, 404
            value = raw_personalities[personality_name]
            if isinstance(value, dict):
                parts = [value.get("system_prompt", "") or value.get("prompt", "")]
                if value.get("tone"):
                    parts.append(f"Tone: {value['tone']}")
                if value.get("style"):
                    parts.append(f"Style: {value['style']}")
                prompt = "\n".join(part for part in parts if part)
            else:
                prompt = str(value)

        with _get_session_agent_lock(sid):
            session.personality = personality_name if personality_name else None
            session.save()
        return {
            "ok": True,
            "personality": session.personality,
            "prompt": prompt,
        }, 200
