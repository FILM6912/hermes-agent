"""Projects service — sidebar project CRUD (legacy parity)."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from app.domain.models import get_session, load_projects, save_projects

logger = logging.getLogger(__name__)

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _all_profiles_flag(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    return value in ("1", "true", "yes", "on")


class ProjectService:
    def list_projects(self, *, all_profiles_raw: str | None = None) -> dict[str, Any]:
        from app.domain.profiles import _profiles_match, get_active_profile_name

        active_profile = get_active_profile_name()
        all_profiles = _all_profiles_flag(all_profiles_raw)
        all_projects = load_projects()
        if all_profiles:
            scoped = all_projects
        else:
            scoped = [
                project
                for project in all_projects
                if _profiles_match(project.get("profile"), active_profile)
            ]
        return {
            "projects": scoped,
            "all_profiles": all_profiles,
            "active_profile": active_profile,
            "other_profile_count": len(all_projects) - len(scoped),
        }

    def create_project(
        self,
        *,
        name: str | None,
        color: str | None = None,
    ) -> tuple[dict[str, Any], int | None]:
        from app.domain.helpers import require
        from app.domain.profiles import get_active_profile_name

        body = {"name": name, "color": color}
        try:
            require(body, "name")
        except ValueError as exc:
            return {"error": str(exc)}, 400

        clean_name = (name or "").strip()[:128]
        if not clean_name:
            return {"error": "name required"}, 400
        if color and not _COLOR_RE.match(color):
            return {"error": "Invalid color format"}, 400

        projects = load_projects()
        project = {
            "project_id": uuid.uuid4().hex[:12],
            "name": clean_name,
            "color": color,
            "profile": get_active_profile_name() or "default",
            "created_at": time.time(),
        }
        projects.append(project)
        save_projects(projects)
        return {"ok": True, "project": project}, None

    def rename_project(
        self,
        *,
        project_id: str | None,
        name: str | None,
        color: str | None = None,
    ) -> tuple[dict[str, Any], int | None]:
        from app.domain.helpers import require
        from app.domain.profiles import _profiles_match, get_active_profile_name

        body = {"project_id": project_id, "name": name, "color": color}
        try:
            require(body, "project_id", "name")
        except ValueError as exc:
            return {"error": str(exc)}, 400

        projects = load_projects()
        project = next(
            (row for row in projects if row["project_id"] == project_id),
            None,
        )
        if not project:
            return {"error": "Project not found"}, 404
        active_profile = get_active_profile_name()
        if not _profiles_match(project.get("profile"), active_profile):
            return {"error": "Project not found"}, 404

        project["name"] = (name or "").strip()[:128]
        if color is not None:
            if color and not _COLOR_RE.match(color):
                return {"error": "Invalid color format"}, 400
            project["color"] = color
        save_projects(projects)
        return {"ok": True, "project": project}, None

    def delete_project(self, *, project_id: str | None) -> tuple[dict[str, Any], int | None]:
        from app.domain.config import SESSION_INDEX_FILE
        from app.domain.helpers import require
        from app.domain.profiles import _profiles_match, get_active_profile_name

        body = {"project_id": project_id}
        try:
            require(body, "project_id")
        except ValueError as exc:
            return {"error": str(exc)}, 400

        projects = load_projects()
        project = next(
            (row for row in projects if row["project_id"] == project_id),
            None,
        )
        if not project:
            return {"error": "Project not found"}, 404
        active_profile = get_active_profile_name()
        if not _profiles_match(project.get("profile"), active_profile):
            return {"error": "Project not found"}, 404

        projects = [row for row in projects if row["project_id"] != project_id]
        save_projects(projects)

        if SESSION_INDEX_FILE.exists():
            try:
                index = json.loads(SESSION_INDEX_FILE.read_text(encoding="utf-8"))
                for entry in index:
                    if entry.get("project_id") == project_id:
                        try:
                            session = get_session(entry["session_id"])
                            session.project_id = None
                            session.save()
                        except Exception:
                            logger.debug(
                                "Failed to update session %s",
                                entry.get("session_id"),
                            )
            except Exception:
                logger.debug("Failed to load session index for project unlink")

        return {"ok": True}, None
