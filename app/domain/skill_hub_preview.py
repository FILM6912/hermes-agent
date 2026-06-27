"""Fetch remote skills-hub SKILL.md content for in-browser preview."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _raw_github_preview(identifier: str) -> dict[str, Any] | None:
    from app.domain.skill_hub_github_fallback import fetch_preview_via_raw_github

    preview = fetch_preview_via_raw_github(identifier)
    if preview and preview.get("content"):
        return preview
    return None


def fetch_hub_skill_preview(identifier: str) -> dict[str, Any]:
    """Return metadata and full SKILL.md text for a hub identifier."""
    ident = str(identifier or "").strip()
    if not ident:
        return {"success": False, "error": "identifier required"}

    # Prefer raw.githubusercontent.com for skills.sh/GitHub taps — avoids
    # GitHub Contents API quota (common in Docker without GITHUB_TOKEN).
    if "/" in ident:
        raw_preview = _raw_github_preview(ident)
        if raw_preview:
            return raw_preview

    try:
        from hermes_cli.skills_hub import _resolve_short_name, _resolve_source_meta_and_bundle
        from tools.skills_hub import GitHubAuth, create_source_router
    except ImportError as exc:
        logger.warning("skills hub preview unavailable: %s", exc)
        raw_preview = _raw_github_preview(ident)
        if raw_preview:
            return raw_preview
        return {"success": False, "error": "skills hub unavailable"}

    class _QuietConsole:
        def print(self, *_args, **_kwargs):
            return None

    auth = GitHubAuth()
    sources = create_source_router(auth)
    if "/" not in ident:
        resolved = _resolve_short_name(ident, sources, _QuietConsole())
        if not resolved:
            raw_preview = _raw_github_preview(ident)
            if raw_preview:
                return raw_preview
            return {"success": False, "error": "Skill not found"}
        ident = resolved

    meta, bundle, _matched = _resolve_source_meta_and_bundle(ident, sources)
    content = _bundle_skill_markdown(bundle)
    if not content:
        raw_preview = _raw_github_preview(ident)
        if raw_preview:
            return raw_preview
        if meta is None and bundle is None:
            return {"success": False, "error": "Skill not found"}
        return {"success": False, "error": "Skill not found"}

    name = meta.name if meta else ident.split("/")[-1]
    return {
        "success": True,
        "name": name,
        "description": meta.description if meta else "",
        "identifier": meta.identifier if meta else ident,
        "source": meta.source if meta else "",
        "trust_level": meta.trust_level if meta else "",
        "content": content,
    }


def _bundle_skill_markdown(bundle) -> str:
    if bundle is None or not getattr(bundle, "files", None):
        return ""
    files = bundle.files
    raw = files.get("SKILL.md")
    if raw is None:
        for path, value in files.items():
            if str(path).endswith("SKILL.md"):
                raw = value
                break
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)
