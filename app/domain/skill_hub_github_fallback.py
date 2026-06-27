"""GitHub-API-free fallbacks for skills.sh hub preview and install."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_RAW_PREFIX = "https://raw.githubusercontent.com"
_SKILLS_SH_BASE = "https://skills.sh"
_SKILLS_SH_PREFIXES = ("skills-sh/", "skills.sh/", "skils-sh/", "skils.sh/")
_DEFAULT_BRANCHES = ("main", "master")
_INSTALL_CMD_RE = re.compile(
    r"npx\s+skills\s+add\s+(?P<repo>https?://github\.com/[^\s<]+|[^\s<]+)"
    r"(?:\s+--skill\s+(?P<skill>[^\s<]+))?",
    re.IGNORECASE,
)


_STRANDED_NPX_SKILLS_ROOT = Path("/app/.agents/skills")


def _agents_skills_root() -> Path:
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
    return home / ".agents" / "skills"


def best_effort_align_agents_skills_ownership() -> int:
    """Chown ``~/.agents/skills`` to the current uid/gid where the process is allowed."""
    root = _agents_skills_root()
    if not root.is_dir():
        return 0

    uid = os.getuid()
    gid = os.getgid()
    aligned = 0
    paths = [root, *root.rglob("*")]
    for path in paths:
        try:
            stat = path.lstat()
        except OSError:
            continue
        if stat.st_uid == uid and stat.st_gid == gid:
            continue
        try:
            os.chown(path, uid, gid, follow_symlinks=False)
            aligned += 1
        except OSError as exc:
            logger.debug("Could not chown %s to %s:%s: %s", path, uid, gid, exc)
    return aligned


def relocate_stranded_npx_skills() -> int:
    """Move skills installed under ``/app/.agents/skills`` into ``~/.agents/skills``.

    Returns the number of skill directories relocated.
    """
    wrong_root = _STRANDED_NPX_SKILLS_ROOT
    if not wrong_root.is_dir():
        return 0

    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
    target_root = home / ".agents" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)

    moved = 0
    for item in wrong_root.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue
        destination = target_root / item.name
        if destination.exists():
            continue
        try:
            shutil.move(str(item), str(destination))
            moved += 1
        except OSError as exc:
            logger.warning("Failed to relocate npx skill %s: %s", item, exc)
    if moved:
        best_effort_align_agents_skills_ownership()
    return moved


def _npx_skills_subprocess_kwargs() -> dict[str, Any]:
    """Run ``npx skills`` from the user home so installs land in ``~/.agents/skills``.

    The CLI writes to ``./.agents/skills`` relative to the current working
    directory. When uvicorn's cwd is ``/app``, a naive subprocess installs under
    ``/app/.agents/skills`` instead of the Docker bind mount at
    ``/home/hermeswebui/.agents/skills``.
    """
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
    agents_dir = home / ".agents" / "skills"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return {"cwd": str(home), "env": os.environ.copy()}


def _finalize_npx_skills_install() -> None:
    relocate_stranded_npx_skills()
    best_effort_align_agents_skills_ownership()


def normalize_skills_sh_identifier(identifier: str) -> str:
    ident = str(identifier or "").strip()
    for prefix in _SKILLS_SH_PREFIXES:
        if ident.startswith(prefix):
            return ident[len(prefix) :]
    return ident


def candidate_github_paths(identifier: str) -> list[str]:
    """Mirror SkillsShSource._candidate_identifiers for raw.githubusercontent.com."""
    canonical = normalize_skills_sh_identifier(identifier)
    parts = canonical.split("/", 2)
    if len(parts) < 3:
        return [canonical] if canonical else []

    repo = f"{parts[0]}/{parts[1]}"
    skill_path = parts[2].lstrip("/")
    candidates = [
        f"{repo}/{skill_path}",
        f"{repo}/skills/{skill_path}",
        f"{repo}/.agents/skills/{skill_path}",
        f"{repo}/.claude/skills/{skill_path}",
    ]
    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def fetch_skill_md_raw(identifier: str) -> tuple[str | None, str | None]:
    """Return (SKILL.md text, resolved owner/repo/path) or (None, None)."""
    for gh_path in candidate_github_paths(identifier):
        parts = gh_path.split("/", 2)
        if len(parts) < 3:
            continue
        repo_slug = f"{parts[0]}/{parts[1]}"
        skill_rel = parts[2].rstrip("/")
        for branch in _DEFAULT_BRANCHES:
            url = f"{_RAW_PREFIX}/{repo_slug}/{branch}/{skill_rel}/SKILL.md"
            try:
                resp = httpx.get(url, timeout=20, follow_redirects=True)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text, gh_path
            except httpx.HTTPError as exc:
                logger.debug("raw GitHub fetch failed for %s: %s", url, exc)
    return None, None


def fetch_preview_via_raw_github(identifier: str) -> dict[str, Any] | None:
    """Build a hub preview payload without using the GitHub Contents API."""
    content, gh_path = fetch_skill_md_raw(identifier)
    if not content or not gh_path:
        return None

    try:
        from tools.skills_tool import _parse_frontmatter
    except ImportError:
        _parse_frontmatter = None

    frontmatter: dict[str, Any] = {}
    if _parse_frontmatter is not None:
        frontmatter, _body = _parse_frontmatter(content)

    parts = gh_path.split("/", 2)
    repo_slug = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ""
    skill_token = parts[2].split("/")[-1] if len(parts) >= 3 else identifier.split("/")[-1]
    name = str(frontmatter.get("name") or skill_token)
    description = str(frontmatter.get("description") or "")
    canonical = normalize_skills_sh_identifier(identifier)
    wrapped = f"skills-sh/{canonical}" if canonical else identifier

    trust_level = "community"
    if repo_slug:
        try:
            from tools.skills_guard import TRUSTED_REPOS

            if repo_slug in TRUSTED_REPOS:
                trust_level = "trusted"
        except ImportError:
            pass

    return {
        "success": True,
        "name": name,
        "description": description,
        "identifier": wrapped,
        "source": "skills.sh",
        "trust_level": trust_level,
        "content": content,
        "fallback": "raw-github",
    }


def _extract_repo_slug(repo_value: str) -> str | None:
    value = str(repo_value or "").strip().rstrip("/")
    if not value:
        return None
    if value.startswith("https://github.com/"):
        slug = value[len("https://github.com/") :]
        if slug.endswith(".git"):
            slug = slug[:-4]
        return slug or None
    if "/" in value and " " not in value:
        return value
    return None


def _fetch_skills_sh_detail(canonical: str) -> dict[str, Any] | None:
    if not canonical:
        return None
    try:
        resp = httpx.get(f"{_SKILLS_SH_BASE}/{canonical}", timeout=20)
        if resp.status_code != 200:
            return None
    except httpx.HTTPError as exc:
        logger.debug("skills.sh detail fetch failed for %s: %s", canonical, exc)
        return None

    parts = canonical.split("/", 2)
    if len(parts) < 3:
        return None
    default_repo = f"{parts[0]}/{parts[1]}"
    skill_token = parts[2]
    repo = default_repo
    install_skill = skill_token

    install_match = _INSTALL_CMD_RE.search(resp.text)
    if install_match:
        repo_value = (install_match.group("repo") or "").strip()
        install_skill = (install_match.group("skill") or install_skill).strip()
        repo = _extract_repo_slug(repo_value) or repo

    return {"repo": repo, "install_skill": install_skill}


def npx_skills_install_args(identifier: str) -> tuple[str, str] | None:
    """Return (repo_slug, skill_name) for ``npx skills add``."""
    canonical = normalize_skills_sh_identifier(identifier)
    detail = _fetch_skills_sh_detail(canonical)
    if detail:
        repo = detail.get("repo")
        skill = detail.get("install_skill")
        if isinstance(repo, str) and isinstance(skill, str) and repo and skill:
            return repo, skill

    parts = canonical.split("/", 2)
    if len(parts) >= 3:
        repo = f"{parts[0]}/{parts[1]}"
        skill = parts[2].split("/")[-1]
        return repo, skill
    return None


def install_repo_via_npx_skills(repo: str) -> dict[str, Any]:
    """Install every skill in a tap via ``npx skills add owner/repo``."""
    slug = str(repo or "").strip()
    if not slug or slug.count("/") != 1:
        return {"ok": False, "message": "Invalid repo slug"}

    cmd = ["npx", "--yes", "skills", "add", slug, "-y"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            **_npx_skills_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("npx skills repo install failed for %s: %s", slug, exc)
        return {"ok": False, "message": f"npx skills repo install failed: {exc}"}

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    lowered = output.lower()
    ok = result.returncode == 0 and (
        "installation complete" in lowered or "installed" in lowered
    )

    from app.domain.skill_hub_install_message import summarize_npx_skills_message

    message = summarize_npx_skills_message(
        output,
        repo=slug,
        ok=ok,
    )
    if ok:
        _finalize_npx_skills_install()
    return {"ok": ok, "message": message, "repo": slug}


def install_via_npx_skills(identifier: str) -> dict[str, Any]:
    """Install a skills.sh skill via git clone (no GitHub API quota)."""
    args = npx_skills_install_args(identifier)
    if not args:
        return {"ok": False, "message": "Could not resolve skill for npx install"}

    repo, skill = args
    cmd = ["npx", "--yes", "skills", "add", repo, "--skill", skill, "-y"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            **_npx_skills_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("npx skills install failed for %s: %s", identifier, exc)
        return {"ok": False, "message": f"npx skills install failed: {exc}"}

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    lowered = output.lower()
    ok = result.returncode == 0 and "installation complete" in lowered
    if not ok and result.returncode == 0 and "installed" in lowered:
        ok = True

    from app.domain.skill_hub_install_message import summarize_npx_skills_message

    message = summarize_npx_skills_message(
        output,
        repo=repo,
        skill=skill,
        ok=ok,
    )
    if ok:
        _finalize_npx_skills_install()
    return {"ok": ok, "message": message, "repo": repo, "skill": skill}
