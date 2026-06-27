"""Serialize skills hub search results for the WebUI."""

from __future__ import annotations

import re
from typing import Any

_REPO_QUERY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


def is_repo_hub_query(query: str) -> bool:
    """True when the query looks like an owner/repo slug (e.g. anthropics/skills)."""
    return bool(_REPO_QUERY_RE.match(str(query or "").strip()))


def hub_search_limit(query: str, requested: int) -> int:
    """Raise the result cap for repo-style queries so full tap lists fit."""
    limit = max(1, min(50, int(requested)))
    if is_repo_hub_query(query):
        return max(limit, 50)
    return limit


def repo_slug_from_identifier(identifier: str) -> str:
    """Extract owner/repo from a hub identifier."""
    ident = str(identifier or "").strip()
    for prefix in ("skills-sh/", "skills.sh/", "skils-sh/", "skils.sh/"):
        if ident.startswith(prefix):
            ident = ident[len(prefix) :]
            break
    parts = ident.split("/", 2)
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def serialize_hub_search_meta(meta: Any) -> dict[str, Any]:
    """Map a SkillMeta from tools.skills_hub into a JSON-friendly row."""
    extra = getattr(meta, "extra", None) or {}
    if not isinstance(extra, dict):
        extra = {}

    repo = str(getattr(meta, "repo", "") or "").strip()
    if not repo:
        repo = repo_slug_from_identifier(str(getattr(meta, "identifier", "") or ""))

    installs = extra.get("installs")
    if not isinstance(installs, int):
        installs = None

    return {
        "identifier": meta.identifier,
        "name": meta.name,
        "description": meta.description,
        "source": meta.source,
        "trust_level": meta.trust_level,
        "repo": repo,
        "installs": installs,
        "detail_url": extra.get("detail_url"),
        "repo_url": extra.get("repo_url"),
    }


def group_hub_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group flat search rows by repo slug for skills.sh-style browsing."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in results:
        repo = str(row.get("repo") or "").strip() or "unknown"
        if repo not in buckets:
            buckets[repo] = []
            order.append(repo)
        buckets[repo].append(row)

    groups: list[dict[str, Any]] = []
    for repo in order:
        skills = buckets[repo]
        total_installs = sum(
            int(skill["installs"])
            for skill in skills
            if isinstance(skill.get("installs"), int)
        )
        groups.append(
            {
                "repo": repo,
                "skill_count": len(skills),
                "total_installs": total_installs or None,
                "skills": skills,
            }
        )
    return groups
