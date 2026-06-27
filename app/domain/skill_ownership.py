"""Track which profile skills were inherited from the default profile."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

INHERITED_MANIFEST = ".hermes-inherited.json"


def inherited_manifest_path(skills_dir: Path) -> Path:
    return skills_dir / INHERITED_MANIFEST


def default_profile_skills_dir() -> Path:
    from app.domain.profiles import _default_profile_home

    return _default_profile_home() / "skills"


def active_profile_is_default_master() -> bool:
    from app.domain.profiles import _default_profile_home, get_active_hermes_home

    try:
        return get_active_hermes_home().resolve() == _default_profile_home().resolve()
    except Exception:
        return False


def collect_skill_names(skills_dir: Path) -> set[str]:
    """Return frontmatter skill names discovered under *skills_dir*."""
    if not skills_dir.is_dir():
        return set()
    try:
        from agent.skill_utils import iter_skill_index_files
        from tools.skills_tool import _EXCLUDED_SKILL_DIRS, _parse_frontmatter
    except ImportError:
        return set()

    names: set[str] = set()
    for skill_md in iter_skill_index_files(skills_dir, "SKILL.md"):
        if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
            continue
        skill_dir = skill_md.parent
        try:
            content = skill_md.read_text(encoding="utf-8")[:4000]
            frontmatter, _body = _parse_frontmatter(content)
            name = str(frontmatter.get("name", skill_dir.name) or skill_dir.name).strip()
            if name:
                names.add(name[:64])
        except Exception as exc:
            logger.debug("Failed to read skill name from %s: %s", skill_md, exc)
    return names


def _read_manifest_names(skills_dir: Path) -> set[str] | None:
    manifest = inherited_manifest_path(skills_dir)
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid inherited skills manifest at %s: %s", manifest, exc)
        return set()
    if not isinstance(data, dict):
        return set()
    raw = data.get("names")
    if not isinstance(raw, list):
        return set()
    return {str(name).strip() for name in raw if str(name).strip()}


def save_inherited_skill_names(skills_dir: Path, names: Iterable[str]) -> None:
    skills_dir.mkdir(parents=True, exist_ok=True)
    payload = {"names": sorted({str(name).strip() for name in names if str(name).strip()})}
    inherited_manifest_path(skills_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_inherited_skill_names(skills_dir: Path) -> set[str]:
    """Return skill names inherited from the default profile for *skills_dir*."""
    if active_profile_is_default_master():
        return set()

    manifest_names = _read_manifest_names(skills_dir)
    if manifest_names is not None:
        return manifest_names

    default_names = collect_skill_names(default_profile_skills_dir())
    profile_names = collect_skill_names(skills_dir)
    inherited = default_names & profile_names
    if inherited:
        save_inherited_skill_names(skills_dir, inherited)
    return inherited


def mark_skills_inherited(skills_dir: Path, names: Iterable[str]) -> None:
    if active_profile_is_default_master():
        return
    current = load_inherited_skill_names(skills_dir)
    current.update(str(name).strip() for name in names if str(name).strip())
    save_inherited_skill_names(skills_dir, current)


def skill_is_readonly(skill_name: str, skills_dir: Path) -> bool:
    name = str(skill_name or "").strip()
    if not name or active_profile_is_default_master():
        return False
    return name in load_inherited_skill_names(skills_dir)


def skill_is_readonly_for_user(
    skill_name: str,
    skills_dir: Path,
    user=None,
) -> bool:
    """Return whether *skill_name* is read-only for *user* (admins may mutate)."""
    if user is not None and getattr(user, "is_admin", False):
        return False
    return skill_is_readonly(skill_name, skills_dir)
