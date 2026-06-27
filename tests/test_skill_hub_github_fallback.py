import app.domain.skill_hub_github_fallback as hub_fallback
from app.domain.skill_hub_github_fallback import (
    _npx_skills_subprocess_kwargs,
    best_effort_align_agents_skills_ownership,
    candidate_github_paths,
    fetch_preview_via_raw_github,
    install_repo_via_npx_skills,
    normalize_skills_sh_identifier,
    npx_skills_install_args,
    relocate_stranded_npx_skills,
)


def test_normalize_skills_sh_identifier_strips_prefix():
    assert normalize_skills_sh_identifier("skills-sh/anthropics/skills/xlsx") == (
        "anthropics/skills/xlsx"
    )


def test_candidate_github_paths_includes_skills_subdir():
    paths = candidate_github_paths("skills-sh/anthropics/skills/xlsx")
    assert "anthropics/skills/skills/xlsx" in paths


def test_fetch_preview_via_raw_github_xlsx(allow_outbound_network):
    preview = fetch_preview_via_raw_github("skills-sh/anthropics/skills/xlsx")
    assert preview is not None
    assert preview["success"] is True
    assert preview["name"] == "xlsx"
    assert "spreadsheet" in preview["description"].lower()
    assert preview["content"].startswith("---")
    assert preview["fallback"] == "raw-github"


def test_npx_skills_install_args_from_identifier():
    args = npx_skills_install_args("skills-sh/anthropics/skills/xlsx")
    assert args == ("anthropics/skills", "xlsx")


def test_relocate_stranded_npx_skills(tmp_path, monkeypatch):
    home = tmp_path / "home"
    stranded_root = tmp_path / "stranded" / ".agents" / "skills"
    skill_dir = stranded_root / "pptx"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# pptx\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(hub_fallback, "_STRANDED_NPX_SKILLS_ROOT", stranded_root)

    assert relocate_stranded_npx_skills() == 1
    assert (home / ".agents" / "skills" / "pptx").is_dir()


def test_npx_skills_subprocess_uses_home_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    kwargs = _npx_skills_subprocess_kwargs()
    assert kwargs["cwd"] == str(tmp_path)
    assert (tmp_path / ".agents" / "skills").is_dir()


def test_install_repo_via_npx_skills_rejects_invalid_slug():
    result = install_repo_via_npx_skills("not-a-repo-slug")
    assert result["ok"] is False


def test_best_effort_align_agents_skills_ownership(tmp_path, monkeypatch):
    home = tmp_path / "home"
    skill_dir = home / ".agents" / "skills" / "pptx"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# pptx\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    assert best_effort_align_agents_skills_ownership() == 0
    assert skill_dir.is_dir()
