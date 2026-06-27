import json
import os
import pathlib
import shutil

from tests._pytest_port import BASE
from tests.conftest import requires_agent_modules

pytestmark = requires_agent_modules


def _state_dir() -> pathlib.Path:
    return pathlib.Path(os.environ["HERMES_WEBUI_TEST_STATE_DIR"])


def _remove_path(path: pathlib.Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _write_skill(skills_dir: pathlib.Path, name: str, body: str = "Body") -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


class _IsolatedSkillsDirs:
    def __init__(self, profile: str):
        self.profile = profile
        self.state = _state_dir()
        self.root_skills = self.state / "skills"
        self.profile_home = self.state / "profiles" / profile
        self.profile_skills = self.profile_home / "skills"
        self._root_was_symlink = False
        self._root_symlink_target = None

    def __enter__(self):
        self._root_was_symlink = self.root_skills.is_symlink()
        if self._root_was_symlink:
            self._root_symlink_target = self.root_skills.resolve()
        _remove_path(self.root_skills)
        _remove_path(self.profile_home)
        self.root_skills.mkdir(parents=True, exist_ok=True)
        self.profile_skills.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        _remove_path(self.profile_home)
        _remove_path(self.root_skills)
        if self._root_was_symlink and self._root_symlink_target is not None:
            self.root_skills.symlink_to(self._root_symlink_target)


def _post(path: str, body: dict, *, profile: str | None = None):
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if profile:
        headers["Cookie"] = f"hermes_profile={profile}"
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read()), exc.code


def _get(path: str, *, profile: str | None = None):
    import urllib.error
    import urllib.request

    headers = {}
    if profile:
        headers["Cookie"] = f"hermes_profile={profile}"
    req = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read()), exc.code


def test_default_inherited_skill_is_readonly_for_profile():
    profile = "skillown-default"
    with _IsolatedSkillsDirs(profile) as dirs:
        _write_skill(dirs.root_skills, "default-readonly-skill", "from default")
        _write_skill(dirs.profile_skills, "default-readonly-skill", "copied copy")

        manifest = dirs.profile_skills / ".hermes-inherited.json"
        manifest.write_text(
            json.dumps({"names": ["default-readonly-skill"]}) + "\n",
            encoding="utf-8",
        )

        data, status = _get("/api/skills", profile=profile)
        assert status == 200
        row = next(s for s in data["skills"] if s["name"] == "default-readonly-skill")
        assert row["readonly"] is True
        assert row["source"] == "default"

        save, save_status = _post(
            "/api/skills/save",
            {
                "name": "default-readonly-skill",
                "content": "---\nname: default-readonly-skill\ndescription: x\n---\n\nchanged\n",
            },
            profile=profile,
        )
        assert save_status == 403

        delete, delete_status = _post(
            "/api/skills/delete",
            {"name": "default-readonly-skill"},
            profile=profile,
        )
        assert delete_status == 403


def test_user_skill_can_be_saved_and_deleted():
    profile = "skillown-user"
    with _IsolatedSkillsDirs(profile) as _dirs:
        content = "---\nname: user-owned-skill\ndescription: mine\n---\n\n# Mine\n"
        saved, save_status = _post(
            "/api/skills/save",
            {"name": "user-owned-skill", "content": content},
            profile=profile,
        )
        assert save_status == 200
        saved_path = pathlib.Path(saved["path"]).resolve()
        saved_path.relative_to(_dirs.profile_skills.resolve())

        data, status = _get("/api/skills", profile=profile)
        assert status == 200
        row = next(s for s in data["skills"] if s["name"] == "user-owned-skill")
        assert row["readonly"] is False
        assert row["source"] == "user"

        deleted, delete_status = _post(
            "/api/skills/delete",
            {"name": "user-owned-skill"},
            profile=profile,
        )
        assert delete_status == 200
        assert not saved_path.exists()

        gone, gone_status = _post(
            "/api/skills/delete",
            {"name": "user-owned-skill"},
            profile=profile,
        )
        assert gone_status == 200
        assert gone.get("ok") is True


def test_remove_skill_installation_unlinks_profile_symlink_and_external_target(
    monkeypatch, tmp_path
):
    from app.domain import routes

    skills_dir = tmp_path / "skills"
    external = tmp_path / "external-skills"
    skills_dir.mkdir()
    external.mkdir()
    target = external / "xlsx"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: xlsx\ndescription: test\n---\n\n# xlsx\n",
        encoding="utf-8",
    )
    link = skills_dir / "xlsx"
    link.symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(
        routes,
        "_active_skill_search_dirs",
        lambda _skills_dir: [skills_dir, external],
    )

    routes._remove_skill_installation([link], skills_dir)

    assert not link.exists()
    assert not target.exists()


def test_external_skill_dir_is_deletable_within_search_dirs(monkeypatch, tmp_path):
    from app.domain import routes

    skills_dir = tmp_path / "skills"
    external = tmp_path / "external-skills"
    skills_dir.mkdir()
    external.mkdir()
    external_skill = external / "external-delete-me"
    external_skill.mkdir()

    monkeypatch.setattr(
        routes,
        "_active_skill_search_dirs",
        lambda _skills_dir: [skills_dir, external],
    )

    assert routes._skill_dir_within_search_dirs(external_skill, skills_dir) is True
    assert routes._skill_path_within(skills_dir, external_skill) is False


def test_admin_may_mutate_inherited_skill():
    from pathlib import Path
    from unittest.mock import patch

    from app.core.security import CurrentUser
    from app.domain.skill_ownership import skill_is_readonly_for_user

    admin = CurrentUser(user_id="admin@example.com", role="admin")
    user = CurrentUser(user_id="user@example.com", role="user", profile_name="skillown-admin")
    skills_dir = Path("/tmp/hermes-skills-admin-test")

    with patch("app.domain.skill_ownership.skill_is_readonly", return_value=True):
        assert skill_is_readonly_for_user("default-readonly-skill", skills_dir, user) is True
        assert skill_is_readonly_for_user("default-readonly-skill", skills_dir, admin) is False
        assert skill_is_readonly_for_user("default-readonly-skill", skills_dir, None) is True
