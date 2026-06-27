"""Regression: skill_view must resolve frontmatter names, not just directory names."""

from __future__ import annotations

import pathlib

import pytest

from tests.conftest import requires_agent_modules

pytestmark = requires_agent_modules


def _write_skill(skills_dir: pathlib.Path, dir_name: str, frontmatter_name: str) -> None:
    skill_dir = skills_dir / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {frontmatter_name}\ndescription: Frontmatter-named skill\n---\n\n# Body\n",
        encoding="utf-8",
    )


def test_find_skill_in_dirs_matches_frontmatter_name(tmp_path, monkeypatch):
    from app.domain import routes

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir, "soft-skill", "high-end-visual-design")

    monkeypatch.setattr(routes, "_active_skills_dir", lambda: skills_dir)
    monkeypatch.setattr(routes, "_active_skill_search_dirs", lambda _sd: [skills_dir])

    skill_dir, skill_md = routes._find_skill_in_dirs(
        "high-end-visual-design",
        routes._active_skill_search_dirs(skills_dir),
    )
    assert skill_dir == skills_dir / "soft-skill"
    assert skill_md == skill_dir / "SKILL.md"

    detail = routes._skill_view_from_active_dir("high-end-visual-design")
    assert detail["success"] is True
    assert detail["name"] == "high-end-visual-design"
    assert "Frontmatter-named skill" in detail["content"]


def test_skills_list_includes_frontmatter_name(tmp_path, monkeypatch):
    from app.domain import routes

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _write_skill(skills_dir, "soft-skill", "high-end-visual-design")

    monkeypatch.setattr(routes, "_active_skills_dir", lambda: skills_dir)
    monkeypatch.setattr(routes, "_active_skill_search_dirs", lambda _sd: [skills_dir])

    payload = routes._skills_list_from_dir(skills_dir)
    names = {skill["name"] for skill in payload["skills"]}
    assert "high-end-visual-design" in names
