"""Normalize verbose skills-hub install logs for API responses."""

from __future__ import annotations

import re

_ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])",
)
_ANSI_FRAGMENT_RE = re.compile(
    r"\[(?:\?25[hl]|\d+D\[J|38;5;\d+m|\d+m|999D\[J[^\]]*)",
)
_BOX_CHAR_RE = re.compile(r"[│├┤┌┐└┘┬┴┼─╮╯╰╭╲╱═║]")
_INSTALLED_LINE_RE = re.compile(
    r"^[✓✔]\s+(?:\./\.agents/skills/)?([^\s]+)",
    re.MULTILINE,
)
_INSTALLED_COUNT_RE = re.compile(
    r"installed\s+(\d+)\s+skills?",
    re.IGNORECASE,
)


def strip_terminal_ansi(text: str) -> str:
    """Remove ANSI / Rich spinner fragments from CLI output."""
    cleaned = _ANSI_ESCAPE_RE.sub("", str(text or ""))
    cleaned = _ANSI_FRAGMENT_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r", "")
    return cleaned


def summarize_npx_skills_message(
    output: str,
    *,
    repo: str = "",
    skill: str = "",
    ok: bool = True,
) -> str:
    """Return a short user-facing install summary."""
    clean = strip_terminal_ansi(output)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]

    if not ok:
        for line in lines:
            lowered = line.lower()
            if "error" in lowered or "failed" in lowered:
                return line[:160]
        compact = " ".join(lines)
        return compact[:160] if compact else "Install failed"

    installed_names = _INSTALLED_LINE_RE.findall(clean)
    count_match = _INSTALLED_COUNT_RE.search(clean)
    count = 0
    if count_match:
        count = int(count_match.group(1))
    if installed_names:
        count = max(count, len(installed_names))

    if count > 0:
        if skill or count == 1:
            name = skill or (installed_names[0] if installed_names else "skill")
            source = repo or "skills hub"
            return f"Installed {name} from {source}"
        source = repo or "skills hub"
        return f"Installed {count} skills from {source}"

    if repo and not skill:
        return f"Installed skills from {repo}"
    if repo and skill:
        return f"Installed {skill} from {repo}"

    for line in lines:
        if _BOX_CHAR_RE.search(line):
            continue
        lowered = line.lower()
        if "npm notice" in lowered or lowered.startswith("npx "):
            continue
        if "installation complete" in lowered or lowered.startswith("installed"):
            return line[:120]

    return "Skill installed successfully"


def summarize_skill_install_message(
    output: str,
    *,
    repo: str = "",
    skill: str = "",
    ok: bool = True,
) -> str:
    """Summarize any skills-hub install log (npx skills or hermes_cli rich output)."""
    clean = strip_terminal_ansi(output)
    if not clean.strip():
        return summarize_npx_skills_message("", repo=repo, skill=skill, ok=ok)

    lowered = clean.lower()
    if not ok or "error:" in lowered or "could not fetch" in lowered:
        for line in clean.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("error:"):
                return stripped[:160]
            if "could not fetch" in stripped.lower():
                return stripped[:160]
        return summarize_npx_skills_message(clean, repo=repo, skill=skill, ok=False)

    return summarize_npx_skills_message(clean, repo=repo, skill=skill, ok=True)
