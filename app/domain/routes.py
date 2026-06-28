"""
Hermes Web UI -- Route handlers for GET and POST endpoints.
Extracted from server.py (Sprint 11) so server.py is a thin shell.
"""

import html as _html
import copy
import io
import gzip
import json
import logging
import os
import queue
import re
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import re
from pathlib import Path
from contextlib import closing
from urllib.parse import parse_qs, urlsplit
from app.domain.agent_sessions import (
    MESSAGING_SOURCES,
    is_cli_session_row,
    is_cli_session_row_visible,
    read_session_lineage_report,
)
from app.domain.session_sidebar import (
    CLI_VISIBLE_SESSION_CAP,
    _cap_recent_cli_sessions,
    _is_cli_session_for_settings,
    _merge_cli_sidebar_metadata,
    _reconcile_stale_stream_state_for_session_rows,
)
from app.domain.compression_anchor import (
    normalize_compaction_message_roles,
    visible_messages_for_anchor,
)
from app.domain.session_events import (
    publish_session_list_changed,
    subscribe_session_events,
    unsubscribe_session_events,
)

logger = logging.getLogger(__name__)

# Treat stalled/closed HTTP clients as normal disconnects.  Long-lived SSE
# connections often end this way when a browser tab sleeps, a phone switches
# networks, or Tailscale leaves the socket half-closed.  If these bubble to the
# request handler, the server logs 500s and can leave CLOSE-WAIT sockets around
# until the OS-level timeout fires.
_CLIENT_DISCONNECT_ERRORS = (
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
    OSError,
)

# ── Cron run tracking ────────────────────────────────────────────────────────
# Track job IDs currently being executed so the frontend can poll status.
_RUNNING_CRON_JOBS: dict[str, float] = {}  # job_id → start_timestamp
_RUNNING_CRON_LOCK = threading.Lock()
_MANUAL_COMPRESSION_JOBS: dict[str, dict] = {}
_MANUAL_COMPRESSION_JOBS_LOCK = threading.Lock()
_MANUAL_COMPRESSION_JOB_TTL_SECONDS = 10 * 60
_CRON_OUTPUT_CONTENT_LIMIT = 8000
_CRON_OUTPUT_HEADER_CONTEXT = 200
_MESSAGING_RAW_SOURCES = {str(s).strip().lower() for s in MESSAGING_SOURCES}
_MESSAGING_SESSION_METADATA_CACHE: dict[str, object] = {
    "path": None,
    "mtime": None,
    "identity": {},
}
_MESSAGING_SESSION_METADATA_LOCK = threading.Lock()
_STALE_MESSAGING_END_REASONS = {"session_reset", "session_switch"}
def _session_field(session, field, default=None):
    if isinstance(session, dict):
        return session.get(field, default)
    return getattr(session, field, default)


# ── Profile-scoped session/project filtering (#1611, #1614) ────────────────
#
# Sessions and projects are stored in the WebUI sidecar without per-row
# isolation by default — they're tagged with a `profile` field but every
# query saw all rows. The fix scopes both endpoints to the active profile
# by default, with `?all_profiles=1` opting into aggregate mode.
#
# Renamed-root profile handling (#1612): a row tagged `profile='default'`
# matches the active root regardless of the root's display name, and a row
# tagged with the renamed-root display name (e.g. 'kinni') likewise matches
# when the active profile is `'default'`. _is_root_profile() is the
# canonical check.

# Canonical helper now lives in api.profiles so out-of-process consumers
# (mcp_server.py) can import it without duplicating the visibility model.
# Re-exported here so existing `_profiles_match(...)` call sites in this
# module keep resolving without per-call-site refactors.
from app.domain.profiles import _profiles_match  # noqa: F401, E402  (re-export)


def _all_profiles_query_flag(parsed_url) -> bool:
    """Return True if the request URL has `?all_profiles=1` (or true/yes).

    Centralizes the opt-in parsing so /api/sessions and /api/projects use
    the same shape. Accepts 1/true/yes (case-insensitive) for ergonomics.
    """
    qs = parse_qs(parsed_url.query)
    raw = qs.get('all_profiles', [''])[0].strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def _active_skills_dir() -> Path:
    """Return the skills directory for the request's active Hermes profile.

    WebUI profile switches are cookie/thread-local scoped, so the agent
    module-level ``tools.skills_tool.SKILLS_DIR`` can still point at the server
    startup profile. Skills UI endpoints must derive the directory from
    ``get_active_hermes_home()`` for every request instead of reading that
    process-global constant.
    """
    try:
        from app.domain.profiles import get_active_hermes_home

        return Path(get_active_hermes_home()) / "skills"
    except Exception:
        try:
            from tools.skills_tool import SKILLS_DIR

            return Path(SKILLS_DIR)
        except Exception:
            return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser() / "skills"


def _skill_path_within(base_dir: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base_dir.resolve())
        return True
    except (OSError, ValueError):
        return False


def _skill_category_from_path(skill_md: Path, skills_dirs: list[Path]) -> str | None:
    for skills_dir in skills_dirs:
        try:
            rel_path = skill_md.relative_to(skills_dir)
        except ValueError:
            continue
        parts = rel_path.parts
        if len(parts) >= 3:
            return parts[0]
        return None
    return None


def _active_skill_search_dirs(skills_dir: Path) -> list[Path]:
    dirs = [skills_dir]
    try:
        from agent.skill_utils import get_external_skills_dirs

        dirs.extend(Path(p) for p in get_external_skills_dirs())
    except Exception:
        pass
    return [p for p in dirs if p.exists()]


def _skill_dir_within_search_dirs(skill_dir: Path, skills_dir: Path) -> bool:
    """True when *skill_dir* lives under the profile or configured external dirs."""
    for base in _active_skill_search_dirs(skills_dir):
        if _skill_path_within(base, skill_dir):
            return True
    return False


def _remove_path_safe(path: Path) -> None:
    """Remove a file, directory, or symlink without calling rmtree on symlinks."""
    import shutil

    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _skill_install_paths_for_name(name: str, skills_dir: Path) -> list[Path]:
    """Collect every on-disk install path for *name* across profile + external dirs."""
    raw_name = str(name or "").strip().lower().replace(" ", "-")
    if not raw_name:
        return []

    search_dirs = _active_skill_search_dirs(skills_dir)
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path | None) -> None:
        if path is None:
            return
        if not (path.exists() or path.is_symlink()):
            return
        if not _skill_dir_within_search_dirs(path, skills_dir):
            return
        key = str(path.resolve()) if path.is_symlink() else str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    candidate_names = [raw_name]
    if ":" in raw_name:
        namespace, bare = raw_name.split(":", 1)
        if namespace and bare:
            candidate_names.append(f"{namespace}/{bare}")

    for base in search_dirs:
        for candidate_name in candidate_names:
            _add(base / candidate_name)

    skill_dir, _skill_md = _find_skill_in_dirs(raw_name, search_dirs)
    _add(skill_dir)
    return paths


def _remove_skill_installation(skill_dirs: list[Path], skills_dir: Path) -> None:
    """Delete skill installs, including profile symlinks into external_dirs.

    ``npx skills`` often symlinks ``~/.hermes/skills/<name>`` → ``~/.agents/skills/<name>``.
    Walk symlinks to their targets and never call ``rmtree`` on a symlink itself.
    """
    queue: list[Path] = list(skill_dirs)
    seen: set[str] = set()
    expanded: list[Path] = []

    while queue:
        path = queue.pop(0)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not _skill_dir_within_search_dirs(path, skills_dir):
            continue
        expanded.append(path)
        if path.is_symlink():
            try:
                resolved = path.resolve()
                if str(resolved) not in seen:
                    queue.append(resolved)
            except OSError:
                pass

    symlinks = [path for path in expanded if path.is_symlink()]
    others = [path for path in expanded if not path.is_symlink()]
    for path in symlinks + others:
        _remove_path_safe(path)


def _worktree_retained_payload(session) -> dict:
    """Return explicit no-cleanup metadata for worktree-backed session actions."""
    worktree_path = getattr(session, "worktree_path", None) if session else None
    if not worktree_path:
        return {}
    payload = {
        "worktree_retained": True,
        "worktree_path": worktree_path,
    }
    worktree_branch = getattr(session, "worktree_branch", None)
    worktree_repo_root = getattr(session, "worktree_repo_root", None)
    if worktree_branch:
        payload["worktree_branch"] = worktree_branch
    if worktree_repo_root:
        payload["worktree_repo_root"] = worktree_repo_root
    return payload


def _worktree_retained_payload_for_session_id(sid: str) -> dict:
    try:
        return _worktree_retained_payload(get_session(sid, metadata_only=True))
    except KeyError:
        return {}
    except Exception:
        logger.debug("Failed to read worktree metadata for deleted session %s", sid)
        return {}


def _skills_list_from_dir(
    skills_dir: Path,
    category: str | None = None,
    user=None,
) -> dict:
    """List skills using an explicit local skills directory.

    This mirrors ``tools.skills_tool.skills_list`` closely, but keeps the local
    scan root explicit so per-client WebUI profile switches do not race on or
    leak through the skills tool's module-global ``SKILLS_DIR``.
    """
    from agent.skill_utils import iter_skill_index_files
    from tools.skills_tool import (
        MAX_DESCRIPTION_LENGTH,
        _EXCLUDED_SKILL_DIRS,
        _get_disabled_skill_names,
        _parse_frontmatter,
        _sort_skills,
        skill_matches_platform,
    )

    try:
        from app.domain.skill_hub_github_fallback import relocate_stranded_npx_skills

        relocate_stranded_npx_skills()
    except Exception:
        pass

    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)
        return {
            "success": True,
            "skills": [],
            "categories": [],
            "message": f"No skills found. Skills directory created at {skills_dir}/",
        }

    all_skills = []
    seen_names: set[str] = set()
    disabled = _get_disabled_skill_names()
    search_dirs = _active_skill_search_dirs(skills_dir)
    from app.domain.skill_ownership import (
        load_inherited_skill_names,
        skill_is_readonly_for_user,
    )

    inherited_names = load_inherited_skill_names(skills_dir)

    for scan_dir in search_dirs:
        for skill_md in iter_skill_index_files(scan_dir, "SKILL.md"):
            if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
                continue
            skill_dir = skill_md.parent
            try:
                content = skill_md.read_text(encoding="utf-8")[:4000]
                frontmatter, body = _parse_frontmatter(content)
                if not skill_matches_platform(frontmatter):
                    continue
                name = frontmatter.get("name", skill_dir.name)[:64]
                if name in seen_names:
                    continue
                description = frontmatter.get("description", "")
                if not description:
                    for line in body.strip().split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#"):
                            description = line
                            break
                if len(description) > MAX_DESCRIPTION_LENGTH:
                    description = description[: MAX_DESCRIPTION_LENGTH - 3] + "..."
                seen_names.add(name)
                is_external = not _skill_path_within(skills_dir, skill_dir)
                readonly = skill_is_readonly_for_user(name, skills_dir, user)
                if is_external:
                    source = "external"
                elif name in inherited_names:
                    source = "default"
                else:
                    source = "user"
                all_skills.append(
                    {
                        "name": name,
                        "description": description,
                        "category": _skill_category_from_path(skill_md, search_dirs),
                        "disabled": name in disabled,
                        "readonly": readonly,
                        "source": source,
                    }
                )
            except (UnicodeDecodeError, PermissionError) as e:
                logger.debug("Failed to read skill file %s: %s", skill_md, e)
            except Exception as e:
                logger.debug(
                    "Skipping skill at %s: failed to parse: %s", skill_md, e, exc_info=True
                )

    if category:
        all_skills = [s for s in all_skills if s.get("category") == category]
    all_skills = _sort_skills(all_skills)
    categories = sorted(set(s.get("category") for s in all_skills if s.get("category")))
    result = {
        "success": True,
        "skills": all_skills,
        "categories": categories,
        "count": len(all_skills),
    }
    if all_skills:
        result["hint"] = "Use skill_view(name) to see full content, tags, and linked files"
    else:
        result["message"] = "No skills found in skills/ directory."
    return result


def _find_skill_in_dirs(name: str, skills_dirs: list[Path]) -> tuple[Path | None, Path | None]:
    """Resolve a WebUI skill name inside explicit skills directories."""
    from agent.skill_utils import iter_skill_index_files
    from tools.skills_tool import _EXCLUDED_SKILL_DIRS, _parse_frontmatter

    raw_name = str(name or "").strip().strip("/")
    if not raw_name:
        return None, None

    candidate_names = [raw_name]
    if ":" in raw_name:
        namespace, bare = raw_name.split(":", 1)
        if namespace and bare:
            candidate_names.append(f"{namespace}/{bare}")

    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            continue
        for candidate_name in candidate_names:
            direct_path = skills_dir / candidate_name
            if not _skill_path_within(skills_dir, direct_path):
                continue
            if direct_path.is_dir() and (direct_path / "SKILL.md").exists():
                return direct_path, direct_path / "SKILL.md"
            legacy_md = direct_path.with_suffix(".md")
            if legacy_md.exists() and _skill_path_within(skills_dir, legacy_md):
                return legacy_md.parent, legacy_md

        for skill_md in iter_skill_index_files(skills_dir, "SKILL.md"):
            if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
                continue
            skill_dir = skill_md.parent
            if skill_dir.name == raw_name:
                return skill_dir, skill_md
            try:
                frontmatter, _ = _parse_frontmatter(skill_md.read_text(encoding="utf-8")[:4000])
                if frontmatter.get("name") == raw_name:
                    return skill_dir, skill_md
            except Exception:
                continue

        for legacy_md in skills_dir.rglob("*.md"):
            if legacy_md.name == "SKILL.md":
                continue
            if legacy_md.stem == raw_name and _skill_path_within(skills_dir, legacy_md):
                return legacy_md.parent, legacy_md
    return None, None


def _find_skill_in_dir(name: str, skills_dir: Path) -> tuple[Path | None, Path | None]:
    """Resolve a WebUI skill name inside an explicit skills directory."""
    return _find_skill_in_dirs(name, [skills_dir])


def _skill_not_found_payload(name: str, skills_dir: Path) -> dict:
    available = [s["name"] for s in _skills_list_from_dir(skills_dir).get("skills", [])[:20]]
    return {
        "success": False,
        "error": f"Skill '{name}' not found.",
        "available_skills": available,
        "hint": "Use skills_list to see all available skills",
    }


def _linked_files_for_skill(skill_dir: Path | None) -> dict:
    if not skill_dir or not (skill_dir / "SKILL.md").exists():
        return {}
    linked_files: dict[str, list[str]] = {}

    references_dir = skill_dir / "references"
    if references_dir.exists():
        refs = [str(f.relative_to(skill_dir)) for f in references_dir.glob("*.md")]
        if refs:
            linked_files["references"] = sorted(refs)

    templates_dir = skill_dir / "templates"
    if templates_dir.exists():
        templates = []
        for ext in ["*.md", "*.py", "*.yaml", "*.yml", "*.json", "*.tex", "*.sh"]:
            templates.extend(str(f.relative_to(skill_dir)) for f in templates_dir.rglob(ext))
        if templates:
            linked_files["templates"] = sorted(set(templates))

    assets_dir = skill_dir / "assets"
    if assets_dir.exists():
        assets = [str(f.relative_to(skill_dir)) for f in assets_dir.rglob("*") if f.is_file()]
        if assets:
            linked_files["assets"] = sorted(assets)

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists():
        scripts = []
        for ext in ["*.py", "*.sh", "*.bash", "*.js", "*.ts", "*.rb"]:
            scripts.extend(str(f.relative_to(skill_dir)) for f in scripts_dir.glob(ext))
        if scripts:
            linked_files["scripts"] = sorted(set(scripts))

    return linked_files


def _skill_view_from_file(skill_dir: Path | None, skill_md: Path) -> dict:
    from tools.skills_tool import _parse_frontmatter, _parse_tags, skill_matches_platform

    content = skill_md.read_text(encoding="utf-8")
    frontmatter, _body = _parse_frontmatter(content)
    if not skill_matches_platform(frontmatter):
        return {"success": False, "error": "Skill is not available on this platform."}

    metadata = frontmatter.get("metadata")
    hermes_meta = metadata.get("hermes", {}) if isinstance(metadata, dict) else {}
    tags = _parse_tags(hermes_meta.get("tags") or frontmatter.get("tags", ""))
    related_skills = _parse_tags(
        hermes_meta.get("related_skills") or frontmatter.get("related_skills", "")
    )
    try:
        path = str(skill_md.relative_to((skill_dir or skill_md.parent).parent))
    except ValueError:
        path = str(skill_md)

    return {
        "success": True,
        "name": frontmatter.get("name", skill_md.stem if not skill_dir else skill_dir.name),
        "description": frontmatter.get("description", ""),
        "tags": tags,
        "related_skills": related_skills,
        "content": content,
        "path": path,
        "skill_dir": str(skill_dir) if skill_dir else None,
        "linked_files": _linked_files_for_skill(skill_dir),
    }


def _skill_view_from_active_dir(name: str) -> dict:
    from tools.skills_tool import skill_view as _skill_view

    skills_dir = _active_skills_dir()
    search_dirs = _active_skill_search_dirs(skills_dir)
    skill_dir, skill_md = _find_skill_in_dirs(name, search_dirs)
    if not skill_md:
        # Preserve plugin-qualified skill viewing without falling back to the
        # startup/root profile's local skills tree for ordinary missing skills.
        if ":" in str(name or ""):
            try:
                from agent.skill_utils import is_valid_namespace, parse_qualified_name
                from hermes_cli.plugins import discover_plugins, get_plugin_manager

                namespace, _bare = parse_qualified_name(name)
                if is_valid_namespace(namespace):
                    discover_plugins()
                    pm = get_plugin_manager()
                    if pm.find_plugin_skill(name) is not None or pm.list_plugin_skills(namespace):
                        raw = _skill_view(name)
                        return json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                pass
        return _skill_not_found_payload(name, skills_dir)
    return _skill_view_from_file(skill_dir, skill_md)

# ── SSE app-level heartbeat (#1623) ────────────────────────────────────────
#
# Kernel TCP keepalive (server.py setsockopt block) declares a peer dead at
# KEEPIDLE (10s) + KEEPINTVL (5s) * KEEPCNT (3) = 25s in the worst case. The
# app-level SSE heartbeat must fire well below that window so flaky-network
# probes never get the chance to kill an idle stream during long LLM thinking
# phases. 5s gives the kernel ~5x headroom: probe at 10s, heartbeat byte at
# every 5s of idle keeps the socket warm.
#
# Cost: ~12 bytes per heartbeat * 12 extra heartbeats/min = ~150B/min idle.
# Trivial; many production SSE deployments run 5-15s heartbeats specifically
# to handle proxies and mobile NAT.
_SSE_HEARTBEAT_INTERVAL_SECONDS = 5


def _normalize_messaging_source(raw_source) -> str:
    return str(raw_source or "").strip().lower()


def _is_known_messaging_source(raw_source) -> bool:
    return _normalize_messaging_source(raw_source) in _MESSAGING_RAW_SOURCES


def _safe_first(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _gateway_session_metadata_path():
    try:
        from app.domain.profiles import get_active_hermes_home
        hermes_home = Path(get_active_hermes_home()).expanduser().resolve()
    except Exception:
        hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser().resolve()
    return hermes_home / "sessions" / "sessions.json"


def _load_gateway_session_identity_map() -> dict[str, dict]:
    path = _gateway_session_metadata_path()
    if not path.exists():
        return {}

    try:
        st = path.stat()
        cache = _MESSAGING_SESSION_METADATA_CACHE
        with _MESSAGING_SESSION_METADATA_LOCK:
            if cache["path"] == str(path) and cache["mtime"] == st.st_mtime:
                return cache["identity"].copy()
    except Exception:
        return {}

    try:
        raw_sessions = json.loads(path.read_text(encoding="utf-8"))
    except Exception as _json_err:
        logger.debug("Failed to parse gateway sessions metadata from %s: %s", path, _json_err)
        return {}

    mapping: dict[str, dict] = {}
    if isinstance(raw_sessions, dict):
        for _entry in raw_sessions.values():
            if not isinstance(_entry, dict):
                continue
            session_id = _safe_first(_entry.get("session_id"))
            if not session_id:
                continue
            origin = _entry.get("origin") if isinstance(_entry.get("origin"), dict) else {}
            platform = _safe_first(origin.get("platform"), _entry.get("platform"))
            mapping[session_id] = {
                "session_key": _safe_first(_entry.get("session_key"), _entry.get("key")),
                "chat_id": _safe_first(origin.get("chat_id"), _entry.get("chat_id")),
                "thread_id": _safe_first(origin.get("thread_id"), _entry.get("thread_id")),
                "chat_type": _safe_first(origin.get("chat_type"), _entry.get("chat_type")),
                "user_id": _safe_first(origin.get("user_id"), _entry.get("user_id")),
                "platform": platform,
                "raw_source": platform,
            }

    with _MESSAGING_SESSION_METADATA_LOCK:
        _MESSAGING_SESSION_METADATA_CACHE["path"] = str(path)
        _MESSAGING_SESSION_METADATA_CACHE["mtime"] = st.st_mtime
        _MESSAGING_SESSION_METADATA_CACHE["identity"] = mapping
    return mapping.copy()


def _mark_cron_running(job_id: str):
    with _RUNNING_CRON_LOCK:
        _RUNNING_CRON_JOBS[job_id] = time.time()


def _mark_cron_done(job_id: str):
    with _RUNNING_CRON_LOCK:
        _RUNNING_CRON_JOBS.pop(job_id, None)


def _is_cron_running(job_id: str) -> tuple[bool, float]:
    """Return (is_running, elapsed_seconds)."""
    with _RUNNING_CRON_LOCK:
        t = _RUNNING_CRON_JOBS.get(job_id)
        if t is None:
            return False, 0.0
        return True, time.time() - t


def _cron_response_marker_index(text: str) -> int:
    """Return the start index of a markdown Response heading, if present."""
    candidates = []
    for heading in ("## Response", "# Response"):
        if text.startswith(heading):
            candidates.append(0)
        idx = text.find(f"\n{heading}")
        if idx >= 0:
            candidates.append(idx + 1)
    return min(candidates) if candidates else -1


def _cron_output_content_window(text: str, limit: int = _CRON_OUTPUT_CONTENT_LIMIT) -> str:
    """Return a bounded cron output window that preserves useful response text.

    Cron output files can contain large skill dumps in the Prompt section. The
    UI already extracts ``## Response`` when present, so keep that section in
    the API payload instead of blindly returning the first ``limit`` chars.
    """
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text

    response_idx = _cron_response_marker_index(text)
    if response_idx >= 0:
        header = text[:min(_CRON_OUTPUT_HEADER_CONTEXT, response_idx)].rstrip()
        response = text[response_idx:].lstrip("\n")
        content = f"{header}\n...\n{response}" if header else response
        return content[:limit]

    return text[-limit:]




def _cron_job_for_api(job: dict) -> dict:
    """Return a cron job payload with optional UI settings normalized.

    Legacy jobs intentionally persist without ``profile`` so they keep the
    scheduler's server-default behavior. The API still returns ``profile: None``
    so the UI can label that state explicitly instead of guessing.

    ``toast_notifications`` is a WebUI preference for completion toasts. Legacy
    jobs default to enabled so existing behavior is preserved unless a job is
    explicitly muted.
    """
    payload = dict(job or {})
    payload.setdefault("profile", None)
    payload["toast_notifications"] = payload.get("toast_notifications") is not False
    return payload


def _cron_jobs_for_api(jobs) -> list[dict]:
    return [_cron_job_for_api(job) for job in (jobs or [])]


def _available_cron_profile_names() -> set[str]:
    from app.domain.profiles import list_profiles_api

    names = {"default"}
    for profile in list_profiles_api():
        try:
            name = str(profile.get("name") or "").strip()
        except AttributeError:
            continue
        if name:
            names.add(name)
    return names


def _normalize_cron_profile_value(value) -> str | None:
    if value is None:
        return None
    profile = str(value).strip()
    if not profile:
        return None
    if profile not in _available_cron_profile_names():
        raise ValueError(f"Unknown profile: {profile}")
    return profile


def _profile_home_for_cron_job(job: dict):
    """Resolve the execution profile for a cron job, with graceful fallback.

    A missing/blank profile preserves legacy server-default behavior. If a job
    points at a profile that was deleted after save, fall back to the active
    server profile and log a warning instead of crashing the Run Now path.
    """
    from app.domain.profiles import get_active_hermes_home, get_hermes_home_for_profile

    raw = str((job or {}).get("profile") or "").strip()
    if not raw:
        return get_active_hermes_home()
    if raw not in _available_cron_profile_names():
        logger.warning(
            "Cron job %s references missing profile %r; falling back to server default",
            (job or {}).get("id", "?"), raw,
        )
        return get_active_hermes_home()
    return get_hermes_home_for_profile(raw)


def _cron_job_subprocess_main(job, execution_profile_home, result_queue):
    """Run one cron job inside a child process pinned to a profile home."""
    try:
        def _run():
            from cron.scheduler import run_job

            return run_job(job)

        if execution_profile_home is None:
            result = _run()
        else:
            from app.domain.profiles import cron_profile_context_for_home

            with cron_profile_context_for_home(execution_profile_home):
                result = _run()
        result_queue.put(("ok", result))
    except BaseException as exc:  # pragma: no cover - surfaced in parent
        import traceback

        result_queue.put(("error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))


def _cron_subprocess_result_timeout_seconds(job):
    """Return how long the manual-run parent waits for child result payloads."""
    for key in ("timeout_seconds", "max_runtime_seconds", "timeout"):
        raw = (job or {}).get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return max(60.0, value + 30.0)
    # Manual cron jobs can legitimately run for a long time.  Keep a recovery
    # path for wedged children without truncating normal long-running jobs.
    return 6 * 60 * 60.0


def _run_cron_job_in_profile_subprocess(job, execution_profile_home):
    """Execute cron.scheduler.run_job without holding the parent cron env lock.

    cron.scheduler/cron.jobs still rely on process-global HERMES_HOME and module
    constants, so running the job body in a child process gives each long cron
    execution its own globals. The parent process only uses cron_profile_context
    for short metadata reads/writes and remains responsive to unrelated cron UI
    and API calls while the job runs.
    """
    import multiprocessing
    import queue

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_cron_job_subprocess_main,
        args=(job, execution_profile_home, result_queue),
    )
    process.start()

    result_timeout = _cron_subprocess_result_timeout_seconds(job)
    status = "error"
    payload = ["cron run subprocess failed before producing a result", ""]
    try:
        try:
            # Drain the potentially large pickled result before joining.  If the
            # child puts >~64 KiB on a multiprocessing.Queue, joining first can
            # deadlock while the child's feeder thread waits for the parent to
            # read from the pipe.
            status, *payload = result_queue.get(timeout=result_timeout)
        except queue.Empty:
            status = "error"
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                payload = [
                    f"cron run subprocess produced no result within {result_timeout:g}s and was terminated",
                    "",
                ]
            else:
                payload = [
                    f"cron run subprocess exited with code {process.exitcode} without producing a result",
                    "",
                ]
        finally:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if status == "ok":
                    status = "error"
                    payload = [
                        "cron run subprocess did not exit after returning a result",
                        "",
                    ]
    finally:
        result_queue.close()
        result_queue.join_thread()

    if status == "ok":
        return payload[0]

    message = payload[0]
    traceback_text = payload[1] if len(payload) > 1 else ""
    if traceback_text:
        logger.error("Manual cron subprocess failed:\n%s", traceback_text)
    raise RuntimeError(message)


def _run_cron_tracked(job, profile_home=None, execution_profile_home=None):
    """Wrapper that tracks running state around cron.scheduler.run_job.

    ``profile_home`` is the cron store that owns the job row/output metadata.
    ``execution_profile_home`` is the selected per-job profile used to load
    agent config/.env while running. When no job profile is selected, both homes
    are the same and legacy server-default behavior is preserved.
    """
    import importlib

    from cron.jobs import mark_job_run, save_job_output

    _cron_scheduler = importlib.import_module("cron.scheduler")

    _silent_marker = getattr(_cron_scheduler, "SILENT_MARKER", "[SILENT]")
    _deliver_result = getattr(_cron_scheduler, "_deliver_result", None)

    job_id = job.get("id", "")
    execution_profile_home = execution_profile_home or profile_home

    def _with_cron_home(home, fn):
        if home is None:
            return fn()
        from app.domain.profiles import cron_profile_context_for_home

        with cron_profile_context_for_home(home):
            return fn()

    try:
        success, output, final_response, error = _run_cron_job_in_profile_subprocess(
            job, execution_profile_home
        )

        # Persist output, deliver the same content the scheduled cron path would
        # send, and write run metadata back to the job's owning cron store even
        # when the selected execution profile is different.
        def _persist_success():
            save_job_output(job_id, output)

            deliver_content = (
                final_response
                if success
                else f"⚠️ Cron job '{job.get('name', job_id)}' failed:\n{error}"
            )
            should_deliver = bool(deliver_content)
            if should_deliver and success and _silent_marker in deliver_content.strip().upper():
                should_deliver = False

            delivery_error = None
            if should_deliver and _deliver_result is not None:
                try:
                    delivery_error = _deliver_result(job, deliver_content)
                except Exception as de:
                    delivery_error = str(de)
                    logger.error("Delivery failed for manual cron job %s: %s", job_id, de)

            # Match the scheduled cron path: an apparently successful run with no
            # final response should not leave the job looking healthy.
            _success, _error = success, error
            if _success and not final_response:
                _success = False
                _error = "Agent completed but produced empty response (model error, timeout, or misconfiguration)"

            try:
                mark_job_run(job_id, _success, _error, delivery_error=delivery_error)
            except TypeError:
                # Older/fake cron.jobs modules used by focused WebUI tests may
                # not expose the newer delivery_error parameter. Real Hermes
                # scheduler builds do, so this is only a compatibility shim for
                # legacy test doubles and deployments.
                mark_job_run(job_id, _success, _error)

        _with_cron_home(profile_home, _persist_success)
    except Exception as e:
        logger.exception("Manual cron run failed for job %s", job_id)
        try:
            _with_cron_home(profile_home, lambda: mark_job_run(job_id, False, str(e)))
        except Exception:
            logger.debug("Failed to mark manual cron run failure for %s", job_id)
    finally:
        _mark_cron_done(job_id)
        publish_session_list_changed("cron_complete")

_PROVIDER_ALIASES = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "google",
    "openai-codex": "openai",
}

# OpenAI-compatible /v1/models endpoints for live model discovery.
# Used as fallback when hermes_cli.provider_model_ids() is unavailable or
# returns [] for a provider (#871).  Kept at module level so the dict is
# built once, not reconstructed per request.
_OPENAI_COMPAT_ENDPOINTS = {
    "zai": "https://api.z.ai/v1",
    "minimax": "https://api.minimax.chat/v1",
    "mistralai": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}
# NOTE: "openai-codex" is excluded because it maps to the same endpoint as
# the base "openai" provider (api.openai.com/v1).  When both are configured
# the openai provider is already wired through provider_model_ids(); codex-
# specific model filtering happens downstream in hermes_cli.
#
_LIVE_MODELS_CACHE_TTL = 60.0
_LIVE_MODELS_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_LIVE_MODELS_CACHE_LOCK = threading.RLock()


def _active_profile_for_live_models_cache() -> str:
    try:
        from app.domain.profiles import get_active_profile_name

        return get_active_profile_name() or "default"
    except Exception as _e:
        # A transient profile-resolution error mis-scopes the cache for up to
        # 60s ("default" gets the wrong payload). Log so we can detect it; the
        # blast radius stays small because the TTL caps the bad-cache window.
        logger.debug("_active_profile_for_live_models_cache fell back to 'default': %s", _e)
        return "default"


def _live_models_cache_key(provider: str) -> tuple[str, str]:
    return (_active_profile_for_live_models_cache(), provider)


def _get_cached_live_models(key: tuple[str, str]) -> dict | None:
    now = time.monotonic()
    with _LIVE_MODELS_CACHE_LOCK:
        cached = _LIVE_MODELS_CACHE.get(key)
        if not cached:
            return None
        ts, payload = cached
        if now - ts >= _LIVE_MODELS_CACHE_TTL:
            _LIVE_MODELS_CACHE.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _set_cached_live_models(key: tuple[str, str], payload: dict) -> None:
    with _LIVE_MODELS_CACHE_LOCK:
        _LIVE_MODELS_CACHE[key] = (time.monotonic(), copy.deepcopy(payload))


def _clear_live_models_cache() -> None:
    with _LIVE_MODELS_CACHE_LOCK:
        _LIVE_MODELS_CACHE.clear()

from app.domain.config import (
    REPO_ROOT,
    STATE_DIR,
    SESSION_DIR,
    DEFAULT_WORKSPACE,
    DEFAULT_MODEL,
    SESSIONS,
    SESSIONS_MAX,
    LOCK,
    STREAMS,
    STREAMS_LOCK,
    CANCEL_FLAGS,
    STREAM_LAST_EVENT_ID,
    SERVER_START_TIME,
    _resolve_cli_toolsets,
    _INDEX_HTML_PATH,
    get_available_models,
    IMAGE_EXTS,
    MD_EXTS,
    MIME_MAP,
    MAX_FILE_BYTES,
    MAX_UPLOAD_BYTES,
    PREVIEW_MAX_BYTES,
    CHAT_LOCK,
    _get_session_agent_lock,
    SESSION_AGENT_LOCKS,
    SESSION_AGENT_LOCKS_LOCK,
    load_settings,
    save_settings,
    set_hermes_default_model,
    model_with_provider_context,
    get_reasoning_status,
    set_reasoning_display,
    set_reasoning_effort,
    create_stream_channel,
    get_webui_session_save_mode,
    STREAM_GOAL_RELATED,
    PENDING_GOAL_CONTINUATION,
    _get_config_path,
    _load_yaml_config_file,
    _save_yaml_config_file,
    reload_config,
    _cfg_lock,
)
from app.domain.helpers import (
    require,
    bad,
    safe_resolve,
    j,
    t,
    read_body,
    _security_headers,
    _sanitize_error,
    redact_session_data,
    _redact_text,
)
from app.domain.handlers import client_diagnostics as _client_diag

# Re-export client diagnostics symbols for legacy tests and admin_reload imports.
_CLIENT_EVENT_MAX_BODY_BYTES = _client_diag._CLIENT_EVENT_MAX_BODY_BYTES
_CLIENT_EVENT_RATE_LIMIT = _client_diag._CLIENT_EVENT_RATE_LIMIT
_CLIENT_EVENT_RATE_LIMIT_MAX = _client_diag._CLIENT_EVENT_RATE_LIMIT_MAX
_CSP_REPORT_RATE_LIMIT = _client_diag._CSP_REPORT_RATE_LIMIT
_CSP_REPORT_RATE_LIMIT_MAX = _client_diag._CSP_REPORT_RATE_LIMIT_MAX
_handle_csp_report = _client_diag.handle_csp_report
_handle_client_event_log = _client_diag.handle_client_event_log
_read_client_event_payload = _client_diag.read_client_event_payload
_sanitize_client_event_payload = _client_diag.sanitize_client_event_payload
from app.domain.agent_health import build_agent_health_payload
from app.domain.request_diagnostics import RequestDiagnostics
from app.domain.system_health import build_system_health_payload


def _kanban_unknown_endpoint(handler, parsed, method: str) -> bool:
    """Return a Kanban-specific 404 for stale clients/obsolete endpoint shapes."""
    return bad(
        handler,
        (
            f"unknown Kanban endpoint: {method} {parsed.path}. "
            "If this appeared after a WebUI update, your browser may be running "
            "a stale cached bundle; use Hard refresh now, then reopen Kanban."
        ),
        status=404,
    ) or True


def _clear_stale_stream_state(session) -> bool:
    """Clear persisted streaming flags when the in-memory stream no longer exists.

    A server restart or worker crash can leave active_stream_id/pending_* in the
    session JSON while STREAMS is empty. The frontend then keeps reconnecting to
    a dead stream and shows a permanent running/thinking state.

    SAFETY (#1558): If ``session`` was loaded with ``metadata_only=True``, its
    ``messages`` array is empty by design and calling ``save()`` would
    atomically overwrite the on-disk JSON, wiping the conversation. In that
    case we re-load the full session before mutating, so the persisted
    write carries the real messages forward.
    """
    stream_id = getattr(session, "active_stream_id", None)
    if not stream_id:
        return False
    with STREAMS_LOCK:
        stream_alive = stream_id in STREAMS
    if stream_alive:
        return False

    # ── #1558 P0 safety: if we were handed a metadata-only stub, reload the
    # full session before touching persisted state. The original
    # metadata-only object is left untouched so the caller's read path is
    # unaffected.
    original_stub = session  # SHOULD-FIX #1 (Opus): keep reference so we can
                             # patch the caller's in-memory copy after a
                             # successful clear, avoiding one ghost SSE
                             # reconnect on the very next /api/session GET.
    if getattr(session, "_loaded_metadata_only", False):
        try:
            from app.domain.models import get_session as _get_session
            session = _get_session(session.session_id, metadata_only=False)
        except Exception:
            # If we cannot upgrade to a full load (file gone, decode error,
            # etc.) bail without clearing — better to leave a stale
            # active_stream_id than to wipe the conversation.
            logger.warning(
                "_clear_stale_stream_state: refused to clear stale stream %s "
                "for session %s — full reload failed and we will not save a "
                "metadata-only stub. See #1558.",
                stream_id, getattr(session, "session_id", "?"),
            )
            return False
        if session is None:
            return False
        # The full-load path may have already repaired stale pending fields
        # via _repair_stale_pending(); only re-assert if still set.
        if not getattr(session, "active_stream_id", None):
            # Patch the caller's stub so its read path also sees the cleared
            # field (matches the Opus SHOULD-FIX #1 — without this, /api/session
            # would briefly return the stale active_stream_id and the frontend
            # would attempt one ghost SSE reconnect before recovering).
            try:
                original_stub.active_stream_id = None
                if hasattr(original_stub, "pending_user_message"):
                    original_stub.pending_user_message = None
                if hasattr(original_stub, "pending_attachments"):
                    original_stub.pending_attachments = []
                if hasattr(original_stub, "pending_started_at"):
                    original_stub.pending_started_at = None
            except Exception:
                pass
            return False

    # ── #1533 race fix: acquire the per-session lock and re-read
    # active_stream_id under it. A concurrent chat_start may have already
    # registered a new stream after our STREAMS_LOCK check above; in that
    # case we must NOT clobber its session.active_stream_id.
    with _get_session_agent_lock(session.session_id):
        if getattr(session, "active_stream_id", None) != stream_id:
            return False
        if getattr(session, "pending_user_message", None):
            try:
                from app.domain.models import _apply_core_sync_or_error_marker, _get_profile_home
                profile_home = _get_profile_home(getattr(session, "profile", None))
                core_path = profile_home / "sessions" / f"session_{session.session_id}.json"
                repaired = _apply_core_sync_or_error_marker(
                    session,
                    core_path,
                    stream_id_for_recheck=stream_id,
                    touch_updated_at=False,
                )
            except Exception:
                logger.exception(
                    "_clear_stale_stream_state: failed to repair stale pending stream %s "
                    "for session %s",
                    stream_id, getattr(session, "session_id", "?"),
                )
                repaired = False
            if repaired:
                if original_stub is not session:
                    try:
                        original_stub.active_stream_id = None
                        if hasattr(original_stub, "pending_user_message"):
                            original_stub.pending_user_message = None
                        if hasattr(original_stub, "pending_attachments"):
                            original_stub.pending_attachments = []
                        if hasattr(original_stub, "pending_started_at"):
                            original_stub.pending_started_at = None
                    except Exception:
                        pass
                return True
            if getattr(session, "active_stream_id", None) != stream_id:
                return False
        _materialize_pending_user_turn_before_error(session)
        session.active_stream_id = None
        if hasattr(session, "pending_user_message"):
            session.pending_user_message = None
        if hasattr(session, "pending_attachments"):
            session.pending_attachments = []
        if hasattr(session, "pending_started_at"):
            session.pending_started_at = None
        try:
            # Runtime cleanup is not user activity; do not bubble old sessions
            # to the top of the sidebar just because a stale stream flag was
            # repaired during a read/list path.
            session.save(touch_updated_at=False)
        except Exception:
            logger.exception(
                "_clear_stale_stream_state: save() failed for session %s",
                getattr(session, "session_id", "?"),
            )
    # Patch the caller's stub (if different from the full-load object) so
    # its in-memory active_stream_id matches what just got persisted.
    if original_stub is not session:
        try:
            original_stub.active_stream_id = None
            if hasattr(original_stub, "pending_user_message"):
                original_stub.pending_user_message = None
            if hasattr(original_stub, "pending_attachments"):
                original_stub.pending_attachments = []
            if hasattr(original_stub, "pending_started_at"):
                original_stub.pending_started_at = None
        except Exception:
            pass
    return True


def _run_journal_status_payload(summary: dict, *, active: bool = False) -> dict:
    from app.domain.chat_streaming import run_journal_status_payload

    return run_journal_status_payload(summary, active=active)


def _ensure_full_session_before_mutation(sid: str, session):
    """Reload cached metadata-only sessions before mutating persisted fields.

    Session.save() intentionally refuses metadata-only stubs (#1558) because
    their messages list is empty by design. Mutation routes that save session
    metadata must upgrade the cached stub first so they do not trip that guard
    or risk writing an incomplete object.
    """
    if not getattr(session, "_loaded_metadata_only", False):
        return session
    full_session = Session.load(sid)
    if full_session is None:
        raise KeyError(sid)
    with LOCK:
        SESSIONS[sid] = full_session
        SESSIONS.move_to_end(sid)
        while len(SESSIONS) > SESSIONS_MAX:
            SESSIONS.popitem(last=False)
    return full_session


# ── CSRF: validate Origin/Referer on POST ────────────────────────────────────
import re as _re


def _normalize_host_port(value: str) -> tuple[str, str | None]:
    """Split a host or host:port string into (hostname, port|None).
    Handles IPv6 bracket notation, e.g. [::1]:8080."""
    value = value.strip().lower()
    if not value:
        return '', None
    if value.startswith('['):
        end = value.find(']')
        if end != -1:
            host = value[1:end]
            rest = value[end + 1 :]
            if rest.startswith(':') and rest[1:].isdigit():
                return host, rest[1:]
            return host, None
    if value.count(':') == 1:
        host, port = value.rsplit(':', 1)
        if port.isdigit():
            return host, port
    return value, None


def _ports_match(origin_scheme: str, origin_port: str | None, allowed_port: str | None) -> bool:
    """Return True when two ports should be considered equivalent, scheme-aware.

    Treats an absent port as the scheme default: port 80 for http, port 443 for https.
    Port 80 is NOT treated as equivalent to 443 (different protocols = different origins).
    """
    if origin_port == allowed_port:
        return True
    # Determine the default port for the origin's scheme
    default = '443' if origin_scheme == 'https' else '80'
    if not origin_port and allowed_port == default:
        return True
    if not allowed_port and origin_port == default:
        return True
    return False


def _allowed_public_origins() -> set[str]:
    """Parse HERMES_WEBUI_ALLOWED_ORIGINS env var (comma-separated) into a set.

    Each entry must include the scheme, e.g. https://myapp.example.com:8000.
    Entries without a scheme are silently skipped and a warning is printed.
    """
    raw = os.getenv('HERMES_WEBUI_ALLOWED_ORIGINS', '')
    result = set()
    for value in raw.split(','):
        value = value.strip().rstrip('/').lower()
        if not value:
            continue
        if not (value.startswith('http://') or value.startswith('https://')):
            import sys
            print(
                f"[webui] WARNING: HERMES_WEBUI_ALLOWED_ORIGINS entry {value!r} is missing "
                f"the scheme (expected https://hostname or http://hostname). Entry ignored.",
                flush=True, file=sys.stderr,
            )
            continue
        result.add(value)
    return result


def _is_browser_unsafe_request(handler) -> bool:
    """Return True when request headers identify a browser unsafe request.

    Non-browser API clients, including the MCP bridge and curl-style scripts,
    normally send no Origin/Referer and remain compatible with the existing
    same-machine API contract. Browsers send Origin for unsafe fetch/form POSTs;
    Referer is retained for older paths and proxies.
    """
    return bool(handler.headers.get("Origin") or handler.headers.get("Referer"))


def _csrf_exempt_path(path: str) -> bool:
    """Paths that cannot or must not carry a session CSRF token."""
    return path in {
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/passkey/options",
        "/api/auth/passkey/login",
        "/api/v1/system/bootstrap-admin",
        "/api/csp-report",
    }


_CSRF_FAILURE_ATTR = "_hermes_csrf_failure_reason"


def _set_csrf_failure_reason(handler, reason: str) -> bool:
    try:
        setattr(handler, _CSRF_FAILURE_ATTR, reason)
    except Exception:
        pass
    return False


def _clear_csrf_failure_reason(handler) -> None:
    try:
        if hasattr(handler, _CSRF_FAILURE_ATTR):
            delattr(handler, _CSRF_FAILURE_ATTR)
    except Exception:
        pass


def _csrf_rejection_error(handler) -> str:
    reason = getattr(handler, _CSRF_FAILURE_ATTR, "")
    if reason == "origin_mismatch":
        return "Cross-origin mismatch - check reverse proxy headers"
    if reason == "token_mismatch":
        return "Session expired - reload the page"
    return "Cross-origin request rejected"


def _check_csrf(handler) -> bool:
    """Reject cross-origin or tokenless authenticated browser unsafe requests."""
    _clear_csrf_failure_reason(handler)
    origin = handler.headers.get("Origin", "")
    referer = handler.headers.get("Referer", "")
    host = handler.headers.get("Host", "")
    if not _is_browser_unsafe_request(handler):
        return True  # non-browser clients (curl, MCP, agent) have no Origin
    target = origin or referer
    # Extract host:port from origin/referer
    m = _re.match(r"^https?://([^/]+)", target)
    if not m:
        return _set_csrf_failure_reason(handler, "origin_mismatch")
    origin_host = m.group(1)
    origin_scheme = m.group(0).split('://')[0].lower()  # 'http' or 'https'
    origin_name, origin_port = _normalize_host_port(origin_host)
    origin_allowed = False
    # Check against explicitly allowed public origins (env var)
    origin_value = m.group(0).rstrip('/').lower()
    if origin_value in _allowed_public_origins():
        origin_allowed = True
    if not origin_allowed:
        # Allow same-origin: check Host, X-Forwarded-Host (reverse proxy), and
        # X-Real-Host against the origin. Reverse proxies (Caddy, nginx) set
        # X-Forwarded-Host to the client's original Host header.
        allowed_hosts = [
            h.strip()
            for h in [
                host,
                handler.headers.get("X-Forwarded-Host", ""),
                handler.headers.get("X-Real-Host", ""),
            ]
            if h.strip()
        ]
        for allowed in allowed_hosts:
            allowed_name, allowed_port = _normalize_host_port(allowed)
            if origin_name == allowed_name and _ports_match(origin_scheme, origin_port, allowed_port):
                origin_allowed = True
                break
    if not origin_allowed:
        return _set_csrf_failure_reason(handler, "origin_mismatch")

    from app.domain.auth import (
        CSRF_HEADER_NAME,
        is_auth_enabled,
        parse_bearer_authorization,
        parse_cookie,
        verify_csrf_token,
        verify_session,
    )

    if not is_auth_enabled():
        return True
    bearer = parse_bearer_authorization(handler.headers.get("Authorization"))
    if bearer and verify_session(bearer):
        return True
    if bearer:
        try:
            from app.domain.mcp_auth import is_valid_mcp_bearer

            if is_valid_mcp_bearer(bearer):
                return True
        except Exception:
            pass
    cookie_val = parse_cookie(handler)
    submitted = handler.headers.get(CSRF_HEADER_NAME) or handler.headers.get("X-CSRF-Token")
    if verify_csrf_token(cookie_val or "", submitted or ""):
        return True
    return _set_csrf_failure_reason(handler, "token_mismatch")


def _normalize_provider_id(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[raw]
    for prefix, normalized in (
        ("openai-codex", "openai"),
        ("openai", "openai"),
        ("anthropic", "anthropic"),
        ("claude", "anthropic"),
        ("google", "google"),
        ("gemini", "google"),
        ("openrouter", "openrouter"),
        ("custom", "custom"),
    ):
        if raw.startswith(prefix):
            return normalized
    # Unknown prefix — return empty so callers treat it as "no match" and pass
    # the model through unchanged rather than incorrectly stripping it.
    return "" 


def _catalog_provider_id_sets(catalog: dict) -> tuple[set[str], set[str]]:
    raw_provider_ids: set[str] = set()
    normalized_provider_ids: set[str] = set()
    for group in catalog.get("groups") or []:
        raw = str(group.get("provider_id") or "").strip().lower()
        if not raw:
            continue
        raw_provider_ids.add(raw)
        normalized = _normalize_provider_id(raw)
        if normalized:
            normalized_provider_ids.add(normalized)
    return raw_provider_ids, normalized_provider_ids


def _catalog_has_provider(
    provider_raw: str,
    provider_normalized: str,
    raw_provider_ids: set[str],
    normalized_provider_ids: set[str],
) -> bool:
    return (
        provider_raw in raw_provider_ids
        or (provider_normalized and provider_normalized in raw_provider_ids)
        or (provider_normalized and provider_normalized in normalized_provider_ids)
    )


def _model_matches_active_provider_family(
    model: str,
    active_provider: str,
) -> bool:
    model_lower = model.lower()
    for bare_prefix in ("gpt", "claude", "gemini"):
        if model_lower.startswith(bare_prefix):
            return _normalize_provider_id(bare_prefix) == active_provider
    return False


def _catalog_model_id_matches(candidate: str, model: str) -> bool:
    candidate = str(candidate or "").strip()
    if candidate.startswith("@") and ":" in candidate:
        candidate = candidate.rsplit(":", 1)[1]
    if "/" in candidate:
        candidate = candidate.split("/", 1)[1]
    return candidate.replace("-", ".").lower() == model.replace("-", ".").lower()


def _clean_session_model_provider(value: str | None) -> str | None:
    provider = str(value or "").strip().lower()
    if not provider or provider == "default":
        return None
    if provider.startswith("@"):
        provider = provider[1:]
    return provider or None


def _split_provider_qualified_model(model: str) -> tuple[str, str | None]:
    model = str(model or "").strip()
    if model.startswith("@") and ":" in model:
        provider_hint, bare_model = model[1:].rsplit(":", 1)
        provider = _clean_session_model_provider(provider_hint)
        bare = bare_model.strip()
        if provider and bare:
            return bare, provider
    return model, None


def _should_attach_codex_provider_context(model: str, raw_active_provider: str, catalog: dict) -> bool:
    """Return True when a bare Codex model needs separate provider context.

    OpenAI, OpenAI Codex, Copilot, and OpenRouter can all expose GPT-looking
    bare names. If a session stores only ``gpt-...`` while Codex is active, a
    later provider-list/default-model round trip can lose the user's Codex
    choice. Store the provider separately instead of converting the persisted
    model to ``@openai-codex:model``.
    """
    if raw_active_provider != "openai-codex":
        return False
    if not model.lower().startswith("gpt"):
        return False
    for group in catalog.get("groups") or []:
        if str(group.get("provider_id") or "").strip().lower() != "openai-codex":
            continue
        return any(
            _catalog_model_id_matches(entry.get("id"), model)
            for entry in group.get("models", [])
            if isinstance(entry, dict)
        )
    return False


def _resolve_compatible_session_model_state(
    model_id: str | None,
    model_provider: str | None = None,
) -> tuple[str, str | None, bool]:
    """Return (effective_model, effective_provider, model_was_normalized).

    Sessions can outlive provider changes. When an older session still points at
    a different provider namespace (for example `gemini/...` after switching the
    agent to OpenAI Codex), reusing that stale model causes chat startup to hit
    the wrong backend and fail. Normalize only obvious cross-provider mismatches.
    When a model has an explicit provider context, keep the model string itself
    in its picker/API shape and carry the provider as separate state.

    Fast path (#1855): when the caller supplies both a model and an explicit
    ``model_provider`` AND the model is not itself ``@provider:model``-qualified,
    we can return the inputs verbatim without calling ``get_available_models()``.
    The slow path below would arrive at the same answer via
    ``if requested_provider and not explicit_provider: return model, requested_provider, False``
    after paying the full catalog-build cost. Avoiding the catalog here keeps
    ``POST /api/chat/start`` snappy even when the model catalog is cold and the
    rebuild has to make network calls (custom OpenAI-compat endpoints,
    OpenRouter ``/models``, LM Studio ``/models``, credential pool refresh) —
    those used to wedge the handler for >100s and trigger 502s on default-60s
    reverse proxies, even though the WebUI itself eventually responded.
    """
    model = str(model_id or "").strip()
    requested_provider = _clean_session_model_provider(model_provider)
    if model and requested_provider:
        # Only safe when the model itself does not carry an ``@provider:model``
        # qualifier — qualified strings require the catalog to decide whether
        # the qualifier matches the active provider (see slow path below).
        bare_model, explicit_provider = _split_provider_qualified_model(model)
        model_prefix = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        stale_codex_openai_slash_id = (
            requested_provider == "openai-codex"
            and model_prefix == "openai"
        )
        if not explicit_provider and not stale_codex_openai_slash_id:
            return model, requested_provider, False

    catalog = get_available_models()
    default_model = str(catalog.get("default_model") or DEFAULT_MODEL or "").strip()
    if not model:
        return default_model, requested_provider, bool(default_model)

    active_provider = _normalize_provider_id(catalog.get("active_provider"))
    # Also keep the raw active_provider slug for cross-provider detection with
    # non-listed providers (ollama-cloud, deepseek, xai, etc.) that _normalize_provider_id
    # returns "" for. If the raw provider is set but normalization returned "", we still
    # want to detect that a session model from a known provider (e.g. openai/gpt-5.4-mini)
    # is stale relative to this unknown active provider. (#1023)
    raw_active_provider = str(catalog.get("active_provider") or "").strip().lower()
    if not active_provider and not raw_active_provider:
        bare_model, explicit_provider = _split_provider_qualified_model(model)
        return model, explicit_provider or requested_provider, False

    bare_for_context, explicit_provider = _split_provider_qualified_model(model)
    if requested_provider and not explicit_provider:
        model_prefix = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        stale_codex_openai_slash_id = (
            raw_active_provider == "openai-codex"
            and requested_provider == "openai-codex"
            and model_prefix == "openai"
        )
        if not stale_codex_openai_slash_id:
            return model, requested_provider, False

    if model.startswith("@") and ":" in model:
        provider_raw = explicit_provider or ""
        provider_normalized = _normalize_provider_id(provider_raw)
        bare_model = bare_for_context.strip()
        if not provider_raw or not bare_model:
            return model, requested_provider, False

        raw_provider_ids, normalized_provider_ids = _catalog_provider_id_sets(catalog)
        hint_matches_active = (
            provider_raw == raw_active_provider
            or provider_raw == active_provider
            or (provider_normalized and provider_normalized == active_provider)
        )
        if hint_matches_active:
            # The @provider:model hint explicitly names the active provider, so this
            # selection is intentional — not a stale cross-provider artifact. Return
            # the full @provider:model string unchanged so downstream (resolve_model_provider
            # in config.py) can route through the correct provider. Stripping the prefix
            # here would collapse duplicate model IDs from different providers back to the
            # bare ID, causing the first matching provider to win on the next UI render
            # and the wrong provider to be used for the agent run. (#1253)
            return model, provider_raw, False

        if _catalog_has_provider(
            provider_raw,
            provider_normalized,
            raw_provider_ids,
            normalized_provider_ids,
        ):
            return model, provider_raw, False

        if _model_matches_active_provider_family(bare_model, active_provider):
            provider_context = (
                raw_active_provider
                if _should_attach_codex_provider_context(bare_model, raw_active_provider, catalog)
                else None
            )
            return bare_model, provider_context, True
        if default_model:
            provider_context = (
                raw_active_provider
                if _should_attach_codex_provider_context(default_model, raw_active_provider, catalog)
                else None
            )
            return default_model, provider_context, True
        return model, provider_raw, False

    slash = model.find("/")
    if slash < 0:
        model_lower = model.lower()
        for bare_prefix in ("gpt", "claude", "gemini"):
            if model_lower.startswith(bare_prefix):
                model_provider = _normalize_provider_id(bare_prefix)
                if model_provider and model_provider != active_provider and default_model:
                    provider_context = (
                        raw_active_provider
                        if _should_attach_codex_provider_context(default_model, raw_active_provider, catalog)
                        else None
                    )
                    return default_model, provider_context, True
                provider_context = (
                    raw_active_provider
                    if _should_attach_codex_provider_context(model, raw_active_provider, catalog)
                    else requested_provider
                )
                return model, provider_context, False
        return model, requested_provider, False

    model_provider = _normalize_provider_id(model[:slash])

    # For custom/openrouter active providers: only skip normalization when the
    # model's namespace prefix is actually routable by a group in the catalog.
    # A user who only has custom_providers configured (active_provider="custom")
    # with a stale session model like "openai/gpt-5.4-mini" would otherwise
    # never get cleaned up, causing "(unavailable)" to appear in the picker.
    if active_provider in {"custom", "openrouter"}:
        # These namespaces are always routable as-is — preserve them.
        if model_provider in {"", "custom", "openrouter"}:
            return model, requested_provider, False
        # Check if any catalog group can actually route this model's prefix.
        groups = catalog.get("groups") or []
        routable_provider_ids = {
            _normalize_provider_id(g.get("provider_id") or "") for g in groups
        }
        # openrouter group can route any provider/model namespace
        has_openrouter_group = any(
            (g.get("provider_id") or "") == "openrouter" for g in groups
        )
        if model_provider in routable_provider_ids or has_openrouter_group:
            return model, requested_provider, False
        # Model prefix is not routable — stale cross-provider reference, clear it.
        if default_model:
            return default_model, requested_provider, True
        return model, requested_provider, False

    # Skip normalization for models on custom/openrouter namespaces — these are
    # user-controlled and should never be silently replaced.
    #
    # OpenAI Codex is intentionally normalized to the OpenAI family above so bare
    # GPT IDs survive provider switches. Slash-qualified OpenAI IDs are different:
    # ``openai/gpt-...`` is the OpenRouter shape for OpenAI models, and
    # resolve_model_provider() routes that through OpenRouter when Codex is the
    # configured provider. Legacy sessions can carry that stale slash ID without
    # a saved model_provider, so repair it to the active Codex default unless the
    # session/request explicitly says it is an OpenRouter selection. (#1734)
    if (
        raw_active_provider == "openai-codex"
        and model_provider == "openai"
        and requested_provider in {None, "openai-codex"}
        and default_model
    ):
        # Persist provider_context = "openai-codex" unconditionally on this
        # repair path so the resolved shape is stable across resolutions
        # (Opus stage-303 SHOULD-FIX: avoid redundant repair-writes per
        # chat-start when the catalog-coverage check fails — e.g. if a
        # future Codex default is itself slash-prefixed). Once we've
        # decided the session belongs to Codex, persist that decision.
        return default_model, raw_active_provider, True

    # Also normalize when the model is from a known provider but the active provider
    # is an unlisted one (e.g. ollama-cloud) — active_provider is "" in that case
    # but raw_active_provider is set. If model_provider doesn't start with the raw
    # active provider name, the session model is stale. (#1023)
    _active_for_compare = active_provider or raw_active_provider
    if model_provider and model_provider not in {"", "custom", "openrouter"} and model_provider != _active_for_compare and default_model:
        return default_model, requested_provider, True
    return model, requested_provider, False


def _resolve_compatible_session_model(model_id: str | None) -> tuple[str, bool]:
    """Return (effective_model, model_was_normalized) for legacy callers."""
    effective_model, _provider, changed = _resolve_compatible_session_model_state(model_id)
    return effective_model, changed


def _normalize_session_model_in_place(session) -> str:
    original_model = getattr(session, "model", None) or ""
    original_provider = _clean_session_model_provider(
        getattr(session, "model_provider", None)
    )
    effective_model, effective_provider, changed = _resolve_compatible_session_model_state(
        original_model or None,
        original_provider,
    )
    provider_changed = effective_provider != original_provider
    # Only persist the correction if the session had an explicit model that needed changing.
    # Sessions with no model stored (empty/None) get the effective default returned without
    # a disk write — no need to rebuild the index for a fill-in-blank operation.
    if original_model and effective_model and (
        (changed and original_model != effective_model) or provider_changed
    ):
        if changed and original_model != effective_model:
            session.model = effective_model
        session.model_provider = effective_provider
        session.save(touch_updated_at=False)
    return effective_model


def _resolve_effective_session_model_for_display(session) -> str:
    """Resolve the model a session should display without mutating persisted state.

    `GET /api/session` should stay side-effect free. If a stale persisted model
    needs normalization for the current provider configuration, return the
    effective model for the response payload only and leave disk state alone.
    """
    original_model = getattr(session, "model", None) or ""
    effective_model, _provider, _changed = _resolve_compatible_session_model_state(
        original_model or None,
        getattr(session, "model_provider", None),
    )
    return effective_model or original_model

def _resolve_effective_session_model_provider_for_display(session) -> str | None:
    original_model = getattr(session, "model", None) or ""
    _model, provider, _changed = _resolve_compatible_session_model_state(
        original_model or None,
        getattr(session, "model_provider", None),
    )
    return provider


def _resolve_context_length_for_session_model(
    model: str | None,
    provider: str | None = None,
) -> int:
    """Best-effort current context window for a session model.

    Persisted session context metadata is a snapshot from a prior model call.
    During session hydration/model switching, the current model metadata should
    be allowed to replace that stale snapshot.
    """
    model_for_lookup = str(model or "").strip()
    if not model_for_lookup:
        return 0
    try:
        from agent.model_metadata import get_model_context_length as _get_cl
        from app.domain.config import get_config as _get_config_for_cl

        _cfg_for_cl = _get_config_for_cl()
        _cfg_ctx_len_load = None
        _cfg_custom_providers_load = None
        try:
            _model_cfg_load = _cfg_for_cl.get('model', {}) if isinstance(_cfg_for_cl, dict) else {}
            if isinstance(_model_cfg_load, dict):
                _raw_cfg_ctx_load = _model_cfg_load.get('context_length')
                if _raw_cfg_ctx_load is not None:
                    try:
                        _parsed_load = int(_raw_cfg_ctx_load)
                        if _parsed_load > 0:
                            _cfg_ctx_len_load = _parsed_load
                    except (TypeError, ValueError):
                        pass
            _raw_cp_load = _cfg_for_cl.get('custom_providers') if isinstance(_cfg_for_cl, dict) else None
            if isinstance(_raw_cp_load, list):
                _cfg_custom_providers_load = _raw_cp_load
        except Exception:
            pass
        try:
            return _get_cl(
                model_for_lookup,
                "",
                config_context_length=_cfg_ctx_len_load,
                provider=provider or "",
                custom_providers=_cfg_custom_providers_load,
            ) or 0
        except TypeError:
            # Older hermes-agent builds: legacy 2-arg form.
            return _get_cl(model_for_lookup, "") or 0
    except Exception:
        return 0


def _session_model_state_from_request(
    model: str | None,
    requested_provider: str | None,
    current_provider: str | None = None,
) -> tuple[str | None, str | None]:
    model_value = str(model).strip() if model is not None else None
    provider = (
        _clean_session_model_provider(requested_provider)
        if requested_provider is not None
        else None
    )
    if model_value:
        _bare, explicit_provider = _split_provider_qualified_model(model_value)
        if explicit_provider:
            provider = explicit_provider
        elif requested_provider is None:
            provider = _clean_session_model_provider(current_provider)
        model_value, provider, _changed = _resolve_compatible_session_model_state(
            model_value,
            provider,
        )
    return model_value, provider


def _lookup_gateway_session_identity(session_id: str) -> dict:
    if not session_id:
        return {}
    metadata = _load_gateway_session_identity_map().get(str(session_id))
    return metadata if isinstance(metadata, dict) else {}


def _lookup_cli_session_metadata(session_id: str) -> dict:
    if not session_id:
        return {}
    try:
        for row in get_cli_sessions():
            if row.get("session_id") == session_id:
                return row
    except Exception:
        return {}
    return {}


def _messaging_session_identity(session: dict, raw_source: str) -> str:
    metadata = _lookup_gateway_session_identity(session.get("session_id"))
    session_key = _safe_first(
        metadata.get("session_key"),
        session.get("session_key"),
        session.get("gateway_session_key"),
    )
    if session_key:
        return f"{raw_source}|session_key:{session_key}"

    chat_id = _safe_first(
        metadata.get("chat_id"),
        session.get("chat_id"),
        session.get("origin_chat_id"),
    )
    thread_id = _safe_first(metadata.get("thread_id"), session.get("thread_id"))
    chat_type = _safe_first(metadata.get("chat_type"), session.get("chat_type"))
    user_id = _safe_first(
        metadata.get("user_id"),
        session.get("user_id"),
        session.get("origin_user_id"),
    )

    identity_parts = []
    if chat_type:
        identity_parts.append(f"chat_type:{chat_type}")
    if chat_id:
        identity_parts.append(f"chat_id:{chat_id}")
    if thread_id:
        identity_parts.append(f"thread_id:{thread_id}")
    if user_id:
        identity_parts.append(f"user_id:{user_id}")

    if identity_parts:
        return f"{raw_source}|" + "|".join(identity_parts)
    return raw_source


def _session_messaging_raw_source(session: dict) -> str:
    raw = _safe_first(
        session.get("raw_source"),
        session.get("source_tag"),
        session.get("source"),
        session.get("platform"),
    )
    if not raw:
        raw = session.get("source_label") or "messaging"
    return _normalize_messaging_source(raw)


def _has_durable_messaging_identity(session: dict) -> bool:
    metadata = _lookup_gateway_session_identity(session.get("session_id"))
    return bool(_safe_first(
        metadata.get("session_key"),
        session.get("session_key"),
        session.get("gateway_session_key"),
        metadata.get("chat_id"),
        session.get("chat_id"),
        session.get("origin_chat_id"),
        metadata.get("thread_id"),
        session.get("thread_id"),
    ))


def _numeric_count(value) -> int:
    try:
        return int(float(_safe_first(value, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _should_hide_stale_messaging_session(
    session: dict,
    active_gateway_session_ids: set[str],
    active_gateway_sources: set[str],
) -> bool:
    """Hide stale Gateway-owned internal rows after an external chat moved on.

    Hermes Gateway keeps the external conversation identity in sessions.json.
    Compression/session-reset can leave old Agent state.db rows behind; those
    rows are implementation segments, not distinct conversations users chose.
    Only apply this aggressive hiding when Gateway is currently advertising an
    active session for the same messaging source. Without that source-of-truth
    file we keep the old fallback behavior.
    """
    raw_source = _session_messaging_raw_source(session)
    if not _is_known_messaging_source(raw_source):
        return False
    if not active_gateway_session_ids or raw_source not in active_gateway_sources:
        return False

    sid = _safe_first(session.get("session_id"))
    if sid and sid in active_gateway_session_ids:
        return False

    if _safe_first(session.get("end_reason")) in _STALE_MESSAGING_END_REASONS:
        return True

    if not _has_durable_messaging_identity(session):
        return True

    if session.get("parent_session_id"):
        return True

    message_count = _numeric_count(session.get("message_count"))
    actual_count = _numeric_count(session.get("actual_message_count"))
    if message_count <= 0 and actual_count <= 0:
        return True

    return False


def _is_messaging_session_record(session) -> bool:
    """Return true for sessions backed by external messaging channels."""
    if not session:
        return False
    if (
        (getattr(session, "session_source", None) if not isinstance(session, dict) else session.get("session_source")) == "messaging"
    ):
        return True
    raw = _safe_first(
        getattr(session, "raw_source", None) if not isinstance(session, dict) else session.get("raw_source"),
        getattr(session, "source_tag", None) if not isinstance(session, dict) else session.get("source_tag"),
        getattr(session, "source", None) if not isinstance(session, dict) else session.get("source"),
        session.get("source_label") if isinstance(session, dict) else None,
    )
    return _is_known_messaging_source(raw)


def _messages_include_tool_metadata(messages) -> bool:
    """Return true when returned messages can reconstruct their own tool cards."""
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if isinstance(msg.get("tool_calls"), list) and msg.get("tool_calls"):
            return True
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "tool_use"
            for part in content
        ):
            return True
    return False


def _tool_calls_for_message_window(tool_calls, start_idx: int, message_count: int) -> list:
    """Keep session-level tool calls that point into a returned message window."""
    if not isinstance(tool_calls, list) or message_count <= 0:
        return []
    end_idx = start_idx + message_count
    filtered = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        assistant_idx = tool_call.get("assistant_msg_idx")
        if isinstance(assistant_idx, bool) or not isinstance(assistant_idx, int):
            continue
        if start_idx <= assistant_idx < end_idx:
            filtered.append(tool_call)
    return filtered


def _message_counts_as_renderable_for_window(message) -> bool:
    """Return true when a paginated window should include this transcript row.

    Tool result rows are rendered through their assistant anchor or hidden as raw
    tool output. A tail page containing only tool rows makes the frontend set
    ``S.messages`` to a non-empty array while the visible transcript and topbar
    count stay empty. Anchor small tail windows on the newest non-tool row so
    long sessions do not open to a blank chat with only transient metadata.
    """
    if not isinstance(message, dict):
        return False
    role = str(message.get("role") or "").strip().lower()
    return bool(role and role != "tool")


def _message_window_for_display(messages, msg_limit=None, msg_before=None) -> tuple[list, int]:
    """Return a paginated message window plus its offset in ``messages``.

    The normal fast path is a raw tail window. If that window contains no
    renderable transcript rows because state.db appended hidden tool rows after
    the visible assistant tail, shift the window end back to the newest
    renderable row. This preserves the raw index cursor while avoiding the
    WebUI blank-transcript trap.
    """
    messages = list(messages or [])
    if msg_before is not None:
        before_idx = max(0, min(int(msg_before), len(messages)))
    else:
        before_idx = len(messages)
    source = messages[:before_idx]
    if not source:
        return [], 0
    if not msg_limit:
        return source, 0
    limit = max(1, int(msg_limit))
    end_idx = len(source)
    start_idx = max(0, end_idx - limit)
    window = source[start_idx:end_idx]
    if window and not any(_message_counts_as_renderable_for_window(msg) for msg in window):
        for idx in range(end_idx - 1, -1, -1):
            if _message_counts_as_renderable_for_window(source[idx]):
                end_idx = idx + 1
                start_idx = max(0, end_idx - limit)
                window = source[start_idx:end_idx]
                break
    return window, start_idx


def _merged_session_messages_for_display(session, cli_messages=None) -> list:
    """Return the message coordinate space exposed by ``GET /api/session``.

    Messaging sessions can have a WebUI sidecar transcript plus messages from
    the Agent/CLI store. The frontend computes fork keep-counts against this
    merged display list, so branch/fork must slice the same list rather than
    the sidecar-only ``session.messages`` array.
    """
    from app.domain.streaming import _remap_message_for_display

    def _display_messages(rows):
        remapped = []
        for msg in rows or []:
            mapped = _remap_message_for_display(msg)
            if mapped is not None:
                remapped.append(mapped)
        return remapped

    cli_messages = list(cli_messages or [])
    sidecar_messages = list(getattr(session, "messages", []) or [])
    if cli_messages:
        if sidecar_messages and sidecar_messages != cli_messages:
            merged_messages = []
            seen_message_keys = set()
            for msg in sorted(list(cli_messages) + list(sidecar_messages), key=lambda m: (
                float(m.get("timestamp") or 0),
                str(m.get("role") or ""),
                str(m.get("content") or ""),
            )):
                key = _session_message_merge_key(msg)
                if key in seen_message_keys:
                    continue
                seen_message_keys.add(key)
                merged_messages.append(msg)
            return _display_messages(merged_messages)
        chosen = sidecar_messages if len(sidecar_messages) > len(cli_messages) else cli_messages
        return _display_messages(chosen)
    return _display_messages(sidecar_messages)


def _message_summary(messages) -> dict:
    messages = list(messages or [])
    last_message_at = 0.0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        try:
            last_message_at = max(last_message_at, float(msg.get("timestamp") or 0))
        except (TypeError, ValueError):
            pass
    return {"message_count": len(messages), "last_message_at": last_message_at}


def _metadata_only_message_summary(sid: str, profile: str | None = None) -> dict:
    """Return the cheap message summary used by metadata-only session loads.

    Threads ``profile=`` through to ``get_state_db_session_summary`` so
    background-thread reads land on the correct profile's state.db (per the
    cookie-bound profile selector — fixes the same TLS-vs-thread race the
    #2762 fix addressed for write paths).

    This intentionally does not full-read or merge transcripts.  If state.db has
    grown beyond the sidecar count, report that growth so active-session polling
    can refresh.  If state.db only contains restamped replay rows at or below the
    sidecar count, keep the sidecar metadata so polling does not loop forever on
    a false "newer transcript" signal.
    """
    sidecar_session = Session.load_metadata_only(sid)
    sidecar_count = 0
    sidecar_last_message_at = 0.0
    if sidecar_session:
        sidecar_count = _numeric_count(getattr(sidecar_session, "_metadata_message_count", None))
        if sidecar_count <= 0:
            sidecar_count = _numeric_count(sidecar_session.compact().get("message_count"))
        try:
            sidecar_last_message_at = float(getattr(sidecar_session, "updated_at", 0) or 0)
        except (TypeError, ValueError):
            sidecar_last_message_at = 0.0
        if getattr(sidecar_session, "truncation_watermark", None) is not None:
            # Intentional: once the user has truncated this sidecar, metadata
            # polling must keep the sidecar as authoritative.  A full message
            # load can still apply the watermark-aware merge, but the cheap
            # metadata path should not treat later state.db rows as external
            # growth and resurrect turns the user deliberately cut away.
            return {
                "message_count": sidecar_count,
                "last_message_at": sidecar_last_message_at,
            }
    state_summary = get_state_db_session_summary(sid, profile=profile)
    state_count = _numeric_count(state_summary.get("message_count"))
    try:
        state_last_message_at = float(state_summary.get("last_message_at") or 0)
    except (TypeError, ValueError):
        state_last_message_at = 0.0
    if state_count > sidecar_count and state_last_message_at > sidecar_last_message_at:
        return {
            "message_count": state_count,
            "last_message_at": state_last_message_at,
        }
    return {
        "message_count": sidecar_count,
        "last_message_at": sidecar_last_message_at,
    }


def _session_requires_cli_metadata_lookup(session) -> bool:
    """Return True when a sidecar/session row still needs CLI metadata.

    Legacy imported sidecars may predate the ``read_only`` field and therefore
    load with ``read_only=False``. They still persist ``is_cli_session`` and/or
    source metadata from import time, so those markers intentionally keep them
    on the CLI lookup path while ordinary WebUI-native sessions take the fast
    path.

    Supersedes the simpler is-cli-or-messaging gate from PR #1822 — the new
    gate is strictly more inclusive (also covers ``read_only=True`` sidecars,
    ``session_source`` markers, and source_tag/raw_source/platform metadata)
    so all sessions that previously took the slow path still do, plus a few
    more legacy shapes.
    """
    if not session:
        return False

    def _field(name):
        return session.get(name) if isinstance(session, dict) else getattr(session, name, None)

    if _is_messaging_session_record(session):
        return True
    if bool(_field("is_cli_session")) or bool(_field("read_only")):
        return True
    session_source = _normalize_messaging_source(_safe_first(_field("session_source")))
    if session_source in {"messaging", "external_agent", "external-agent"}:
        return True
    return bool(_safe_first(
        _field("source_tag"),
        _field("raw_source"),
        _field("source"),
        _field("source_label"),
        _field("platform"),
    ))


def _is_messaging_session_id(sid: str) -> bool:
    """Detect messaging-backed sessions from WebUI metadata or Agent rows."""
    try:
        session = Session.load(sid)
        if _is_messaging_session_record(session):
            return True
    except Exception:
        pass
    return _is_messaging_session_record(_lookup_cli_session_metadata(sid))


def _session_sort_timestamp(session: dict) -> float:
    return float(
        _safe_first(
            session.get("last_message_at"),
            session.get("updated_at"),
            session.get("created_at"),
            session.get("started_at"),
            0,
        ) or 0
    ) or 0.0


def _messaging_source_key(session: dict) -> str | None:
    raw = _session_messaging_raw_source(session)
    if not _is_known_messaging_source(raw):
        return None
    return _messaging_session_identity(session, raw)


def _keep_latest_messaging_session_per_source(
    sessions: list[dict],
    *,
    show_previous_messaging_sessions: bool = False,
) -> list[dict]:
    """Keep only the newest sidebar row per messaging session identity."""
    if show_previous_messaging_sessions:
        return sorted(sessions, key=_session_sort_timestamp, reverse=True)

    gateway_metadata = _load_gateway_session_identity_map()
    active_gateway_session_ids = {str(sid) for sid in gateway_metadata.keys() if sid}
    session_ids = {
        _safe_first(session.get("session_id"))
        for session in sessions
        if isinstance(session, dict)
    }
    visible_active_gateway_session_ids = active_gateway_session_ids & session_ids
    active_gateway_sources = {
        _normalize_messaging_source(_safe_first(meta.get("raw_source"), meta.get("platform")))
        for sid, meta in gateway_metadata.items()
        if sid in visible_active_gateway_session_ids and isinstance(meta, dict)
    }
    active_gateway_sources = {source for source in active_gateway_sources if _is_known_messaging_source(source)}

    kept_sources: set[str] = set()
    best_by_source: dict[str, dict] = {}
    kept: list[dict] = []
    for session in sessions:
        key = _messaging_source_key(session)
        if not key:
            kept.append(session)
            continue
        if _should_hide_stale_messaging_session(session, visible_active_gateway_session_ids, active_gateway_sources):
            continue
        if key in kept_sources:
            kept_sources.add(key)
            current = best_by_source.get(key)
            if current is None or _session_sort_timestamp(session) > _session_sort_timestamp(current):
                best_by_source[key] = session
            continue
        kept_sources.add(key)
        best_by_source[key] = session

    kept.extend(best_by_source.values())
    kept.sort(key=_session_sort_timestamp, reverse=True)
    return kept


from app.domain.models import (
    Session,
    get_session,
    new_session,
    all_sessions,
    title_from,
    _write_session_index,
    SESSION_INDEX_FILE,
    _active_state_db_path,
    load_projects,
    save_projects,
    import_cli_session,
    get_cli_sessions,
    get_cli_session_messages,
    get_state_db_session_messages,
    get_state_db_session_summary,
    merge_session_messages_append_only,
    _session_message_merge_key,
    prune_session_from_index,
    ensure_cron_project,
    is_cron_session,
)
from app.domain.workspace import (
    load_workspaces,
    save_workspaces,
    get_last_workspace,
    set_last_workspace,
    list_dir,
    dir_signature,
    list_workspace_suggestions,
    read_file_content,
    safe_resolve_ws,
    resolve_trusted_workspace,
    validate_workspace_to_add,
    MAX_WORKSPACES_PER_PROFILE,
    _is_blocked_system_path,
    _strip_surrounding_quotes,
    _workspace_blocked_roots,
)
from app.domain.upload import handle_upload, handle_upload_extract, handle_transcribe
from app.domain.streaming import (
    _sse,
    _run_agent_streaming,
    cancel_stream,
    _materialize_pending_user_turn_before_error,
)
from app.domain.run_journal import (
    find_run_summary,
    read_run_events,
    stale_interrupted_event,
)
from app.domain.providers import get_providers, get_provider_quota, get_provider_cost_history, set_provider_key, remove_provider_key
from app.domain.onboarding import (
    apply_onboarding_setup,
    get_onboarding_status,
    complete_onboarding,
    probe_provider_endpoint,
)
from app.domain.oauth import (
    cancel_onboarding_oauth_flow,
    poll_onboarding_oauth_flow,
    start_onboarding_oauth_flow,
)

# Approval system (optional -- graceful fallback if agent not available)
try:
    from tools.approval import (
        submit_pending as _submit_pending_raw,
        approve_session,
        approve_permanent,
        save_permanent_allowlist,
        is_approved,
        _pending,
        _lock,
        _permanent_approved,
        _gateway_queues,
        resolve_gateway_approval,
        enable_session_yolo,
        disable_session_yolo,
        is_session_yolo_enabled,
    )
except ImportError:
    _submit_pending_raw = lambda *a, **k: None
    approve_session = lambda *a, **k: None
    approve_permanent = lambda *a, **k: None
    save_permanent_allowlist = lambda *a, **k: None
    is_approved = lambda *a, **k: True
    resolve_gateway_approval = lambda *a, **k: 0
    enable_session_yolo = lambda *a, **k: None
    disable_session_yolo = lambda *a, **k: None
    is_session_yolo_enabled = lambda *a, **k: False
    _pending = {}
    _lock = threading.Lock()
    _permanent_approved = set()
    _gateway_queues = {}


# ── Approval SSE subscribers (long-connection push) ──────────────────────────
_approval_sse_subscribers: dict[str, list[queue.Queue]] = {}


def _approval_sse_subscribe(session_id: str) -> queue.Queue:
    """Register an SSE subscriber for approval events on a given session."""
    q = queue.Queue(maxsize=16)
    with _lock:
        _approval_sse_subscribers.setdefault(session_id, []).append(q)
    return q


def _approval_sse_unsubscribe(session_id: str, q: queue.Queue) -> None:
    """Remove an SSE subscriber."""
    with _lock:
        subs = _approval_sse_subscribers.get(session_id)
        if subs and q in subs:
            subs.remove(q)
            if not subs:
                _approval_sse_subscribers.pop(session_id, None)


def _approval_sse_notify_locked(session_id: str, head: dict | None, total: int) -> None:
    """Push an approval event to all SSE subscribers for a session.

    CALLER MUST HOLD `_lock`. Snapshots the subscriber list under the held
    lock and then calls `q.put_nowait()` on each (which is itself thread-safe).

    `head` is the approval entry currently at the head of the queue (the one
    the UI should display) — NOT the just-appended entry. With multiple
    parallel approvals (#527), the just-appended entry is at the TAIL, but
    `/api/approval/pending` always returns the HEAD, so SSE must match.

    `total` is the total number of pending approvals.

    Pass `head=None` and `total=0` when the queue has just been emptied (e.g.
    `_handle_approval_respond` popped the last entry) so the client knows to
    hide its approval card.
    """
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    subs = _approval_sse_subscribers.get(session_id, ())
    for q in subs:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass  # drop if subscriber is slow (bounded queue prevents memory leak)


def _approval_sse_notify(session_id: str, head: dict | None, total: int) -> None:
    """Convenience wrapper that takes `_lock` itself.

    Use only from contexts that don't already hold `_lock`. Production call
    sites (submit_pending, _handle_approval_respond) MUST hold the lock and
    call `_approval_sse_notify_locked` directly to avoid a notify-ordering
    race where a later append's notify can fire before an earlier append's
    notify (resulting in stale `pending_count`).
    """
    with _lock:
        _approval_sse_notify_locked(session_id, head, total)


def _approval_head_locked(session_id: str) -> tuple[dict | None, int]:
    """Return (head_entry, total_count). CALLER MUST HOLD `_lock`.

    During active streaming, dangerous commands (terminal, execute_code) block
    in the agent's `_gateway_queues`. Clarify SSE already peeks that queue;
    approval pending/SSE must do the same or the React modal never appears.
    """
    sid = str(session_id or "")
    gw_q = _gateway_queues.get(sid) or []
    if gw_q:
        gw_entry = gw_q[0]
        gw_data = getattr(gw_entry, "data", None) or {}
        return dict(gw_data), len(gw_q)
    queue = _pending.get(sid)
    if isinstance(queue, list):
        if queue:
            return dict(queue[0]), len(queue)
        return None, 0
    if queue:
        return dict(queue), 1
    return None, 0


def _approval_head_snapshot(session_id: str) -> tuple[dict | None, int]:
    with _lock:
        return _approval_head_locked(session_id)


def _approval_sse_notify_gateway(session_id: str) -> None:
    """Push approval SSE after a gateway-queue entry is created mid-stream."""
    with _lock:
        head, total = _approval_head_locked(session_id)
        _approval_sse_notify_locked(session_id, head, total)


def submit_pending(session_key: str, approval: dict) -> None:
    """Append a pending approval to the per-session queue.

    Wraps the agent's submit_pending to:
    - Add a stable approval_id (uuid4 hex) so the respond endpoint can target
      a specific entry even when multiple approvals are queued simultaneously.
    - Change the storage from a single overwriting dict value to a list, so
      parallel tool calls each get their own approval slot (fixes #527).
    - Notify any connected SSE subscribers immediately.
    """
    entry = dict(approval)
    entry.setdefault("approval_id", uuid.uuid4().hex)
    with _lock:
        queue_list = _pending.setdefault(session_key, [])
        # Replace a legacy non-list value if the agent version uses the old pattern.
        if not isinstance(queue_list, list):
            _pending[session_key] = [queue_list]
            queue_list = _pending[session_key]
        queue_list.append(entry)
        total = len(queue_list)
        head = queue_list[0]  # /api/approval/pending always returns head
        # Push to SSE subscribers from inside _lock so two parallel
        # submit_pending calls can't deliver out-of-order (T2's later
        # notify arriving before T1's earlier notify with a stale count).
        _approval_sse_notify_locked(session_key, head, total)
    # NOTE: We do NOT call _submit_pending_raw here — that function overwrites
    # _pending[session_key] with a single dict, which would undo the list we just
    # built. The gateway blocking path uses _gateway_queues (a separate mechanism
    # managed by check_all_command_guards / register_gateway_notify), which is
    # unaffected by _pending. The _pending dict is only used for UI polling.

# Clarify prompts (optional -- graceful fallback if agent not available)
try:
    from app.domain.clarify import (
        submit_pending as submit_clarify_pending,
        get_pending as get_clarify_pending,
        resolve_clarify,
        resolve_clarify_by_id,
        sse_subscribe as clarify_sse_subscribe,
        sse_unsubscribe as clarify_sse_unsubscribe,
    )
except ImportError:
    submit_clarify_pending = lambda *a, **k: None
    get_clarify_pending = lambda *a, **k: None
    clarify_sse_subscribe = None
    resolve_clarify = lambda *a, **k: 0
    resolve_clarify_by_id = lambda *a, **k: False


# ── Login page locale strings ─────────────────────────────────────────────────
# Add entries here to support more languages on the login page.
# The key must match the 'language' setting value (from static/i18n.js LOCALES).
_LOGIN_LOCALE = {
    "en": {
        "lang": "en",
        "title": "Sign in",
        "subtitle": "Enter your password to continue",
        "multi_user_subtitle": "Enter your username and password to continue",
        "username_placeholder": "Username",
        "username_required": "Username required",
        "placeholder": "Password",
        "btn": "Sign in",
        "invalid_pw": "Invalid password",
        "conn_failed": "Connection failed",
    },
    "fr": {
        "lang": "fr-FR",
        "title": "Se connecter",
        "subtitle": "Entrez votre mot de passe pour continuer",
        "placeholder": "Mot de passe",
        "btn": "Se connecter",
        "invalid_pw": "Mot de passe invalide",
        "conn_failed": "\u00c9chec de la connexion",
    },
    "es": {
        "lang": "es-ES",
        "title": "Iniciar sesi\u00f3n",
        "subtitle": "Introduce tu contrase\u00f1a para continuar",
        "placeholder": "Contrase\u00f1a",
        "btn": "Entrar",
        "invalid_pw": "Contrase\u00f1a inv\u00e1lida",
        "conn_failed": "Error de conexi\u00f3n",
    },
    "de": {
        "lang": "de-DE",
        "title": "Anmelden",
        "subtitle": "Geben Sie Ihr Passwort ein, um fortzufahren",
        "placeholder": "Passwort",
        "btn": "Anmelden",
        "invalid_pw": "Ung\u00fcltiges Passwort",
        "conn_failed": "Verbindung fehlgeschlagen",
    },
    "ru": {
        "lang": "ru-RU",
        "title": "\u0412\u043e\u0439\u0442\u0438",
        "subtitle": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c",
        "placeholder": "\u041f\u0430\u0440\u043e\u043b\u044c",
        "btn": "\u0412\u043e\u0439\u0442\u0438",
        "invalid_pw": "\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u043f\u0430\u0440\u043e\u043b\u044c",
        "conn_failed": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f",
    },
    "zh": {
        "lang": "zh-CN",
        "title": "\u767b\u5f55",
        "subtitle": "\u8f93\u5165\u5bc6\u7801\u7ee7\u7eed\u4f7f\u7528",
        "placeholder": "\u5bc6\u7801",
        "btn": "\u767b\u5f55",
        "invalid_pw": "\u5bc6\u7801\u9519\u8bef",
        "conn_failed": "\u8fde\u63a5\u5931\u8d25",
    },
    "zh-Hant": {
        "lang": "zh-TW",
        "title": "\u767b\u5f55",
        "subtitle": "\u8f38\u5165\u5bc6\u78bc\u7e7c\u7e8c\u4f7f\u7528",
        "placeholder": "\u5bc6\u78bc",
        "btn": "\u767b\u5f55",
        "invalid_pw": "\u5bc6\u78bc\u932f\u8aa4",
        "conn_failed": "\u9023\u63a5\u5931\u6557",
    },
    # Strings mirror static/i18n.js login_* keys for the corresponding locale.
    # See issue #1442. When adding a new locale to LOCALES in i18n.js, also add
    # the matching entry here — tests/test_login_locale_parity.py enforces this.
    "it": {
        "lang": "it-IT",
        "title": "Accedi",
        "subtitle": "Inserisci la password per continuare",
        "placeholder": "Password",
        "btn": "Accedi",
        "invalid_pw": "Password non valida",
        "conn_failed": "Connessione fallita",
    },
    "ja": {
        "lang": "ja-JP",
        "title": "\u30b5\u30a4\u30f3\u30a4\u30f3",
        "subtitle": "\u30d1\u30b9\u30ef\u30fc\u30c9\u3092\u5165\u529b\u3057\u3066\u7d9a\u884c",
        "placeholder": "\u30d1\u30b9\u30ef\u30fc\u30c9",
        "btn": "\u30b5\u30a4\u30f3\u30a4\u30f3",
        "invalid_pw": "\u30d1\u30b9\u30ef\u30fc\u30c9\u304c\u7121\u52b9\u3067\u3059",
        "conn_failed": "\u63a5\u7d9a\u5931\u6557",
    },
    "pt": {
        "lang": "pt-BR",
        "title": "Entrar",
        "subtitle": "Digite sua senha para continuar",
        "placeholder": "Senha",
        "btn": "Entrar",
        "invalid_pw": "Senha inv\u00e1lida",
        "conn_failed": "Falha na conex\u00e3o",
    },
    "ko": {
        "lang": "ko-KR",
        "title": "\ub85c\uadf8\uc778",
        "subtitle": "\uacc4\uc18d\ud558\ub824\uba74 \ube44\ubc00\ubc88\ud638\ub97c \uc785\ub825\ud558\uc138\uc694",
        "placeholder": "\ube44\ubc00\ubc88\ud638",
        "btn": "\ub85c\uadf8\uc778",
        "invalid_pw": "\ube44\ubc00\ubc88\ud638\uac00 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4",
        "conn_failed": "\uc5f0\uacb0 \uc2e4\ud328",
    },
    "tr": {
        "lang": "tr-TR",
        "title": "Oturum a\u00e7",
        "subtitle": "Devam etmek i\u00e7in \u015fifrenizi girin",
        "placeholder": "\u015eifre",
        "btn": "Oturum a\u00e7",
        "invalid_pw": "Ge\u00e7ersiz \u015fifre",
        "conn_failed": "Ba\u011flant\u0131 ba\u015far\u0131s\u0131z",
    },
    "th": {
        "lang": "th-TH",
        "title": "\u0e40\u0e02\u0e49\u0e32\u0e2a\u0e39\u0e48\u0e23\u0e30\u0e1a\u0e1a",
        "subtitle": "\u0e1b\u0e49\u0e2d\u0e19\u0e23\u0e2b\u0e31\u0e2a\u0e1c\u0e48\u0e32\u0e19\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e14\u0e33\u0e40\u0e19\u0e34\u0e19\u0e01\u0e32\u0e23\u0e15\u0e48\u0e2d",
        "multi_user_subtitle": "\u0e1b\u0e49\u0e2d\u0e19\u0e0a\u0e37\u0e48\u0e2d\u0e1c\u0e39\u0e49\u0e43\u0e0a\u0e49\u0e41\u0e25\u0e30\u0e23\u0e2b\u0e31\u0e2a\u0e1c\u0e48\u0e32\u0e19\u0e40\u0e1e\u0e37\u0e48\u0e2d\u0e14\u0e33\u0e40\u0e19\u0e34\u0e19\u0e01\u0e32\u0e23\u0e15\u0e48\u0e2d",
        "username_placeholder": "\u0e0a\u0e37\u0e48\u0e2d\u0e1c\u0e39\u0e49\u0e43\u0e0a\u0e49",
        "username_required": "\u0e01\u0e23\u0e38\u0e13\u0e32\u0e1b\u0e49\u0e2d\u0e19\u0e0a\u0e37\u0e48\u0e2d\u0e1c\u0e39\u0e49\u0e43\u0e0a\u0e49",
        "placeholder": "\u0e23\u0e2b\u0e31\u0e2a\u0e1c\u0e48\u0e32\u0e19",
        "btn": "\u0e40\u0e02\u0e49\u0e32\u0e2a\u0e39\u0e48\u0e23\u0e30\u0e1a\u0e1a",
        "invalid_pw": "\u0e23\u0e2b\u0e31\u0e2a\u0e1c\u0e48\u0e32\u0e19\u0e44\u0e21\u0e48\u0e16\u0e39\u0e01\u0e15\u0e49\u0eAD\u0e07",
        "conn_failed": "\u0e40\u0e0a\u0e37\u0e48\u0e2d\u0e21\u0e15\u0e48\u0eAD\u0e44\u0e21\u0e48\u0e2a\u0e33\u0e40\u0e08\u0e0d",
    },
}


def _resolve_login_locale_key(raw_lang: str | None) -> str:
    """Resolve settings.language to a known _LOGIN_LOCALE key."""
    if not raw_lang:
        return "en"
    lang = str(raw_lang).strip()
    if not lang:
        return "en"
    if lang in _LOGIN_LOCALE:
        return lang

    normalized = lang.replace("_", "-")
    lower = normalized.lower()

    # Case-insensitive direct key match first.
    for key in _LOGIN_LOCALE:
        if key.lower() == lower:
            return key

    # Common Chinese aliases.
    if lower == "zh" or lower.startswith("zh-cn") or lower.startswith("zh-sg") or lower.startswith("zh-hans"):
        return "zh"
    if lower.startswith("zh-tw") or lower.startswith("zh-hk") or lower.startswith("zh-mo") or lower.startswith("zh-hant"):
        return "zh-Hant" if "zh-Hant" in _LOGIN_LOCALE else "zh"

    # Fallback to base language subtag (e.g. en-US -> en).
    base = lower.split("-", 1)[0]
    for key in _LOGIN_LOCALE:
        if key.lower() == base:
            return key
    return "en"

# ── Login page (self-contained, no external deps) ────────────────────────────
_LOGIN_PAGE_HTML = """<!doctype html>
<html lang="{{LANG}}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{BOT_NAME}} — {{LOGIN_TITLE}}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1a1a2e;color:#e8e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#16213e;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:36px 32px;
  width:320px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.3)}
.logo{width:48px;height:48px;border-radius:12px;background:linear-gradient(145deg,#e8a030,#e94560);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;color:#fff;
  margin:0 auto 12px;box-shadow:0 2px 12px rgba(233,69,96,.3)}
h1{font-size:18px;font-weight:600;margin-bottom:4px}
.sub{font-size:12px;color:#8888aa;margin-bottom:24px}
input{width:100%;padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.04);color:#e8e8f0;font-size:14px;outline:none;margin-bottom:14px;
  transition:border-color .15s}
input:focus{border-color:rgba(124,185,255,.5);box-shadow:0 0 0 3px rgba(124,185,255,.1)}
button{width:100%;padding:10px;border-radius:10px;border:none;background:rgba(124,185,255,.15);
  border:1px solid rgba(124,185,255,.3);color:#7cb9ff;font-size:14px;font-weight:600;cursor:pointer;
  transition:all .15s}
button:hover{background:rgba(124,185,255,.25)}
.passkey-login{margin-top:10px;background:rgba(255,255,255,.04);border-color:rgba(232,160,48,.35);color:#e8a030}
.err{color:#e94560;font-size:12px;margin-top:10px;display:none}
</style></head><body>
<div class="card">
  <div class="logo">{{BOT_NAME_INITIAL}}</div>
  <h1>{{BOT_NAME}}</h1>
  <p class="sub">{{LOGIN_SUBTITLE}}</p>
  <form id="login-form"{{LOGIN_MULTI_USER_ATTR}} data-invalid-pw="{{LOGIN_INVALID_PW}}" data-conn-failed="{{LOGIN_CONN_FAILED}}" data-multi-user-subtitle="{{LOGIN_MULTI_USER_SUBTITLE}}" data-username-required="{{LOGIN_USERNAME_REQUIRED}}">
    <input type="text" id="username" name="username" autocomplete="username" placeholder="{{LOGIN_USERNAME_PLACEHOLDER}}"{{LOGIN_USERNAME_ATTRS}}>
    <input type="password" id="pw" placeholder="{{LOGIN_PLACEHOLDER}}"{{LOGIN_PW_ATTRS}}>
    <button type="submit">{{LOGIN_BTN}}</button>
    <button type="button" id="passkey-login" class="passkey-login" style="display:none">Sign in with passkey</button>
  </form>
  <div class="err" id="err"></div>
</div>
<!-- Keep login.js relative so subpath mounts load it under the current scope. -->
<script src="static/login.js?v={{WEBUI_VERSION}}"></script>
</body></html>"""


# ── Logs endpoint ─────────────────────────────────────────────────────────────
_LOG_FILE_WHITELIST = {
    "agent": "agent.log",
    "errors": "errors.log",
    "gateway": "gateway.log",
}
_LOG_TAIL_VALUES = {100, 200, 500, 1000}
_LOG_DEFAULT_TAIL = 200
_LOG_MAX_BYTES = 4 * 1024 * 1024


def _normalize_logs_tail(raw_tail) -> int:
    try:
        tail = int(str(raw_tail or "").strip())
    except (TypeError, ValueError):
        return _LOG_DEFAULT_TAIL
    return tail if tail in _LOG_TAIL_VALUES else _LOG_DEFAULT_TAIL


def _require_insights_access(handler) -> bool:
    from app.core.security import (
        INSIGHTS_FORBIDDEN_DETAIL,
        get_current_user_from_legacy_handler,
        user_can_access_insights,
    )

    user = get_current_user_from_legacy_handler(handler)
    if not user_can_access_insights(user):
        bad(handler, INSIGHTS_FORBIDDEN_DETAIL, status=403)
        return False
    return True


def _require_logs_access(handler) -> bool:
    from app.core.security import (
        LOGS_FORBIDDEN_DETAIL,
        get_current_user_from_legacy_handler,
        user_can_access_logs,
    )

    user = get_current_user_from_legacy_handler(handler)
    if not user_can_access_logs(user):
        bad(handler, LOGS_FORBIDDEN_DETAIL, status=403)
        return False
    return True


def _require_insights_logs_admin(handler) -> bool:
    """Back-compat alias — prefer ``_require_insights_access`` / ``_require_logs_access``."""
    return _require_insights_access(handler)


def _resolve_insights_logs_profile_filter(query: dict) -> tuple[str | None, str | None]:
    """Return (profile_name, error_message) for optional profile/username filters."""
    profile_raw = (query.get("profile", [None])[0] or "").strip()
    username_raw = (query.get("username", [None])[0] or "").strip().lower()
    if profile_raw and username_raw:
        return None, "Specify profile or username, not both"
    if username_raw:
        from app.domain.users import get_user

        record = get_user(username_raw)
        if record is None:
            return None, f"Unknown user {username_raw!r}"
        if record.role == "admin":
            return None, "Admin accounts are not bound to a profile"
        if not record.profile_name:
            return None, f"User {username_raw!r} has no profile binding"
        return record.profile_name, None
    if profile_raw:
        return profile_raw, None
    return None, None


def _session_entry_matches_profile(entry: dict, profile_filter: str | None) -> bool:
    if not profile_filter:
        return True
    from app.domain.profiles import _profiles_match

    row_profile = entry.get("profile") or "default"
    return _profiles_match(row_profile, profile_filter)


def _handle_logs(handler, parsed) -> bool:
    """Return a bounded tail window for an active-profile Hermes log file."""
    if not _require_logs_access(handler):
        return True
    query = parse_qs(parsed.query)
    profile_filter, filter_error = _resolve_insights_logs_profile_filter(query)
    if filter_error:
        return bad(handler, filter_error, status=400)
    file_key = (query.get("file", ["agent"])[0] or "agent").strip().lower()
    filename = _LOG_FILE_WHITELIST.get(file_key)
    if not filename:
        return bad(handler, "Unknown log file", status=400)

    tail = _normalize_logs_tail(query.get("tail", [None])[0])
    try:
        if profile_filter:
            from app.domain.profiles import get_hermes_home_for_profile

            hermes_home = Path(get_hermes_home_for_profile(profile_filter)).expanduser()
        else:
            from app.domain.profiles import get_active_hermes_home

            hermes_home = Path(get_active_hermes_home()).expanduser()
    except Exception:
        hermes_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()

    log_dir = hermes_home / "logs"
    log_path = log_dir / filename
    try:
        # Defense in depth: the filename is hardcoded above, but keep the final
        # path anchored under the active profile's logs directory.
        if log_path.resolve(strict=False).parent != log_dir.resolve(strict=False):
            return bad(handler, "Invalid log file", status=400)
        if not log_path.exists() or not log_path.is_file():
            return j(handler, {
                "file": file_key,
                "tail": tail,
                "lines": [],
                "truncated": False,
                "total_bytes": 0,
                "mtime": None,
                "hint": f"Log file for {file_key} not found yet.",
                "profile": profile_filter,
            })
        st = log_path.stat()
        total_bytes = int(st.st_size)
        read_bytes = min(total_bytes, _LOG_MAX_BYTES)
        with log_path.open("rb") as fh:
            if total_bytes > read_bytes:
                fh.seek(total_bytes - read_bytes)
            raw = fh.read(read_bytes)
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()[-tail:]
        return j(handler, {
            "file": file_key,
            "tail": tail,
            "lines": lines,
            "truncated": total_bytes > read_bytes,
            "total_bytes": total_bytes,
            "mtime": st.st_mtime,
            "hint": "",
            "profile": profile_filter,
        })
    except Exception as exc:
        logger.exception("Failed to read whitelisted log file %s", file_key)
        return bad(handler, _sanitize_error(exc), status=500)

# ── Insights endpoint ──────────────────────────────────────────────────────────

_LLM_WIKI_DOCS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki"
_LLM_WIKI_PAGE_DIRS = ("entities", "concepts", "comparisons", "queries")


def _llm_wiki_active_hermes_home() -> Path:
    try:
        from app.domain.profiles import get_active_hermes_home
        return Path(get_active_hermes_home()).expanduser()
    except Exception:
        return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _llm_wiki_env_file_path(hermes_home: Path) -> str | None:
    env_path = hermes_home / ".env"
    if not env_path.exists() or not env_path.is_file():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != "WIKI_PATH":
                continue
            value = value.strip().strip('"').strip("'")
            return value or None
    except Exception:
        return None
    return None


def _llm_wiki_get_config_path_value(config: dict, dotted_key: str) -> str | None:
    if not isinstance(config, dict):
        return None
    if dotted_key in config and config.get(dotted_key):
        return str(config.get(dotted_key))
    cur = config
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return str(cur) if cur else None


def _llm_wiki_config_path() -> str | None:
    try:
        from app.domain.config import get_config as _get_cfg
        cfg = _get_cfg()
    except Exception:
        return None
    return (
        _llm_wiki_get_config_path_value(cfg, "skills.config.wiki.path")
        or _llm_wiki_get_config_path_value(cfg, "wiki.path")
    )


# Cap WIKI walks to prevent self-DoS if WIKI_PATH points at /, /etc, /home, etc.
# Real LLM wikis have under a few thousand files; 10k is generous and catches misconfig.
_LLM_WIKI_MAX_FILES = 10000
# Refuse to walk these system roots even if explicitly configured.
_LLM_WIKI_FORBIDDEN_ROOTS = frozenset(
    str(Path(p).expanduser().resolve()) for p in ("/", "/etc", "/usr", "/var", "/opt", "/sys", "/proc")
)


def _llm_wiki_resolve_path() -> tuple[Path, str, bool]:
    hermes_home = _llm_wiki_active_hermes_home()
    raw = os.getenv("WIKI_PATH") or _llm_wiki_env_file_path(hermes_home)
    source = "WIKI_PATH" if raw else "default"
    configured = bool(raw)
    if not raw:
        raw = _llm_wiki_config_path()
        if raw:
            source = "skills.config.wiki.path"
            configured = True
    if not raw:
        raw = "~/wiki"
    return Path(os.path.expandvars(raw)).expanduser(), source, configured


def _llm_wiki_safe_iso(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _llm_wiki_count_files(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    # Defense in depth: refuse to walk forbidden system roots even if WIKI_PATH
    # was set to one. The endpoint is auth-gated but a misconfigured server
    # shouldn't self-DoS by rglob'ing all of /etc on every Insights load.
    try:
        if str(root.resolve()) in _LLM_WIKI_FORBIDDEN_ROOTS:
            return 0
    except Exception:
        return 0
    count = 0
    iterated = 0
    for item in root.rglob("*"):
        iterated += 1
        if iterated > _LLM_WIKI_MAX_FILES:
            break  # bounded — prevents hangs on symlink loops or huge trees
        try:
            if item.is_file() and not any(part.startswith(".") for part in item.relative_to(root).parts):
                count += 1
        except Exception:
            continue
    return count


def _llm_wiki_page_files(wiki_path: Path) -> list[Path]:
    pages: list[Path] = []
    # Defense in depth: refuse forbidden system roots.
    try:
        if str(wiki_path.resolve()) in _LLM_WIKI_FORBIDDEN_ROOTS:
            return pages
    except Exception:
        return pages
    iterated = 0
    for dirname in _LLM_WIKI_PAGE_DIRS:
        section = wiki_path / dirname
        if not section.exists() or not section.is_dir():
            continue
        for item in section.rglob("*.md"):
            iterated += 1
            if iterated > _LLM_WIKI_MAX_FILES:
                return pages  # bounded
            try:
                rel = item.relative_to(section)
                if item.is_file() and not any(part.startswith(".") for part in rel.parts):
                    pages.append(item)
            except Exception:
                continue
    return pages


def _build_llm_wiki_status() -> dict:
    """Return private-safe LLM Wiki status metadata without reading page bodies."""
    try:
        wiki_path, path_source, path_configured = _llm_wiki_resolve_path()
        base = {
            "available": False,
            "enabled": False,
            "status": "missing",
            "entry_count": 0,
            "page_count": 0,
            "raw_source_count": 0,
            "last_updated": None,
            "last_writer": None,
            "path_configured": path_configured,
            "path_source": path_source,
            "toggle_available": False,
            "toggle_reason": "Hermes Agent exposes WIKI_PATH/wiki.path for location, but no stable on/off config flag is currently available.",
            "docs_url": _LLM_WIKI_DOCS_URL,
        }
        if not wiki_path.exists():
            return base
        if not wiki_path.is_dir():
            base["status"] = "not_directory"
            return base

        page_files = _llm_wiki_page_files(wiki_path)
        status_files = [p for p in (wiki_path / "SCHEMA.md", wiki_path / "index.md", wiki_path / "log.md") if p.exists() and p.is_file()]
        status_files.extend(page_files)
        latest = None
        for item in status_files:
            try:
                mtime = item.stat().st_mtime
            except Exception:
                continue
            latest = mtime if latest is None else max(latest, mtime)

        base.update({
            "available": True,
            "enabled": True,
            "status": "ready" if page_files else "empty",
            "entry_count": len(page_files),
            "page_count": len(page_files),
            "raw_source_count": _llm_wiki_count_files(wiki_path / "raw"),
            "last_updated": _llm_wiki_safe_iso(latest),
        })
        return base
    except Exception as exc:
        return {
            "available": False,
            "enabled": False,
            "status": "error",
            "entry_count": 0,
            "page_count": 0,
            "raw_source_count": 0,
            "last_updated": None,
            "last_writer": None,
            "path_configured": False,
            "path_source": "unknown",
            "toggle_available": False,
            "toggle_reason": "Unable to inspect LLM Wiki status safely.",
            "docs_url": _LLM_WIKI_DOCS_URL,
            "error": type(exc).__name__,
        }


def _handle_llm_wiki_status(handler, parsed) -> bool:
    j(handler, _build_llm_wiki_status())
    return True


def _handle_insights(handler, parsed) -> bool:
    """Return usage analytics from local WebUI session data."""
    if not _require_insights_access(handler):
        return True
    import collections
    import time as _time

    query = parse_qs(parsed.query)
    profile_filter, filter_error = _resolve_insights_logs_profile_filter(query)
    if filter_error:
        return bad(handler, filter_error, status=400)
    try:
        days = min(max(int(query.get("days", ["30"])[0]), 1), 365)
    except (ValueError, TypeError):
        days = 30

    now = _time.time()
    today = _time.localtime(now)
    today_midnight = _time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, today.tm_wday, today.tm_yday, today.tm_isdst))
    day_secs = 86400
    first_day_ts = today_midnight - ((days - 1) * day_secs)
    cutoff = first_day_ts

    def _safe_usage_int(value) -> int:
        try:
            return max(int(float(value or 0)), 0)
        except (TypeError, ValueError):
            return 0

    def _safe_cost_float(value) -> float:
        if value is None:
            return 0.0
        try:
            if isinstance(value, str):
                value = value.strip().replace("$", "").replace(",", "")
                if not value:
                    return 0.0
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _session_usage_ts(session: dict) -> float:
        return session.get("updated_at", session.get("created_at", 0)) or session.get("created_at", 0) or 0

    # Walk session index (fast, no full JSON parse)
    sessions_data = []
    idx_path = SESSION_DIR / "_index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = []
    else:
        idx = []

    for entry in idx:
        if not _session_entry_matches_profile(entry, profile_filter):
            continue
        created = entry.get("created_at", 0) or 0
        updated = entry.get("updated_at", 0) or 0
        # Session is relevant if it was created or updated within the calendar window.
        if max(created, updated) < cutoff:
            continue
        sessions_data.append(entry)

    # Aggregate
    total_sessions = len(sessions_data)
    total_messages = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    model_stats: dict[str, dict] = {}
    daily_tokens: dict[str, dict] = {}
    # Activity by day of week (0=Mon .. 6=Sun)
    dow_activity = collections.Counter()
    # Activity by hour of day (0-23)
    hod_activity = collections.Counter()

    for s in sessions_data:
        input_tokens = _safe_usage_int(s.get("input_tokens"))
        output_tokens = _safe_usage_int(s.get("output_tokens"))
        cost_value = _safe_cost_float(s.get("estimated_cost"))
        total_messages += _safe_usage_int(s.get("message_count"))
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cost += cost_value

        model = s.get("model") or "unknown"
        bucket = model_stats.setdefault(model, {
            "sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
        })
        bucket["sessions"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cost"] += cost_value

        # Activity patterns
        ts = _session_usage_ts(s)
        if ts:
            try:
                dt = _time.localtime(ts)
                day_key = _time.strftime("%Y-%m-%d", dt)
                daily_bucket = daily_tokens.setdefault(day_key, {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "sessions": 0,
                    "cost": 0.0,
                })
                daily_bucket["input_tokens"] += input_tokens
                daily_bucket["output_tokens"] += output_tokens
                daily_bucket["sessions"] += 1
                daily_bucket["cost"] += cost_value
                dow_activity[dt.tm_wday] += 1
                hod_activity[dt.tm_hour] += 1
            except Exception:
                pass

    # Build model breakdown
    total_tokens = total_input_tokens + total_output_tokens
    models_breakdown = []
    for model, stats in model_stats.items():
        row_total_tokens = stats["input_tokens"] + stats["output_tokens"]
        row_cost = round(stats["cost"], 6)
        models_breakdown.append({
            "model": model,
            "sessions": stats["sessions"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "total_tokens": row_total_tokens,
            "cost": row_cost,
            "session_share": int(round((stats["sessions"] / total_sessions) * 100)) if total_sessions else 0,
            "token_share": int(round((row_total_tokens / total_tokens) * 100)) if total_tokens else 0,
            "cost_share": int(round((row_cost / total_cost) * 100)) if total_cost else 0,
        })
    models_breakdown.sort(key=lambda r: (-r["cost"], -r["sessions"], r["model"]))

    daily_series = []
    for i in range(days):
        day_ts = first_day_ts + (i * day_secs)
        day_key = _time.strftime("%Y-%m-%d", _time.localtime(day_ts))
        bucket = daily_tokens.get(day_key, {
            "input_tokens": 0,
            "output_tokens": 0,
            "sessions": 0,
            "cost": 0.0,
        })
        daily_series.append({
            "date": day_key,
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "sessions": bucket["sessions"],
            "cost": round(bucket["cost"], 6),
        })

    # Day-of-week labels
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_data = [{"day": dow_labels[i], "sessions": dow_activity.get(i, 0)} for i in range(7)]

    # Hour-of-day data
    hod_data = [{"hour": h, "sessions": hod_activity.get(h, 0)} for h in range(24)]

    return j(handler, {
        "period_days": days,
        "profile": profile_filter,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "models": models_breakdown,
        "daily_tokens": daily_series,
        "activity_by_day": dow_data,
        "activity_by_hour": hod_data,
    })


# ── GET routes ────────────────────────────────────────────────────────────────


def _accept_loop_health(handler) -> dict:
    server = getattr(handler, "server", None)
    return {
        "requests_total": int(getattr(server, "accept_loop_requests_total", 0) or 0),
        "last_request_at": round(float(getattr(server, "accept_loop_last_request_at", 0.0) or 0.0), 3),
    }


def _streams_lock_health(timeout_seconds: float = 0.5) -> dict:
    t0 = time.time()
    acquired = STREAMS_LOCK.acquire(timeout=timeout_seconds)
    elapsed_ms = round((time.time() - t0) * 1000, 1)
    if not acquired:
        return {
            "status": "blocked",
            "timeout_seconds": timeout_seconds,
            "ms": elapsed_ms,
        }
    try:
        return {
            "status": "ok",
            "active_streams": len(STREAMS),
            "ms": elapsed_ms,
        }
    finally:
        STREAMS_LOCK.release()


def _stream_runtime_diagnostics() -> dict:
    """Return non-sensitive SSE stream diagnostics for health/deep status.

    The WebUI chat path can feel slow or stuck when streams are alive but no
    browser is attached, or when many events are buffering offline. This helper
    exposes counts only — stream ids plus subscriber/buffer sizes — and avoids
    event payloads, prompts, tool arguments, or paths.
    """
    streams = []
    total_subscribers = 0
    total_offline_buffered_events = 0
    with STREAMS_LOCK:
        items = list(STREAMS.items())
    for stream_id, stream in items:
        snapshot = {}
        diagnostic_snapshot = getattr(stream, "diagnostic_snapshot", None)
        if callable(diagnostic_snapshot):
            try:
                raw_snapshot = diagnostic_snapshot()
                if isinstance(raw_snapshot, dict):
                    snapshot = raw_snapshot
            except Exception:
                snapshot = {}
        subscriber_count = int(snapshot.get("subscriber_count") or 0)
        offline_buffered_events = int(snapshot.get("offline_buffered_events") or 0)
        total_subscribers += subscriber_count
        total_offline_buffered_events += offline_buffered_events
        streams.append({
            "stream_id": str(stream_id),
            "subscriber_count": subscriber_count,
            "offline_buffered_events": offline_buffered_events,
        })
    streams.sort(key=lambda item: item["stream_id"])
    return {
        "active_streams": len(streams),
        "total_subscribers": total_subscribers,
        "total_offline_buffered_events": total_offline_buffered_events,
        "streams": streams,
    }


def _run_lifecycle_health() -> dict:
    """Return active worker-run state independent of SSE stream presence."""
    # Import the module rather than relying only on imported scalar aliases so
    # LAST_RUN_FINISHED_AT stays fresh after unregister_active_run() updates it.
    from app.domain import config as _live_config

    now = time.time()
    with _live_config.ACTIVE_RUNS_LOCK:
        runs = []
        for stream_id, raw in (_live_config.ACTIVE_RUNS or {}).items():
            item = dict(raw or {})
            started_at = item.get("started_at")
            try:
                age = max(0.0, now - float(started_at))
            except Exception:
                age = 0.0
            item.setdefault("stream_id", stream_id)
            item["age_seconds"] = round(age, 1)
            runs.append(item)
        last_finished = _live_config.LAST_RUN_FINISHED_AT
    runs.sort(key=lambda item: float(item.get("started_at") or 0.0))
    payload = {
        "active_runs": len(runs),
        "runs": runs,
        "last_run_finished_at": last_finished,
    }
    if runs:
        payload["oldest_run_age_seconds"] = runs[0].get("age_seconds", 0.0)
    elif last_finished:
        payload["idle_seconds_since_last_run"] = round(max(0.0, now - float(last_finished)), 1)
    return payload


def _deep_health_checks(stream_check: dict | None = None) -> tuple[dict, bool]:
    """Run cheap probes that exercise the state paths used by the UI shell.

    Plain /health intentionally stays tiny. /health?deep=1 is for supervisors
    and watchdogs that need to know whether the process can still touch the
    shared stream map, sidebar/session path, project state, and Hermes state.db
    without hitting the RST-before-write failure mode from #1458.

    `stream_check` is the result from a prior `_streams_lock_health()` call;
    if provided, it's reused so we don't acquire `STREAMS_LOCK` twice on the
    same /health?deep=1 request (per Opus advisor on stage-297).
    """
    checks: dict[str, dict] = {}

    checks["streams_lock"] = stream_check if stream_check is not None else _streams_lock_health()
    checks["stream_runtime"] = {
        "status": "ok",
        **_stream_runtime_diagnostics(),
    }
    if checks["streams_lock"].get("status") != "ok":
        return checks, False

    t0 = time.time()
    try:
        sessions = all_sessions()
        checks["sessions"] = {
            "status": "ok",
            "count": len(sessions),
            "ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as exc:
        checks["sessions"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    t0 = time.time()
    try:
        projects = load_projects(_migrate=False)
        checks["projects"] = {
            "status": "ok",
            "count": len(projects),
            "ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as exc:
        checks["projects"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    t0 = time.time()
    try:
        db_path = _active_state_db_path()
        if not db_path.exists():
            checks["state_db"] = {
                "status": "missing",
                "ms": round((time.time() - t0) * 1000, 1),
            }
        else:
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute("PRAGMA schema_version").fetchone()
            checks["state_db"] = {
                "status": "ok",
                "ms": round((time.time() - t0) * 1000, 1),
            }
    except Exception as exc:
        checks["state_db"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    t0 = time.time()
    try:
        from app.storage.connection import storage_health_status

        wb = storage_health_status()
        wb["ms"] = round((time.time() - t0) * 1000, 1)
        checks["webui_db"] = wb
    except Exception as exc:
        checks["webui_db"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    healthy = all(
        check.get("status") in {"ok", "missing"}
        for check in checks.values()
    )
    return checks, healthy


def _handle_health(handler, parsed):
    deep = parse_qs(parsed.query or "").get("deep", [""])[0].lower() in {"1", "true", "yes", "on"}
    stream_check = _streams_lock_health()
    run_check = _run_lifecycle_health()
    payload = {
        "status": "ok" if stream_check.get("status") == "ok" else "degraded",
        "sessions": len(SESSIONS),
        "active_streams": int(stream_check.get("active_streams") or 0),
        "active_runs": int(run_check.get("active_runs") or 0),
        "runs": run_check.get("runs", []),
        "last_run_finished_at": run_check.get("last_run_finished_at"),
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
        "accept_loop": _accept_loop_health(handler),
    }
    if "oldest_run_age_seconds" in run_check:
        payload["oldest_run_age_seconds"] = run_check["oldest_run_age_seconds"]
    if "idle_seconds_since_last_run" in run_check:
        payload["idle_seconds_since_last_run"] = run_check["idle_seconds_since_last_run"]
    if deep:
        if stream_check.get("status") != "ok":
            payload["checks"] = {"streams_lock": stream_check}
            return j(handler, payload, status=503)
        checks, healthy = _deep_health_checks(stream_check=stream_check)
        payload["checks"] = checks
        if not healthy:
            payload["status"] = "degraded"
            return j(handler, payload, status=503)
    if payload["status"] != "ok":
        return j(handler, payload, status=503)
    return j(handler, payload)


# ── Plugin visibility endpoint (#539) ───────────────────────────────────────
_PLUGIN_VISIBILITY_HOOKS = (
    "pre_tool_call",
    "post_tool_call",
    "pre_llm_call",
    "post_llm_call",
)
_PLUGIN_VISIBILITY_HOOK_SET = set(_PLUGIN_VISIBILITY_HOOKS)


def _get_plugin_manager_for_visibility():
    """Return Hermes Agent's plugin manager for read-only WebUI visibility."""
    from hermes_cli.plugins import get_plugin_manager

    return get_plugin_manager()


def _clean_plugin_visibility_text(value, *, limit=240) -> str:
    """Return bounded display text without path/callback-like internals."""
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    # Display metadata should be plain labels/descriptions. Drop multiline text
    # and common path separators rather than risk leaking local plugin paths.
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _plugin_visibility_payload(manager=None) -> dict:
    """Build a sanitized plugin/hook visibility payload for Settings.

    The Hermes Agent manager stores manifests and callback objects internally.
    This endpoint intentionally exposes only safe, user-facing metadata and the
    four lifecycle hook names called out by the Settings visibility MVP. It
    never includes plugin source paths, callback names, callback reprs, or raw
    load errors because those can contain private filesystem details.

    Exclusive plugins (e.g. memory providers) are activated through their
    category's ``<category>.provider`` config, not through ``plugins.enabled``.
    Their ``loaded.enabled`` stays False by design and they register hooks
    outside the four visibility hooks below. The payload surfaces ``kind``
    and ``activation`` so the panel can render them distinctly instead of
    mislabeling them as "Disabled" with no hooks (issue #2659).
    """
    manager = manager or _get_plugin_manager_for_visibility()
    manager.discover_and_load(force=False)

    plugins = []
    raw_plugins = getattr(manager, "_plugins", {}) or {}
    for key, loaded in sorted(raw_plugins.items(), key=lambda item: str(item[0])):
        manifest = getattr(loaded, "manifest", None)
        if manifest is None:
            continue
        plugin_key = _clean_plugin_visibility_text(
            getattr(manifest, "key", None) or key or getattr(manifest, "name", ""),
            limit=120,
        )
        name = _clean_plugin_visibility_text(getattr(manifest, "name", "") or plugin_key, limit=120)
        version = _clean_plugin_visibility_text(getattr(manifest, "version", ""), limit=80)
        description = _clean_plugin_visibility_text(getattr(manifest, "description", ""), limit=280)
        kind = _clean_plugin_visibility_text(getattr(manifest, "kind", "") or "standalone", limit=40)
        enabled_flag = bool(getattr(loaded, "enabled", False))
        if kind == "exclusive":
            activation = "exclusive"
        elif kind == "model-provider" and enabled_flag:
            activation = "provider"
        else:
            activation = "enabled" if enabled_flag else "disabled"
        registered = []
        for hook in list(getattr(manifest, "provides_hooks", []) or []) + list(getattr(loaded, "hooks_registered", []) or []):
            hook_name = str(hook or "").strip()
            if hook_name in _PLUGIN_VISIBILITY_HOOK_SET and hook_name not in registered:
                registered.append(hook_name)
        registered.sort(key=_PLUGIN_VISIBILITY_HOOKS.index)
        plugins.append({
            "name": name,
            "key": plugin_key or name,
            "version": version,
            "description": description,
            # `enabled` is preserved for back-compat with older WebUI clients
            # that key off it directly. New clients should prefer `activation`.
            "enabled": enabled_flag,
            "kind": kind,
            "activation": activation,
            "hooks": registered,
        })

    return {
        "plugins": plugins,
        "empty": not bool(plugins),
        "supported_hooks": list(_PLUGIN_VISIBILITY_HOOKS),
        "read_only": True,
    }


def _handle_plugins(handler, parsed) -> bool:
    try:
        return j(handler, _plugin_visibility_payload())
    except Exception as exc:
        logger.warning("Failed to build plugin visibility payload: %s", exc)
        return j(
            handler,
            {
                "plugins": [],
                "empty": True,
                "supported_hooks": list(_PLUGIN_VISIBILITY_HOOKS),
                "read_only": True,
                "unavailable": True,
            },
        )


_SHELL_ERROR_HTML = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Hermes is restarting</title>
</head>
<body style=\"margin:0;padding:2rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111827;color:#e5e7eb;\">
  <main style=\"max-width:40rem;margin:10vh auto;line-height:1.5;\">
    <h1 style=\"font-size:1.5rem;margin:0 0 0.75rem;\">Hermes is restarting…</h1>
    <p style=\"margin:0;color:#cbd5e1;\">The WebUI shell could not load cleanly. Refresh in a moment if this page does not update automatically.</p>
  </main>
</body>
</html>"""


def _serve_shell_unavailable(handler, exc: Exception) -> bool:
    """Return HTML for shell-route failures so `/` never renders JSON."""
    logger.warning("Failed to serve WebUI shell route: %s", exc)
    t(
        handler,
        _SHELL_ERROR_HTML,
        status=503,
        content_type="text/html; charset=utf-8",
    )
    return True


# Optional prebuilt Vite bundle: static/dist (when present). Legacy shell uses static/index.html.
# HERMES_WEBUI_UI=legacy disables SPA fallback; react uses static/dist when built.
_WEBUI_UI_MODES = frozenset({"legacy", "react"})


def _webui_ui_mode() -> str:
    raw = (os.getenv("HERMES_WEBUI_UI") or "").strip().lower()
    return raw if raw in _WEBUI_UI_MODES else ""


def _spa_dist_candidates() -> list[Path]:
    mode = _webui_ui_mode()
    if mode == "legacy":
        return []
    return [(REPO_ROOT / "static" / "dist").resolve()]


def _spa_dist_root() -> Path | None:
    for root in _spa_dist_candidates():
        if (root / "index.html").is_file():
            return root
    return None


def _react_spa_enabled() -> bool:
    return _spa_dist_root() is not None


def _build_shell_html(handler, html_path: Path) -> str:
    """Read index.html and inject runtime tokens when placeholders are present."""
    from urllib.parse import quote
    from app.domain.updates import WEBUI_VERSION
    from app.domain.extensions import inject_extension_tags

    version_token = quote(WEBUI_VERSION, safe="")
    csrf_token = ""
    try:
        from app.domain.auth import csrf_token_for_session, is_auth_enabled, parse_cookie, verify_session

        if is_auth_enabled():
            cookie_val = parse_cookie(handler)
            if cookie_val and verify_session(cookie_val):
                csrf_token = csrf_token_for_session(cookie_val) or ""
    except Exception:
        csrf_token = ""

    html = html_path.read_text(encoding="utf-8")
    if "__WEBUI_VERSION__" in html:
        html = html.replace("__WEBUI_VERSION__", version_token)
    if "__MAX_UPLOAD_BYTES__" in html:
        html = html.replace("__MAX_UPLOAD_BYTES__", str(MAX_UPLOAD_BYTES))
    if "__CSRF_TOKEN_JSON__" in html:
        html = html.replace("__CSRF_TOKEN_JSON__", json.dumps(csrf_token))
    return inject_extension_tags(html)


def _serve_react_spa(handler) -> bool:
    dist_root = _spa_dist_root()
    if dist_root is None:
        return False
    html = _build_shell_html(handler, dist_root / "index.html")
    t(handler, html, content_type="text/html; charset=utf-8")
    return True


def _handle_shutdown(handler) -> bool:
    """Shut down the WebUI server process."""
    j(handler, {"status": "shutting_down"})
    import signal
    import threading

    def _do_shutdown():
        import time
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return True


def _serve_manifest(handler) -> bool:
    """Serve static/manifest.json with the correct PWA Content-Type.

    Shared by the root (/manifest.json, /manifest.webmanifest) and
    session-prefixed (/session/manifest.json, /session/manifest.webmanifest)
    routes so Firefox Android can fetch the manifest when installing from
    a /session/<id> page.  See #2226.
    """
    static_root = REPO_ROOT / "static"
    manifest_path = (static_root / "manifest.json").resolve()
    if manifest_path.exists():
        data = manifest_path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/manifest+json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return True
    return j(handler, {"error": "not found"}, status=404)


class SessionDetailNotFound(KeyError):
    """Raised when neither the WebUI store nor the CLI/state store has a session."""


def build_session_detail_payload(
    sid: str,
    *,
    load_messages: bool = True,
    resolve_model: bool | None = None,
    msg_limit: int | None = None,
    msg_before: int | None = None,
) -> dict:
    """Build the display-merged ``session`` payload for ``GET /api/session``.

    Returns the dict that callers place under the ``{"session": ...}`` envelope.
    Raises :class:`SessionDetailNotFound` when the id resolves to neither a WebUI
    session nor a CLI/state-store transcript. This is the single source of truth
    for both the legacy ``/api/session`` bridge and the native v1 endpoint so the
    response contract (messaging merge, state.db fallback, CLI store fallback)
    stays identical across both surfaces.
    """
    if resolve_model is None:
        resolve_model = load_messages
    try:
        s = get_session(sid, metadata_only=(not load_messages))
        original_stream_id = getattr(s, "active_stream_id", None)
        _clear_stale_stream_state(s)
        cli_meta = (
            _lookup_cli_session_metadata(sid)
            if _session_requires_cli_metadata_lookup(s)
            else {}
        )
        is_messaging_session = _is_messaging_session_record(s) or _is_messaging_session_record(cli_meta)
        cli_messages = []
        state_db_messages = []
        metadata_summary = None
        _session_profile = getattr(s, "profile", None) or None
        if is_messaging_session:
            cli_messages = get_cli_session_messages(sid)
        elif load_messages:
            state_db_messages = get_state_db_session_messages(sid, profile=_session_profile)
        elif not is_messaging_session:
            metadata_summary = _metadata_only_message_summary(sid, profile=_session_profile)
        effective_model = (
            _resolve_effective_session_model_for_display(s) if resolve_model else None
        )
        effective_provider = (
            _resolve_effective_session_model_provider_for_display(s) if resolve_model else None
        )
        if load_messages:
            if is_messaging_session and cli_messages:
                _all_msgs = _merged_session_messages_for_display(s, cli_messages)
            else:
                _all_msgs = merge_session_messages_append_only(
                    s.messages,
                    state_db_messages,
                    truncation_watermark=getattr(s, "truncation_watermark", None),
                )
        else:
            if is_messaging_session and cli_messages:
                sidecar_messages = getattr(s, "messages", []) or []
                _all_msgs = merge_session_messages_append_only(cli_messages, sidecar_messages)
            else:
                if metadata_summary is None:
                    metadata_summary = _message_summary(getattr(s, "messages", []) or [])
                _summary_message_count = metadata_summary["message_count"]
                _summary_last_message_at = metadata_summary["last_message_at"]
                _all_msgs = []
        if not load_messages:
            if metadata_summary is None:
                metadata_summary = _message_summary(_all_msgs)
                _summary_message_count = metadata_summary["message_count"]
                _summary_last_message_at = metadata_summary["last_message_at"]
            if _summary_message_count == 0:
                try:
                    metadata_count = getattr(s, "_metadata_message_count", None)
                    if metadata_count is not None:
                        _summary_message_count = max(0, int(metadata_count))
                except (TypeError, ValueError):
                    pass
        else:
            _summary_message_count = None
            _summary_last_message_at = None
        if load_messages:
            _truncated_msgs, _messages_offset = _message_window_for_display(
                _all_msgs,
                msg_limit=msg_limit,
                msg_before=msg_before,
            )
            if msg_before is not None:
                _before_idx = max(0, min(int(msg_before), len(_all_msgs)))
                _slice = _all_msgs[:_before_idx]
        else:
            _truncated_msgs = []
            _messages_offset = 0
        _windowed_messages = (
            load_messages
            and msg_limit is not None
            and (msg_before is not None or len(_truncated_msgs) < len(_all_msgs))
        )
        # Resolve effective context_length with model-metadata fallback so
        # older sessions (pre-#1318) that have context_length=0 persisted
        # still render a meaningful indicator on load.  Mirrors the
        # SSE-path fallback in api/streaming.py:2333-2342.  Fixes #1436.
        #
        # #1896: _resolve_context_length_for_session_model passes
        # config_context_length, provider, and custom_providers so explicit
        # config overrides win over the 256K default fallback. Without these,
        # an old session loaded after a user upgraded to a 1M-context model
        # with `model.context_length: 1048576` in config.yaml gets a 256K
        # window in the initial UI indicator and /api/session/get response.
        _persisted_cl = getattr(s, "context_length", 0) or 0
        _threshold_tokens = getattr(s, "threshold_tokens", 0) or 0
        if (not _persisted_cl) or resolve_model:
            _model_for_lookup = (
                effective_model or getattr(s, "model", "") or ""
            ).strip()
            _fb_cl = _resolve_context_length_for_session_model(
                _model_for_lookup,
                effective_provider or getattr(s, "model_provider", None) or "",
            )
            if _fb_cl:
                if _persisted_cl and _fb_cl != _persisted_cl:
                    # The old threshold belongs to the old window. Hiding it
                    # is less misleading than rendering a stale compression
                    # threshold against a freshly resolved context length.
                    _threshold_tokens = 0
                _persisted_cl = _fb_cl
        _session_tool_calls = getattr(s, "tool_calls", []) if load_messages else []
        if (
            load_messages
            and msg_limit is not None
            and _messages_include_tool_metadata(_truncated_msgs)
        ):
            _session_tool_calls = []
        elif _windowed_messages:
            _session_tool_calls = _tool_calls_for_message_window(
                _session_tool_calls,
                _messages_offset,
                len(_truncated_msgs),
            )
        _merged_message_count = (
            _summary_message_count if _summary_message_count is not None else len(_all_msgs)
        )
        _merged_last_message_at = (
            _summary_last_message_at if _summary_last_message_at is not None else 0
        )
        if _summary_last_message_at is None and _all_msgs:
            try:
                _merged_last_message_at = max(
                    float((m or {}).get("timestamp") or 0)
                    for m in _all_msgs
                    if isinstance(m, dict)
                )
            except (TypeError, ValueError):
                _merged_last_message_at = 0
        if load_messages:
            _truncated_msgs = normalize_compaction_message_roles(_truncated_msgs)
        raw = s.compact() | {
            "messages": _truncated_msgs,
            "message_count": _merged_message_count,
            "tool_calls": _session_tool_calls,
            "active_stream_id": getattr(s, "active_stream_id", None),
            "pending_user_message": getattr(s, "pending_user_message", None),
            "pending_attachments": getattr(s, "pending_attachments", []) if load_messages else [],
            "pending_started_at": getattr(s, "pending_started_at", None),
            "context_length": _persisted_cl,
            "threshold_tokens": _threshold_tokens,
            "last_prompt_tokens": getattr(s, "last_prompt_tokens", 0) or 0,
        }
        if original_stream_id:
            try:
                journal = find_run_summary(original_stream_id)
            except Exception:
                journal = None
            if journal:
                raw["runtime_journal"] = _run_journal_status_payload(
                    journal,
                    active=bool(getattr(s, "active_stream_id", None)),
                )
        if _merged_last_message_at:
            raw["last_message_at"] = max(
                float(raw.get("last_message_at") or 0),
                _merged_last_message_at,
            )
            raw["updated_at"] = max(
                float(raw.get("updated_at") or 0),
                _merged_last_message_at,
            )
        if cli_meta and _is_messaging_session_record(cli_meta):
            raw = _merge_cli_sidebar_metadata(raw, cli_meta)
            raw["message_count"] = _merged_message_count
        if msg_before is not None:
            _truncated = load_messages and msg_limit is not None and len(_slice) > msg_limit
        else:
            _truncated = load_messages and msg_limit is not None and len(_all_msgs) > msg_limit
        raw["_messages_truncated"] = _truncated
        raw["_messages_offset"] = _messages_offset
        if effective_model:
            raw["model"] = effective_model
        if effective_provider:
            raw["model_provider"] = effective_provider
        return redact_session_data(raw)
    except KeyError:
        # Not a WebUI session -- try CLI/state store
        cli_meta = _lookup_cli_session_metadata(sid)
        msgs = get_cli_session_messages(sid)
        if msgs:
            sess = {
                "session_id": sid,
                "title": (cli_meta or {}).get("title", "CLI Session"),
                "workspace": (cli_meta or {}).get("workspace", ""),
                "model": (cli_meta or {}).get("model", "unknown"),
                "message_count": len(msgs),
                "created_at": (cli_meta or {}).get("created_at", 0),
                "updated_at": (cli_meta or {}).get("updated_at", 0),
                "last_message_at": (cli_meta or {}).get("last_message_at")
                or (cli_meta or {}).get("updated_at", 0)
                or (msgs[-1] if msgs else {"timestamp": 0}).get("timestamp", 0),
                "pinned": False,
                "archived": False,
                "project_id": None,
                "profile": (cli_meta or {}).get("profile"),
                "is_cli_session": True,
                "source_tag": (cli_meta or {}).get("source_tag"),
                "raw_source": (cli_meta or {}).get("raw_source"),
                "session_source": (cli_meta or {}).get("session_source"),
                "source_label": (cli_meta or {}).get("source_label"),
                "read_only": bool((cli_meta or {}).get("read_only")),
                "messages": msgs,
                "tool_calls": [],
            }
            sess = _merge_cli_sidebar_metadata(sess, cli_meta)
            return redact_session_data(sess)
        raise SessionDetailNotFound(sid)


def handle_get(handler, parsed) -> bool:
    """Handle all GET routes. Returns True if handled, False for 404."""

    if parsed.path.startswith("/session/static/"):
        # Strip the leading "/session" so _serve_static() sees a path that
        # starts with "/static/" (its required prefix). _serve_static enforces
        # its own path-traversal sandbox via Path.resolve()+relative_to().
        stripped = parsed._replace(path=parsed.path[len("/session"):])
        return _serve_static(handler, stripped)

    if parsed.path.startswith("/session/assets/"):
        stripped = parsed._replace(path=parsed.path[len("/session"):])
        if _react_spa_enabled():
            return _serve_react_assets(handler, stripped)
        return j(handler, {"error": "not found"}, status=404)

    if parsed.path.startswith("/assets/"):
        if _react_spa_enabled():
            return _serve_react_assets(handler, parsed)
        return j(handler, {"error": "not found"}, status=404)

    # Firefox Android resolves <link rel="manifest"> against the page URL
    # before the dynamic <base href> script runs when installing from
    # /session/<id>, producing requests like /session/manifest.json.
    # Without this guard the catch-all below returns index.html instead of
    # the manifest, and Firefox falls back to a generated letter icon.
    # See #2226.
    if parsed.path in ("/session/manifest.json", "/session/manifest.webmanifest"):
        return _serve_manifest(handler)

    if parsed.path in ("/", "/index.html") or parsed.path.startswith("/session/"):
        try:
            if _react_spa_enabled():
                return _serve_react_spa(handler)
            html = _build_shell_html(handler, _INDEX_HTML_PATH)
            t(handler, html, content_type="text/html; charset=utf-8")
            return True
        except Exception as exc:
            return _serve_shell_unavailable(handler, exc)

    if parsed.path == "/login":
        if _react_spa_enabled():
            try:
                return _serve_react_spa(handler)
            except Exception as exc:
                return _serve_shell_unavailable(handler, exc)

        _settings = load_settings()
        _bn = _html.escape(_settings.get("bot_name") or "Hermes")
        _lang = _settings.get("language", "en")
        _login_strings = _LOGIN_LOCALE[
            _resolve_login_locale_key(_lang)
        ]
        from urllib.parse import quote
        from app.domain.updates import WEBUI_VERSION
        from app.domain.users import is_multi_user_enabled

        version_token = quote(WEBUI_VERSION, safe="")
        _multi_user = is_multi_user_enabled()
        if _multi_user:
            _login_subtitle = _login_strings.get(
                "multi_user_subtitle",
                "Enter your username and password to continue",
            )
            _multi_user_attr = ' data-multi-user="1"'
            _username_attrs = ' autofocus required'
            _pw_attrs = ""
        else:
            _login_subtitle = _login_strings["subtitle"]
            _multi_user_attr = ""
            _username_attrs = ' style="display:none" aria-hidden="true" tabindex="-1"'
            _pw_attrs = " autofocus"
        _page = (
            _LOGIN_PAGE_HTML.replace("{{BOT_NAME}}", _bn)
            .replace("{{BOT_NAME_INITIAL}}", _bn[0].upper())
            .replace("{{WEBUI_VERSION}}", version_token)
            .replace("{{LANG}}", _html.escape(_login_strings["lang"]))
            .replace("{{LOGIN_TITLE}}", _html.escape(_login_strings["title"]))
            .replace("{{LOGIN_SUBTITLE}}", _html.escape(_login_subtitle))
            .replace("{{LOGIN_MULTI_USER_ATTR}}", _multi_user_attr)
            .replace("{{LOGIN_USERNAME_ATTRS}}", _username_attrs)
            .replace("{{LOGIN_PW_ATTRS}}", _pw_attrs)
            .replace(
                "{{LOGIN_MULTI_USER_SUBTITLE}}",
                _html.escape(
                    _login_strings.get(
                        "multi_user_subtitle",
                        "Enter your username and password to continue",
                    )
                ),
            )
            .replace(
                "{{LOGIN_USERNAME_PLACEHOLDER}}",
                _html.escape(_login_strings.get("username_placeholder", "Username")),
            )
            .replace(
                "{{LOGIN_USERNAME_REQUIRED}}",
                _html.escape(_login_strings.get("username_required", "Username required")),
            )
            .replace(
                "{{LOGIN_PLACEHOLDER}}", _html.escape(_login_strings["placeholder"])
            )
            .replace("{{LOGIN_BTN}}", _html.escape(_login_strings["btn"]))
            .replace("{{LOGIN_INVALID_PW}}", _html.escape(_login_strings["invalid_pw"]))
            .replace(
                "{{LOGIN_CONN_FAILED}}", _html.escape(_login_strings["conn_failed"])
            )
        )
        return t(handler, _page, content_type="text/html; charset=utf-8")

    if parsed.path == "/api/auth/status":
        from app.domain.auth import get_auth_status_payload, parse_cookie

        return j(handler, get_auth_status_payload(parse_cookie(handler)))

    if parsed.path in ("/manifest.json", "/manifest.webmanifest"):
        return _serve_manifest(handler)

    if parsed.path == "/sw.js":
        static_root = REPO_ROOT / "static"
        sw_path = (static_root / "sw.js").resolve()
        if sw_path.exists():
            # Inject the current git-derived version as the cache name so the
            # service worker cache busts automatically on every new deploy.
            from urllib.parse import quote
            from app.domain.updates import WEBUI_VERSION
            version_token = quote(WEBUI_VERSION, safe="")
            text = sw_path.read_text(encoding="utf-8").replace(
                "__WEBUI_VERSION__", version_token
            )
            data = text.encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript; charset=utf-8")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Service-Worker-Allowed", "/")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True
        return j(handler, {"error": "not found"}, status=404)

    if parsed.path == "/favicon.ico":
        static_root = REPO_ROOT / "static"
        ico_path = (static_root / "favicon.ico").resolve()
        if ico_path.exists() and ico_path.is_file():
            data = ico_path.read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", "image/x-icon")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "public, max-age=86400")
            handler.end_headers()
            handler.wfile.write(data)
        else:
            handler.send_response(204)
            handler.end_headers()
        return True

    # ── Insights / knowledge status ──
    if parsed.path == "/api/insights":
        return _handle_insights(handler, parsed)

    if parsed.path.startswith("/api/kanban/"):
        from app.domain.kanban_bridge import handle_kanban_get

        # Only treat an explicit False as "no route matched". None means the
        # bridge already sent a response via bad()/j() — emitting our own 404
        # on top of that produces concatenated JSON bodies on the wire.
        result = handle_kanban_get(handler, parsed)
        if result is False:
            return _kanban_unknown_endpoint(handler, parsed, "GET")
        return True
    if parsed.path == "/api/wiki/status":
        return _handle_llm_wiki_status(handler, parsed)
    if parsed.path == "/api/logs":
        return _handle_logs(handler, parsed)

    if parsed.path == "/health":
        return _handle_health(handler, parsed)

    if parsed.path == "/api/health/agent":
        return j(handler, build_agent_health_payload())

    if parsed.path == "/api/system/health":
        j(handler, build_system_health_payload())
        return True

    if parsed.path == "/api/models":
        return j(handler, get_available_models())

    if parsed.path == "/api/models/live":
        return _handle_live_models(handler, parsed)

    # ── Auxiliary models (GET/POST) ──
    if parsed.path == "/api/model/auxiliary":
        from app.domain.config import get_auxiliary_models
        return j(handler, get_auxiliary_models())

    if parsed.path == "/api/dashboard/status":
        from app.domain import dashboard_probe

        j(handler, dashboard_probe.get_dashboard_status())
        return True

    if parsed.path == "/api/dashboard/config":
        from app.domain import dashboard_probe

        try:
            j(handler, dashboard_probe.get_dashboard_config())
        except ValueError as exc:
            bad(handler, str(exc), status=400)
        return True

    # ── Providers (GET) ──
    if parsed.path == "/api/providers":
        return j(handler, get_providers())

    # ── Plugins/hooks visibility (read-only, no callback/source internals) ──
    if parsed.path == "/api/plugins":
        return _handle_plugins(handler, parsed)
    if parsed.path == "/api/provider/quota":
        query = parse_qs(parsed.query)
        provider_id = (query.get("provider", [""])[0] or None)
        refresh = (query.get("refresh", [""])[0] or "").strip().lower() in {"1", "true", "yes", "on"}
        return j(handler, get_provider_quota(provider_id, refresh=refresh))

    if parsed.path == "/api/provider/cost-history":
        query = parse_qs(parsed.query)
        provider_id = (query.get("provider", [""])[0] or None)
        days_raw = (query.get("days", ["7"])[0] or "7").strip()
        try:
            days = max(1, min(int(days_raw), 365))
        except (ValueError, TypeError):
            days = 7
        return j(handler, get_provider_cost_history(provider_id, days))

    if parsed.path == "/api/settings":
        settings = load_settings()
        # Never expose the stored password hash to clients
        settings.pop("password_hash", None)
        # Surface env-var precedence so the UI can disable the password field
        # instead of silently no-oping the save (#1560). The setting takes
        # precedence in api.auth.get_password_hash(), but until now the UI
        # had no way to know — see issue #1139 / #1560.
        settings["password_env_var"] = bool(
            os.getenv("HERMES_WEBUI_PASSWORD", "").strip()
        )
        # Inject the running version so the UI badge stays in sync with git tags
        # without any manual release step.
        try:
            from app.domain.updates import AGENT_VERSION, WEBUI_VERSION
            settings["webui_version"] = WEBUI_VERSION
            settings["agent_version"] = AGENT_VERSION
        except Exception:
            pass
        return j(handler, settings)

    if parsed.path == "/api/reasoning":
        # Current reasoning config (shared source of truth with the CLI —
        # reads display.show_reasoning and agent.reasoning_effort from
        # the active profile's config.yaml).
        query = parse_qs(parsed.query)
        model_id = (query.get("model", [""])[0] or "").strip() or None
        provider_id = (query.get("provider", [""])[0] or "").strip() or None
        base_url = (query.get("base_url", [""])[0] or "").strip() or None
        return j(
            handler,
            get_reasoning_status(
                model_id=model_id,
                provider_id=provider_id,
                base_url=base_url,
            ),
        )

    if parsed.path == "/api/onboarding/status":
        return j(handler, get_onboarding_status())

    if parsed.path.startswith("/extensions/"):
        from app.domain.extensions import serve_extension_static

        return serve_extension_static(handler, parsed)

    if parsed.path.startswith("/static/"):
        return _serve_static(handler, parsed)


    if parsed.path == "/api/session/worktree/status":
        query = parse_qs(parsed.query)
        sid = query.get("session_id", [""])[0]
        if not sid:
            return bad(handler, "session_id is required", status=400)
        try:
            s = get_session(sid, metadata_only=True)
        except KeyError:
            return bad(handler, "Session not found", status=404)
        try:
            from app.domain.worktrees import worktree_status_for_session

            return j(handler, {"status": worktree_status_for_session(s)})
        except ValueError as exc:
            return bad(handler, str(exc), status=400)
        except Exception as exc:
            logger.exception("failed to read worktree status for session %s", sid)
            return bad(handler, _sanitize_error(exc), status=500)

    if parsed.path == "/api/session/compress/status":
        query = parse_qs(parsed.query)
        _handle_session_compress_status(handler, query.get("session_id", [""])[0])
        return True

    if parsed.path == "/api/session":
        import time as _time
        _t0 = _time.monotonic()
        _debug_slow = os.environ.get("HERMES_DEBUG_SLOW", "")
        query = parse_qs(parsed.query)
        sid = query.get("session_id", [""])[0]
        if not sid:
            return j(handler, {"error": "session_id is required"}, status=400)
        # ?messages=0 skips the message payload for fast session switching.
        # The frontend uses this when switching conversations in the sidebar
        # (only needs metadata). The full message array is loaded lazily
        # via ?messages=1 when the message panel opens.
        load_messages = query.get("messages", ["1"])[0] != "0"
        resolve_model_default = "1" if load_messages else "0"
        resolve_model = query.get("resolve_model", [resolve_model_default])[0] != "0"
        # ?msg_limit=N returns only the last N messages (tail window).
        # Used by the frontend for fast session switching — avoids serialising
        # and sending hundreds of messages when the user only sees the most
        # recent exchange.  Older messages are loaded on-demand via scrolling.
        _msg_limit = query.get("msg_limit", [None])[0]
        try:
            msg_limit = max(1, int(_msg_limit)) if _msg_limit else None
        except (ValueError, TypeError):
            msg_limit = None
        # ?msg_before=N — 0-based index into the full message array.
        # Returns messages before this index (for scroll-to-top lazy loading).
        # Combined with msg_limit for paging.
        _msg_before = query.get("msg_before", [None])[0]
        try:
            msg_before = int(_msg_before) if _msg_before else None
        except (ValueError, TypeError):
            msg_before = None
        try:
            payload = build_session_detail_payload(
                sid,
                load_messages=load_messages,
                resolve_model=resolve_model,
                msg_limit=msg_limit,
                msg_before=msg_before,
            )
        except SessionDetailNotFound:
            return bad(handler, "Session not found", 404)
        resp = j(handler, {"session": payload})
        if _debug_slow:
            logger.warning(
                "[SLOW] session_id=%s total=%.1fms",
                sid,
                (_time.monotonic() - _t0) * 1000,
            )
        return resp

    if parsed.path == "/api/session/lineage/report":
        sid = parse_qs(parsed.query).get("session_id", [""])[0]
        if not sid:
            return bad(handler, "session_id required", 400)
        report = read_session_lineage_report(_active_state_db_path(), sid)
        if not report.get("found"):
            return bad(handler, "Session not found", 404)
        return j(handler, report)

    if parsed.path == "/api/session/recovery/audit":
        from app.domain.session_recovery import audit_session_recovery
        return j(handler, audit_session_recovery(SESSION_DIR, state_db_path=_active_state_db_path()))

    if parsed.path == "/api/session/status":
        sid = parse_qs(parsed.query).get("session_id", [""])[0]
        if not sid:
            return bad(handler, "Missing session_id")
        try:
            from app.domain.session_ops import session_status
            _clear_stale_stream_state(get_session(sid, metadata_only=True))
            return j(handler, session_status(sid))
        except KeyError:
            return bad(handler, "Session not found", 404)

    if parsed.path == "/api/session/yolo":
        sid = parse_qs(parsed.query).get("session_id", [""])[0]
        if not sid:
            return bad(handler, "Missing session_id")
        return j(handler, {"yolo_enabled": is_session_yolo_enabled(sid)})

    if parsed.path == "/api/session/usage":
        sid = parse_qs(parsed.query).get("session_id", [""])[0]
        if not sid:
            return bad(handler, "Missing session_id")
        try:
            from app.domain.session_ops import session_usage
            return j(handler, session_usage(sid))
        except KeyError:
            return bad(handler, "Session not found", 404)

    if parsed.path == "/api/background/status":
        sid = parse_qs(parsed.query).get("session_id", [""])[0]
        if not sid:
            return bad(handler, "Missing session_id")
        from app.domain.background import get_results
        return j(handler, {"results": get_results(sid)})

    if parsed.path == "/api/sessions":
        diag = RequestDiagnostics.maybe_start("GET", parsed.path, logger=logger)
        try:
            diag.stage("all_sessions")
            webui_sessions = all_sessions(diag=diag)
            diag.stage("reconcile_stale_stream_state")
            if _reconcile_stale_stream_state_for_session_rows(webui_sessions):
                diag.stage("all_sessions_after_stale_stream_reconcile")
                webui_sessions = all_sessions(diag=diag)
            diag.stage("load_settings")
            settings = load_settings()
            show_cli_sessions = bool(settings.get("show_cli_sessions"))
            if show_cli_sessions:
                diag.stage("get_cli_sessions")
                cli = get_cli_sessions()
                diag.stage("merge_cli_sessions")
                cli_by_id = {s["session_id"]: s for s in cli}
                for s in webui_sessions:
                    meta = cli_by_id.get(s.get("session_id"))
                    if not meta:
                        continue
                    if _is_messaging_session_record(meta):
                        s.update(_merge_cli_sidebar_metadata(s, meta))
                        if s.get("session_id") != meta.get("session_id"):
                            s["session_id"] = meta.get("session_id")
                    else:
                        for key in ("source_tag", "raw_source", "session_source", "source_label"):
                            if not s.get(key) and meta.get(key):
                                s[key] = meta[key]
                # Apply the same CLI visibility semantics to imported local copies so
                # low-value imported artifacts do not leak into the sidebar.
                webui_sessions = [s for s in webui_sessions if is_cli_session_row_visible(s)]
                webui_ids = {s["session_id"] for s in webui_sessions}
                from app.domain.models import _hide_from_default_sidebar as _cron_hide
                deduped_cli = [s for s in cli if s["session_id"] not in webui_ids and is_cli_session_row_visible(s) and not _cron_hide(s)]
            else:
                diag.stage("filter_webui_sessions")
                webui_sessions = [s for s in webui_sessions if not _is_cli_session_for_settings(s)]
                deduped_cli = []
            diag.stage("sort_sessions")
            merged = webui_sessions + deduped_cli
            merged.sort(
                key=lambda s: s.get("last_message_at") or s.get("updated_at", 0) or 0,
                reverse=True,
            )
            # ── Profile scoping (#1611) ────────────────────────────────────────
            # Default: filter to the active profile. ?all_profiles=1 opts into
            # the aggregate view used by the "All profiles" sidebar toggle.
            # The other_profile_count is always returned so the UI can render
            # the "Show N from other profiles" affordance without sending the
            # cross-profile rows by default.
            #
            # IMPORTANT: scope BEFORE _keep_latest_messaging_session_per_source.
            # _messaging_source_key is profile-blind (#1614 follow-up): if the
            # same Slack/Telegram identity has sessions in profiles A and B, a
            # profile-blind dedupe would discard the older one even when scoped
            # to its own profile, leaving that profile with zero rows for that
            # source. Filter first so the dedupe operates only within the active
            # profile's rows.
            diag.stage("active_profile")
            from app.domain.profiles import get_active_profile_name
            active_profile = get_active_profile_name()
            all_profiles = _all_profiles_query_flag(parsed)
            diag.stage("profile_filter")
            if all_profiles:
                scoped = merged
                other_profile_count = 0
            else:
                scoped = [s for s in merged
                          if _profiles_match(s.get("profile"), active_profile)]
                other_profile_count = len(merged) - len(scoped)
            diag.stage("messaging_dedupe")
            scoped = _keep_latest_messaging_session_per_source(
                scoped,
                show_previous_messaging_sessions=bool(
                    settings.get("show_previous_messaging_sessions")
                ),
            )
            if show_cli_sessions:
                diag.stage("cli_cap")
                scoped = _cap_recent_cli_sessions(scoped, cli_cap=CLI_VISIBLE_SESSION_CAP)
            diag.stage("redact_sessions")
            safe_merged = []
            for s in scoped:
                item = dict(s)
                if isinstance(item.get("title"), str):
                    item["title"] = _redact_text(item["title"])
                safe_merged.append(item)
            diag.stage("response_write")
            return j(handler, {
                "sessions": safe_merged,
                "cli_count": len(deduped_cli),
                "all_profiles": all_profiles,
                "active_profile": active_profile,
                "other_profile_count": other_profile_count,
                "server_time": time.time(),
                "server_tz": time.strftime("%z"),
            })
        finally:
            diag.finish()

    if parsed.path == "/api/projects":
        # ── Profile scoping (#1614) ────────────────────────────────────────
        # Default: filter to the active profile. ?all_profiles=1 returns the
        # aggregate list so settings/admin UIs can still see everything.
        from app.domain.profiles import get_active_profile_name
        active_profile = get_active_profile_name()
        all_projects = load_projects()
        all_profiles = _all_profiles_query_flag(parsed)
        if all_profiles:
            scoped = all_projects
        else:
            scoped = [p for p in all_projects
                      if _profiles_match(p.get("profile"), active_profile)]
        return j(handler, {
            "projects": scoped,
            "all_profiles": all_profiles,
            "active_profile": active_profile,
            "other_profile_count": len(all_projects) - len(scoped),
        })

    if parsed.path == "/api/session/export":
        return _handle_session_export(handler, parsed)

    if parsed.path == "/api/workspaces":
        return j(
            handler, {"workspaces": load_workspaces(), "last": get_last_workspace()}
        )

    if parsed.path == "/api/workspaces/suggest":
        qs = parse_qs(parsed.query)
        prefix = qs.get("prefix", [""])[0]
        return j(
            handler,
            {
                "suggestions": list_workspace_suggestions(prefix),
                "prefix": prefix,
            },
        )

    if parsed.path == "/api/sessions/search":
        return _handle_sessions_search(handler, parsed)

    if parsed.path == "/api/list":
        return _handle_list_dir(handler, parsed)

    if parsed.path == "/api/git/status":
        return _handle_git_status(handler, parsed)

    if parsed.path == "/api/git/branches":
        return _handle_git_branches(handler, parsed)

    if parsed.path == "/api/git/diff":
        return _handle_git_diff(handler, parsed)

    if parsed.path == "/api/personalities":
        # Read personalities from config.yaml agent.personalities section
        # (matches hermes-agent CLI behavior, not filesystem SOUL.md approach)
        from app.domain.config import reload_config as _reload_cfg

        _reload_cfg()  # pick up config.yaml changes without server restart
        from app.domain.config import get_config as _get_cfg

        _cfg = _get_cfg()
        agent_cfg = _cfg.get("agent", {})
        raw_personalities = agent_cfg.get("personalities", {})
        personalities = []
        if isinstance(raw_personalities, dict):
            for name, value in raw_personalities.items():
                desc = ""
                if isinstance(value, dict):
                    desc = value.get("description", "")
                elif isinstance(value, str):
                    desc = value[:80] + ("..." if len(value) > 80 else "")
                personalities.append({"name": name, "description": desc})
        return j(handler, {"personalities": personalities})

    if parsed.path == "/api/git-info":
        qs = parse_qs(parsed.query)
        sid = qs.get("session_id", [""])[0]
        if not sid:
            return bad(handler, "session_id required")
        try:
            s = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        from app.domain.workspace_git import GitWorkspaceError, git_status

        try:
            status = git_status(Path(s.workspace))
        except GitWorkspaceError as e:
            return _git_bad(handler, e)
        totals = status.get("totals") or {}
        info = None if not status.get("is_git") else {
            "branch": status.get("branch"),
            "dirty": totals.get("changed", 0),
            "modified": (totals.get("staged", 0) or 0) + (totals.get("unstaged", 0) or 0),
            "untracked": totals.get("untracked", 0),
            "ahead": status.get("ahead", 0),
            "behind": status.get("behind", 0),
            "is_git": True,
        }
        return j(handler, {"git": info})

    if parsed.path == "/api/commands":
        from app.domain.commands import list_commands
        return j(handler, {"commands": list_commands()})

    if parsed.path == "/api/updates/check":
        settings = load_settings()
        if not settings.get("check_for_updates", True):
            return j(handler, {"disabled": True})
        include_agent_updates = not bool(settings.get("ignore_agent_updates"))
        qs = parse_qs(parsed.query)
        force = qs.get("force", ["0"])[0] == "1"
        # ?simulate=1 returns fake behind counts for UI testing (localhost only)
        if (
            qs.get("simulate", ["0"])[0] == "1"
            and handler.client_address[0] == "127.0.0.1"
        ):
            return j(
                handler,
                {
                    "webui": {
                        "name": "webui",
                        "behind": 3,
                        "current_sha": "abc1234",
                        "latest_sha": "def5678",
                        "branch": "master",
                        "repo_url": "https://github.com/nesquena/hermes-webui",
                        "compare_url": "https://github.com/nesquena/hermes-webui/compare/abc1234...def5678",
                    },
                    "agent": {
                        "name": "agent",
                        "behind": 1 if include_agent_updates else 0,
                        "ignored": not include_agent_updates,
                        "current_sha": "aaa0001",
                        "latest_sha": "bbb0002",
                        "branch": "master",
                        "repo_url": "https://github.com/NousResearch/hermes-agent",
                        "compare_url": "https://github.com/NousResearch/hermes-agent/compare/aaa0001...bbb0002",
                    },
                    "checked_at": 0,
                },
            )
        from app.domain.updates import check_for_updates

        return j(handler, check_for_updates(force=force, include_agent=include_agent_updates))

    if parsed.path == "/api/chat/stream/status":
        from app.domain.chat_streaming import chat_stream_status_payload

        stream_id = parse_qs(parsed.query).get("stream_id", [""])[0]
        return j(handler, chat_stream_status_payload(stream_id))

    if parsed.path == "/api/chat/cancel":
        from app.domain.chat_streaming import cancel_chat_stream

        stream_id = parse_qs(parsed.query).get("stream_id", [""])[0]
        payload, status = cancel_chat_stream(stream_id)
        if status == 400:
            return bad(handler, payload.get("error", "stream_id required"))
        return j(handler, payload)

    if parsed.path == "/api/chat/stream":
        return _handle_sse_stream(handler, parsed)

    if parsed.path == "/api/terminal/output":
        return _handle_terminal_output(handler, parsed)

    if parsed.path == '/api/sessions/gateway/stream':
        return _handle_gateway_sse_stream(handler, parsed)

    if parsed.path == '/api/sessions/events':
        return _handle_session_events_stream(handler)

    if parsed.path == "/api/media":
        return _handle_media(handler, parsed)

    if parsed.path == "/api/file/raw":
        return _handle_file_raw(handler, parsed)

    if parsed.path == "/api/file/view":
        return _handle_file_view(handler, parsed)

    if parsed.path == "/api/folder/download":
        return _handle_folder_download(handler, parsed)

    if parsed.path == "/api/file":
        return _handle_file_read(handler, parsed)

    if parsed.path == "/api/approval/pending":
        return _handle_approval_pending(handler, parsed)

    if parsed.path == "/api/approval/stream":
        return _handle_approval_sse_stream(handler, parsed)

    if parsed.path == "/api/approval/inject_test":
        # Loopback-only: used by automated tests; blocked from any remote client
        if handler.client_address[0] != "127.0.0.1":
            return j(handler, {"error": "not found"}, status=404)
        return _handle_approval_inject(handler, parsed)

    if parsed.path == "/api/clarify/pending":
        return _handle_clarify_pending(handler, parsed)

    if parsed.path == "/api/clarify/stream":
        return _handle_clarify_sse_stream(handler, parsed)

    if parsed.path == "/api/clarify/inject_test":
        # Loopback-only: used by automated tests; blocked from any remote client
        if handler.client_address[0] != "127.0.0.1":
            return j(handler, {"error": "not found"}, status=404)
        return _handle_clarify_inject(handler, parsed)

    if parsed.path == "/api/onboarding/oauth/poll":
        qs = parse_qs(parsed.query)
        flow_id = qs.get("flow_id", [""])[0]
        try:
            return j(
                handler,
                poll_onboarding_oauth_flow(flow_id),
                extra_headers={"Cache-Control": "no-store"},
            )
        except ValueError as e:
            return bad(handler, str(e))
        except KeyError as e:
            return bad(handler, str(e), 404)

    # ── Cron API (GET) ──
    # All cron handlers touch cron.jobs which resolves HERMES_HOME from
    # os.environ (process-global) at call time. Wrap in cron_profile_context
    # so the TLS-active profile's jobs.json is read, not the process default.
    if parsed.path == "/api/crons":
        from cron.jobs import list_jobs
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return j(handler, {"jobs": _cron_jobs_for_api(list_jobs(include_disabled=True))})

    if parsed.path == "/api/crons/output":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_output(handler, parsed)

    if parsed.path == "/api/crons/history":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_history(handler, parsed)

    if parsed.path == "/api/crons/run":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_run_detail(handler, parsed)

    if parsed.path == "/api/crons/recent":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_recent(handler, parsed)

    if parsed.path == "/api/crons/status":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_status(handler, parsed)

    if parsed.path == "/api/crons/delivery-options":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_delivery_options(handler)

    # ── Skills API (GET) ──
    if parsed.path == "/api/skills":
        qs = parse_qs(parsed.query)
        category = qs.get("category", [None])[0]
        from app.core.security import get_current_user_from_legacy_handler

        user = get_current_user_from_legacy_handler(handler)
        data = _skills_list_from_dir(
            _active_skills_dir(),
            category=category,
            user=user,
        )
        return j(handler, {"skills": data.get("skills", [])})

    if parsed.path == "/api/skills/hub/search":
        qs = parse_qs(parsed.query)
        query = (qs.get("q", [""])[0] or "").strip()
        source = (qs.get("source", ["skills-sh"])[0] or "skills-sh").strip()
        limit_raw = qs.get("limit", ["12"])[0]
        try:
            limit = max(1, min(50, int(limit_raw)))
        except (TypeError, ValueError):
            limit = 12
        if not query:
            return j(handler, {"results": []})
        try:
            from tools.skills_hub import GitHubAuth, create_source_router, unified_search

            from app.domain.skill_hub_search import (
                group_hub_search_results,
                hub_search_limit,
                is_repo_hub_query,
                serialize_hub_search_meta,
            )

            effective_limit = hub_search_limit(query, limit)
            auth = GitHubAuth()
            sources = create_source_router(auth)
            metas = unified_search(
                query, sources, source_filter=source, limit=effective_limit
            )
            results = [serialize_hub_search_meta(meta) for meta in metas]
            payload = {
                "results": results,
                "query": query,
                "source": source,
                "limit": effective_limit,
            }
            if is_repo_hub_query(query) or len(
                {r.get("repo") for r in results if r.get("repo")}
            ) == 1:
                payload["groups"] = group_hub_search_results(results)
            return j(handler, payload)
        except ImportError:
            return j(handler, {"results": [], "error": "skills hub unavailable"}, status=503)
        except Exception as e:
            logger.warning("skills hub search failed: %s", e, exc_info=True)
            return bad(handler, _sanitize_error(e), 500)

    if parsed.path == "/api/skills/content":
        qs = parse_qs(parsed.query)
        name = qs.get("name", [""])[0]
        if not name:
            return j(handler, {"error": "name required"}, status=400)
        file_path = qs.get("file", [""])[0]
        if file_path:
            # Serve a linked file from the skill directory
            import re as _re

            if _re.search(r"[*?\[\]]", name):
                return bad(handler, "Invalid skill name", 400)
            skills_dir = _active_skills_dir()
            skill_dir, _skill_md = _find_skill_in_dirs(
                name, _active_skill_search_dirs(skills_dir)
            )
            if not skill_dir:
                return bad(handler, "Skill not found", 404)
            target = (skill_dir / file_path).resolve()
            try:
                target.relative_to(skill_dir.resolve())
            except ValueError:
                return bad(handler, "Invalid file path", 400)
            if not target.exists() or not target.is_file():
                return bad(handler, "File not found", 404)
            return j(
                handler,
                {"content": target.read_text(encoding="utf-8"), "path": file_path},
            )
        data = _skill_view_from_active_dir(name)
        if not isinstance(data.get("linked_files"), dict):
            data["linked_files"] = {}
        return j(handler, data)

    # ── Memory API (GET) ──
    if parsed.path == "/api/memory":
        return _handle_memory_read(handler)

    # ── Profile API (GET) ──
    if parsed.path == "/api/profiles":
        from app.core.security import get_current_user_from_legacy_handler
        from app.domain.profiles import (
            ProfileAccessError,
            ensure_profile_management_allowed,
            list_profiles_api,
            get_active_profile_name,
            active_profile_for_user,
            filter_profiles_for_user,
        )

        user = get_current_user_from_legacy_handler(handler)
        try:
            ensure_profile_management_allowed(user)
        except ProfileAccessError as exc:
            return bad(handler, str(exc), 403)
        profiles = filter_profiles_for_user(list_profiles_api(), user)
        active = active_profile_for_user(get_active_profile_name(), user)
        return j(handler, {"profiles": profiles, "active": active})

    if parsed.path == "/api/profile/active":
        from app.domain.profiles import get_active_profile_name, get_active_hermes_home

        return j(
            handler,
            {"name": get_active_profile_name(), "path": str(get_active_hermes_home())},
        )

    # ── Gateway Status (GET) ──
    if parsed.path == "/api/gateway/status":
        import datetime
        identity_map = _load_gateway_session_identity_map()
        sessions_path = _gateway_session_metadata_path()

        # Detect whether the gateway process is alive, independent of
        # connected messaging platforms.  An empty identity_map just
        # means zero platforms connected, not that the gateway is down.
        #
        # agent_health.build_agent_health_payload() is the authoritative
        # signal: it reads gateway.status runtime metadata and returns a
        # tri-state `alive` field (True/False/None).  This avoids the
        # false-negative where the gateway is running but has zero active
        # messaging sessions (empty identity_map).
        #
        # `alive` tri-state semantics:
        #   True  → gateway process is alive
        #   False → gateway metadata exists but process is down
        #   None  → no gateway metadata/status available; this WebUI
        #           setup is probably not configured with a gateway
        health = build_agent_health_payload()
        alive = health.get("alive")
        if alive is True:
            running = True
            configured = True
        elif alive is False:
            running = False
            configured = True
        else:  # alive is None → gateway not configured / unavailable
            running = bool(identity_map)
            configured = bool(identity_map)

        platforms_set: set[str] = set()
        for meta in identity_map.values():
            raw = meta.get("raw_source") or meta.get("platform") or ""
            norm = _normalize_messaging_source(raw)
            if norm:
                platforms_set.add(norm)
        _PLATFORM_LABELS = {
            "telegram": "Telegram",
            "discord": "Discord",
            "slack": "Slack",
            "email": "Email",
            "web": "Web",
            "api": "API",
        }
        platforms = sorted(
            [{"name": p, "label": _PLATFORM_LABELS.get(p, p.title())} for p in platforms_set],
            key=lambda x: x["label"],
        )
        last_active = ""
        if running and sessions_path.exists():
            try:
                mtime = sessions_path.stat().st_mtime
                last_active = datetime.datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                pass
        return j(handler, {
            "running": running,
            "configured": configured,
            "platforms": platforms,
            "last_active": last_active,
            "session_count": len(identity_map),
        })

    # ── MCP Servers (GET) ──
    if parsed.path == "/api/mcp/servers":
        return _handle_mcp_servers_list(handler, parsed)

    # ── MCP Tools (GET) ──
    if parsed.path == "/api/mcp/tools":
        return _handle_mcp_tools_list(handler)

    if parsed.path == "/api/notes/sources":
        return _handle_notes_sources_list(handler)
    if parsed.path == "/api/notes/search":
        return _handle_notes_search(handler, parsed)
    if parsed.path == "/api/notes/item":
        return _handle_notes_item(handler, parsed)

    # ── Checkpoints / Rollback (GET) ──
    if parsed.path == "/api/rollback/list":
        qs = parse_qs(parsed.query)
        workspace = qs.get("workspace", [""])[0]
        if not workspace:
            return bad(handler, "workspace query parameter is required")
        try:
            from app.domain.rollback import list_checkpoints
            return j(handler, list_checkpoints(workspace))
        except ValueError as e:
            return bad(handler, str(e))
        except Exception as e:
            logger.exception("rollback/list failed")
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/rollback/diff":
        qs = parse_qs(parsed.query)
        workspace = qs.get("workspace", [""])[0]
        checkpoint = qs.get("checkpoint", [""])[0]
        if not workspace or not checkpoint:
            return bad(handler, "workspace and checkpoint query parameters are required")
        try:
            from app.domain.rollback import get_checkpoint_diff
            return j(handler, get_checkpoint_diff(workspace, checkpoint))
        except ValueError as e:
            return bad(handler, str(e))
        except Exception as e:
            logger.exception("rollback/diff failed")
            return bad(handler, str(e), status=500)

    return False  # 404


# ── GET route helpers


def handle_post(handler, parsed) -> bool:
    """Handle all POST routes. Returns True if handled, False for 404."""
    diag = RequestDiagnostics.maybe_start("POST", parsed.path, logger=logger)
    if parsed.path == "/api/csp-report":
        if diag:
            diag.stage("csp_report")
        try:
            return _handle_csp_report(handler)
        finally:
            if diag:
                diag.finish()
    # CSRF: reject cross-origin or tokenless authenticated browser requests.
    # /api/auth/login has no authenticated session token yet, and /api/csp-report
    # is intentionally unauthenticated for browser-generated violation reports.
    if diag:
        diag.stage("csrf")
    if not _csrf_exempt_path(parsed.path) and not _check_csrf(handler):
        try:
            return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
        finally:
            if diag:
                diag.finish()

    if parsed.path == "/api/shutdown":
        return _handle_shutdown(handler)

    if parsed.path == "/api/upload":
        return handle_upload(handler)
    if parsed.path == "/api/upload/extract":
        return handle_upload_extract(handler)

    if parsed.path == "/api/transcribe":
        return handle_transcribe(handler)

    if parsed.path == "/api/client-events/log":
        if diag:
            diag.stage("read_client_event_body")
        return _handle_client_event_log(
            handler, _read_client_event_payload(handler)
        )

    if diag:
        diag.stage("read_body")
    try:
        body = read_body(handler)
    except Exception:
        if diag:
            diag.finish()
        raise

    if parsed.path == "/api/session/recovery/repair-safe":
        from app.domain.session_recovery import repair_safe_session_recovery
        result = repair_safe_session_recovery(SESSION_DIR, state_db_path=_active_state_db_path())
        return j(handler, result, status=200 if result.get("clean") else 409)

    if parsed.path.startswith("/api/kanban/"):
        from app.domain.kanban_bridge import handle_kanban_post

        result = handle_kanban_post(handler, parsed, body)
        if result is False:
            return _kanban_unknown_endpoint(handler, parsed, "POST")
        return True
    if parsed.path == "/api/dashboard/config":
        from app.domain import dashboard_probe

        try:
            j(handler, dashboard_probe.save_dashboard_config(body))
        except ValueError as exc:
            bad(handler, str(exc), status=400)
        except Exception as exc:
            logger.exception("dashboard config save failed")
            bad(handler, str(exc), status=500)
        return True

    if parsed.path == "/api/session/new":
        try:
            workspace = str(resolve_trusted_workspace(body.get("workspace"))) if body.get("workspace") else None
        except (TypeError, ValueError) as e:
            return bad(handler, str(e))
        worktree_info = None
        worktree_requested = (
            body.get("worktree") is True
            or str(body.get("worktree")).strip().lower() in {"1", "true", "yes", "on"}
        )
        if worktree_requested:
            try:
                from app.domain.worktrees import create_worktree_for_workspace
                base_workspace = workspace
                if not base_workspace:
                    base_workspace = str(resolve_trusted_workspace(get_last_workspace()))
                worktree_info = create_worktree_for_workspace(base_workspace)
                workspace = worktree_info["path"]
            except (TypeError, ValueError) as e:
                return bad(handler, str(e), status=400)
            except Exception as e:
                logger.exception("failed to create worktree-backed session")
                return bad(handler, f"Failed to create worktree: {e}", status=500)
        model, model_provider = _session_model_state_from_request(
            body.get("model"),
            body.get("model_provider"),
        )
        # Use the profile sent by the client tab (if any) so that two tabs on
        # different profiles never clobber each other via the process-level global.
        # ── Memory lifecycle: commit the previous session before starting a new one ──
        prev_session_id = body.get("prev_session_id")
        if prev_session_id:
            try:
                from app.domain.session_lifecycle import commit_session_memory
                from app.domain.config import SESSION_AGENT_CACHE, SESSION_AGENT_CACHE_LOCK
                prev_agent = None
                with SESSION_AGENT_CACHE_LOCK:
                    _cached = SESSION_AGENT_CACHE.get(prev_session_id)
                    if _cached:
                        prev_agent = _cached[0]
                commit_session_memory(prev_session_id, agent=prev_agent)
            except Exception:
                logger.debug("Lifecycle commit for prev_session %s failed", prev_session_id, exc_info=True)
        s = new_session(
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            profile=body.get("profile") or None,
            project_id=body.get("project_id") or None,
            worktree_info=worktree_info,
        )
        if worktree_info:
            publish_session_list_changed("session_new")
        return j(handler, {"session": s.compact() | {"messages": s.messages}})

    if parsed.path == "/api/session/duplicate":
        try:
            sid = body.get("session_id")
            if not sid:
                return bad(handler, "session_id is required")

            session = Session.load(sid)
            if not session:
                # 404, not 400 — missing resource, not a malformed request.
                return bad(handler, "Session not found", status=404)

            # Deep-copy mutable lists so the duplicate is *actually* independent.
            # `Session.__init__` does `self.messages = messages or []` — plain
            # assignment, no copy. Without deepcopy, both sessions share the same
            # list object in memory; appending to one mutates the other.
            # Items inside `messages` are dicts with mutable values (tool_calls,
            # content arrays), so a shallow `list(...)` is not enough.
            copied_session = Session(
                session_id=uuid.uuid4().hex[:12],
                # Defensive: legacy sessions may have title=None on disk; fall back to 'Untitled'
                # so `+ " (copy)"` doesn't TypeError.
                title=(session.title or "Untitled") + " (copy)",
                workspace=session.workspace,
                model=session.model,
                model_provider=session.model_provider,
                messages=copy.deepcopy(session.messages),
                tool_calls=copy.deepcopy(session.tool_calls),
                # Reset ephemeral / per-session-instance flags. Duplicating an
                # archived conversation should produce a visible (un-archived)
                # copy; pinned status doesn't transfer either.
                pinned=False,
                archived=False,
                project_id=session.project_id,
                profile=session.profile,
                input_tokens=session.input_tokens,
                output_tokens=session.output_tokens,
                estimated_cost=session.estimated_cost,
                # Per-session settings the user may have customized — carry them over
                # so the duplicate behaves identically until further edits. Compression
                # anchor + last_prompt_tokens are intentionally NOT carried — those
                # re-derive on the next turn.
                personality=session.personality,
                enabled_toolsets=getattr(session, "enabled_toolsets", None),
                context_length=getattr(session, "context_length", None),
                threshold_tokens=getattr(session, "threshold_tokens", None),
                created_at=time.time(),
                updated_at=time.time(),
            )

            with LOCK:
                SESSIONS[copied_session.session_id] = copied_session
                SESSIONS.move_to_end(copied_session.session_id)
                while len(SESSIONS) > SESSIONS_MAX:
                    SESSIONS.popitem(last=False)
            # Persist immediately. The pre-PR flow (/api/session/new + /api/session/rename)
            # accidentally avoided this because `/api/session/rename` calls `s.save()`.
            # Without this explicit save, the duplicate is in-memory only — if the user
            # refreshes before sending a turn, the duplicate vanishes.
            copied_session.save()
            publish_session_list_changed("session_duplicate")

            return j(handler, {"session": copied_session.compact() | {"messages": copied_session.messages}})
        except Exception as e:
            return bad(handler, str(e))

    if parsed.path == "/api/default-model":
        try:
            return j(handler, set_hermes_default_model(body.get("model")))
        except ValueError as e:
            return bad(handler, str(e))
        except RuntimeError as e:
            return bad(handler, str(e), 500)

    # ── Auxiliary model set (POST) ──
    if parsed.path == "/api/model/set":
        scope = str(body.get("scope") or "").strip()
        task = str(body.get("task") or "").strip()
        provider = str(body.get("provider") or "auto").strip()
        model = str(body.get("model") or "").strip()
        if scope == "auxiliary":
            from app.domain.config import set_auxiliary_model
            try:
                return j(handler, set_auxiliary_model(task, provider, model))
            except Exception as exc:
                return bad(handler, str(exc), status=400)
        if scope == "main":
            try:
                return j(handler, set_hermes_default_model(model))
            except ValueError as exc:
                return bad(handler, str(exc), status=400)
        return bad(handler, f"unknown scope: {scope}", status=400)

    # ── Providers (POST) ──
    if parsed.path == "/api/providers":
        provider_id = (body.get("provider") or "").strip().lower()
        api_key = body.get("api_key")
        if not provider_id:
            return bad(handler, "provider is required")
        if api_key is not None:
            api_key = str(api_key).strip() or None
        result = set_provider_key(provider_id, api_key)
        if not result.get("ok"):
            return bad(handler, result.get("error", "Unknown error"))
        return j(handler, result)

    if parsed.path == "/api/providers/delete":
        provider_id = (body.get("provider") or "").strip().lower()
        if not provider_id:
            return bad(handler, "provider is required")
        result = remove_provider_key(provider_id)
        if not result.get("ok"):
            return bad(handler, result.get("error", "Unknown error"))
        return j(handler, result)

    if parsed.path == "/api/reasoning":
        # CLI-parity /reasoning handler — writes to the same config.yaml keys
        # the CLI uses (display.show_reasoning, agent.reasoning_effort) so a
        # preference set via WebUI is honoured in the terminal REPL and vice
        # versa.  Body is one of:
        #   {"display": "show"|"hide"|"on"|"off"}   → display.show_reasoning
        #   {"effort":  "none"|"minimal"|"low"|"medium"|"high"|"xhigh"}
        #                                            → agent.reasoning_effort
        try:
            display = body.get("display")
            effort = body.get("effort")
            if display is not None:
                flag = str(display).strip().lower()
                if flag in ("show", "on", "true", "1"):
                    return j(handler, set_reasoning_display(True))
                if flag in ("hide", "off", "false", "0"):
                    return j(handler, set_reasoning_display(False))
                return bad(handler, f"display must be show|hide|on|off (got '{display}')")
            if effort is not None:
                return j(handler, set_reasoning_effort(effort))
            return bad(handler, "reasoning: must supply 'display' or 'effort'")
        except ValueError as e:
            return bad(handler, str(e))
        except RuntimeError as e:
            return bad(handler, str(e), 500)

    if parsed.path == "/api/admin/reload":
        # Hot-reload api.models module to pick up code changes without restart.
        import importlib
        from app.domain import models as _models
        importlib.reload(_models)
        # Also re-expose get_session from the reloaded module so routes.py
        # continues to work (routes.py imported it at module level).
        import app.domain.routes as _routes
        _routes.get_session = _models.get_session
        _routes.Session = _models.Session
        _routes.compact = _models.compact
        return j(handler, {"status": "ok", "reloaded": "app.domain.models"})

    if parsed.path == "/api/sessions/cleanup":
        return _handle_sessions_cleanup(handler, body, zero_only=False)

    if parsed.path == "/api/sessions/cleanup_zero_message":
        return _handle_sessions_cleanup(handler, body, zero_only=True)

    if parsed.path == "/api/session/rename":
        try:
            require(body, "session_id", "title")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            s = get_session(body["session_id"])
            s = _ensure_full_session_before_mutation(body["session_id"], s)
        except KeyError:
            return bad(handler, "Session not found", 404)
        with _get_session_agent_lock(body["session_id"]):
            s.title = str(body["title"]).strip()[:80] or "Untitled"
            s.save()
        publish_session_list_changed("session_rename")
        return j(handler, {"session": s.compact()})

    if parsed.path == "/api/personality/set":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        if "name" not in body:
            return bad(handler, "Missing required field: name")
        sid = body["session_id"]
        name = body["name"].strip()
        try:
            s = get_session(sid)
            s = _ensure_full_session_before_mutation(sid, s)
        except KeyError:
            return bad(handler, "Session not found", 404)
        # Resolve personality from config.yaml agent.personalities section
        # (matches hermes-agent CLI behavior)
        prompt = ""
        if name:
            from app.domain.config import reload_config as _reload_cfg2

            _reload_cfg2()  # pick up config changes without restart
            from app.domain.config import get_config as _get_cfg2

            _cfg2 = _get_cfg2()
            agent_cfg = _cfg2.get("agent", {})
            raw_personalities = agent_cfg.get("personalities", {})
            if not isinstance(raw_personalities, dict) or name not in raw_personalities:
                return bad(
                    handler, f'Personality "{name}" not found in config.yaml', 404
                )
            value = raw_personalities[name]
            # Resolve prompt using the same logic as hermes-agent cli.py
            if isinstance(value, dict):
                parts = [value.get("system_prompt", "") or value.get("prompt", "")]
                if value.get("tone"):
                    parts.append(f"Tone: {value['tone']}")
                if value.get("style"):
                    parts.append(f"Style: {value['style']}")
                prompt = "\n".join(p for p in parts if p)
            else:
                prompt = str(value)
        with _get_session_agent_lock(sid):
            s.personality = name if name else None
            s.save()
        return j(handler, {"ok": True, "personality": s.personality, "prompt": prompt})

    if parsed.path == "/api/session/toolsets":
        """Set or clear per-session toolset override (#493).

        POST body: { session_id, toolsets: [...] | null }
        - toolsets: list of toolset names to restrict the session to, or null to clear.
        """
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        sid = body["session_id"]
        toolsets = body.get("toolsets")
        # Validate: if not None, must be a non-empty list of strings
        if toolsets is not None:
            if not isinstance(toolsets, list) or not toolsets:
                return bad(handler, "toolsets must be a non-empty list or null")
            if not all(isinstance(t, str) and t for t in toolsets):
                return bad(handler, "each toolset must be a non-empty string")
        try:
            s = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        with _get_session_agent_lock(sid):
            s.enabled_toolsets = toolsets
            s.save()
        return j(handler, {"ok": True, "enabled_toolsets": s.enabled_toolsets})

    if parsed.path == "/api/session/draft":
        # GET ?session_id=X  → return current draft
        # POST body          → save draft { session_id, text?, files? }
        # HTTP method is in handler.command (e.g. "POST", "GET"), parsed has no .method
        if handler.command == "GET":
            query = parse_qs(parsed.query)
            sid = query.get("session_id", [""])[0] if parsed.query else ""
            if not sid:
                return bad(handler, "session_id is required", 400)
            try:
                s = get_session(sid)
            except KeyError:
                return bad(handler, "Session not found", 404)
            draft = getattr(s, "composer_draft", {}) or {}
            return j(handler, {"draft": draft})
        # POST
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        sid = body["session_id"]
        text = body.get("text")
        files = body.get("files")
        # Stage-326 hardening (per Opus advisor): size + type validation on
        # the draft inputs. Without this, a misbehaving or malicious client
        # can persist multi-MB strings into the session JSON on every keystroke
        # via the 400ms debounced auto-save.
        _MAX_DRAFT_TEXT = 50_000  # 50 KB cap on textarea content
        _MAX_DRAFT_FILES = 50  # max number of attached file references
        if text is not None and not isinstance(text, str):
            text = ""
        if isinstance(text, str) and len(text) > _MAX_DRAFT_TEXT:
            text = text[:_MAX_DRAFT_TEXT]
        if files is not None and not isinstance(files, list):
            files = []
        if isinstance(files, list) and len(files) > _MAX_DRAFT_FILES:
            files = files[:_MAX_DRAFT_FILES]
        try:
            s = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        with _get_session_agent_lock(sid):
            draft = getattr(s, "composer_draft", {}) or {}
            if text is not None:
                draft["text"] = text
            if files is not None:
                draft["files"] = files
            s.composer_draft = draft
            # Draft persistence is not conversation activity. Touching updated_at
            # here makes the active-session external-refresh poll force-reload the
            # current chat every few seconds while the user is typing, and that
            # delayed reload can restore an older draft over newer local input.
            s.save(touch_updated_at=False, skip_index=True)
        return j(handler, {"ok": True, "draft": s.composer_draft})

    if parsed.path == "/api/session/update":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            s = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)
        old_ws = getattr(s, "workspace", "")
        old_model = getattr(s, "model", None)
        old_provider = getattr(s, "model_provider", None)
        try:
            new_ws = str(resolve_trusted_workspace(body.get("workspace", s.workspace)))
        except ValueError as e:
            return bad(handler, str(e))
        with _get_session_agent_lock(body["session_id"]):
            s.workspace = new_ws
            if "model" in body or "model_provider" in body:
                model, provider = _session_model_state_from_request(
                    body.get("model", s.model),
                    body.get("model_provider") if "model_provider" in body else None,
                    getattr(s, "model_provider", None),
                )
                if model is not None:
                    s.model = model
                s.model_provider = provider
                if (
                    str(old_model or "") != str(getattr(s, "model", "") or "")
                    or str(old_provider or "") != str(getattr(s, "model_provider", "") or "")
                ):
                    s.context_length = _resolve_context_length_for_session_model(
                        getattr(s, "model", None),
                        getattr(s, "model_provider", None),
                    )
                    s.threshold_tokens = 0
                    s.last_prompt_tokens = 0
                    from app.domain.config import _evict_session_agent

                    _evict_session_agent(body["session_id"])
            s.save()
        if str(old_ws or "") != str(new_ws or ""):
            try:
                from app.domain.terminal import close_terminal
                close_terminal(body["session_id"])
            except Exception:
                logger.debug("Failed to close workspace terminal after workspace update")
        set_last_workspace(new_ws)
        return j(handler, {"session": s.compact() | {"messages": s.messages}})
    if parsed.path == "/api/session/worktree/remove":
        sid = body.get("session_id", "")
        if not sid or not isinstance(sid, str) or not sid.strip():
            return bad(handler, "session_id must be a non-empty string", status=400)
        sid = sid.strip()
        if not all(c in '0123456789abcdefghijklmnopqrstuvwxyz_' for c in sid):
            return bad(handler, "Invalid session_id", 400)
        try:
            s = get_session(sid, metadata_only=True)
        except KeyError:
            return bad(handler, "Session not found", status=404)
        force = bool(body.get("force", False))
        try:
            from app.domain.worktrees import remove_worktree_for_session

            result = remove_worktree_for_session(s, force=force)
            return j(handler, result)
        except ValueError as exc:
            return bad(handler, str(exc), status=400)
        except Exception as exc:
            logger.exception("failed to remove worktree for session %s", sid)
            return bad(handler, _sanitize_error(exc), status=500)

    if parsed.path == "/api/session/delete":
        sid = body.get("session_id", "")
        if not sid:
            return bad(handler, "session_id is required")
        if not all(c in '0123456789abcdefghijklmnopqrstuvwxyz_' for c in sid):
            return bad(handler, "Invalid session_id", 400)
        cli_meta_for_delete = _lookup_cli_session_metadata(sid)
        if cli_meta_for_delete.get("read_only"):
            return bad(handler, "Read-only imported sessions cannot be deleted from WebUI", 400)
        is_messaging_session = _is_messaging_session_id(sid)
        worktree_retained = _worktree_retained_payload_for_session_id(sid)
        # Delete from WebUI session store
        with LOCK:
            SESSIONS.pop(sid, None)
        # Evict cached agent so turn count doesn't leak into a recycled session
        from app.domain.config import _evict_session_agent
        _evict_session_agent(sid)
        try:
            p = (SESSION_DIR / f"{sid}.json").resolve()
            p.relative_to(SESSION_DIR.resolve())
        except Exception:
            return bad(handler, "Invalid session_id", 400)
        try:
            p.unlink(missing_ok=True)
            p.with_suffix('.json.bak').unlink(missing_ok=True)
        except Exception:
            logger.debug("Failed to unlink session file %s", p)
        try:
            prune_session_from_index(sid)
        except Exception:
            logger.debug("Failed to prune deleted session from index: %s", sid, exc_info=True)
        try:
            from app.domain.upload import _session_attachment_dir

            shutil.rmtree(_session_attachment_dir(sid), ignore_errors=True)
        except Exception:
            logger.debug("Failed to clean attachment dir for deleted session %s", sid)
        # Prune the per-session agent lock so deleted sessions don't leak
        # Lock entries in SESSION_AGENT_LOCKS forever.
        with SESSION_AGENT_LOCKS_LOCK:
            SESSION_AGENT_LOCKS.pop(sid, None)
        try:
            from app.domain.terminal import close_terminal
            close_terminal(sid)
        except Exception:
            logger.debug("Failed to close workspace terminal for deleted session %s", sid)
        # Also delete from CLI state.db for CLI sessions shown in sidebar,
        # but never erase external messaging channel memory via WebUI delete.
        if not is_messaging_session:
            try:
                from app.domain.models import delete_cli_session

                delete_cli_session(sid)
            except Exception:
                logger.debug("Failed to delete CLI session %s", sid)
        publish_session_list_changed("session_delete")
        return j(handler, {"ok": True, **worktree_retained})

    if parsed.path == "/api/session/clear":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            s = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)
        sid = body["session_id"]
        with _get_session_agent_lock(sid):
            s.messages = []
            s.tool_calls = []
            s.title = "Untitled"
            s.save()
        # Evict cached agent outside the per-session lock.  Eviction may run a
        # boundary memory commit for batch-extraction providers, and provider
        # I/O must not hold the session mutation lock.
        from app.domain.config import _evict_session_agent
        _evict_session_agent(sid)
        return j(handler, {"ok": True, "session": s.compact()})

    if parsed.path == "/api/session/truncate":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        if body.get("keep_count") is None:
            return bad(handler, "Missing required field(s): keep_count")
        try:
            s = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)
        keep = int(body["keep_count"])
        with _get_session_agent_lock(body["session_id"]):
            s.messages = s.messages[:keep]
            try:
                from app.domain.session_ops import _truncation_watermark_for
                s.truncation_watermark = _truncation_watermark_for(s.messages)
            except Exception:
                s.truncation_watermark = 0.0
            s.save()
        return j(
            handler, {"ok": True, "session": s.compact() | {"messages": s.messages}}
        )

    if parsed.path == "/api/session/branch":
        # Fork a conversation from any message point (#465).
        # Accepts: {session_id, keep_count?, title?}
        #   keep_count: number of messages to copy (0=empty, undefined=full history)
        #   title: custom title (defaults to "<original title> (fork)")
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        # Reject non-string session_id explicitly so the failure surfaces as a
        # 400 instead of a generic 500 from get_session() raising TypeError.
        # (Opus pre-release follow-up.)
        if not isinstance(body["session_id"], str):
            return bad(handler, "session_id must be a string")
        try:
            source = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)

        keep_count = body.get("keep_count")
        if keep_count is not None:
            try:
                keep_count = int(keep_count)
            except (ValueError, TypeError):
                return bad(handler, "keep_count must be an integer")
            # Negative slice (`messages[:-N]`) returns "all but last N", which
            # is a confusing fork semantic. Reject explicitly so the user
            # doesn't accidentally fork a session with the tail truncated when
            # they meant to copy the prefix. (Opus pre-release follow-up.)
            if keep_count < 0:
                return bad(handler, "keep_count must be non-negative")

        custom_title = body.get("title")
        if custom_title:
            custom_title = str(custom_title).strip()[:80] or None

        # Build messages slice in the same coordinate space exposed by GET
        # /api/session so frontend keep_count values from merged messaging
        # transcripts do not silently become full sidecar copies.
        try:
            source.save()
        except Exception:
            pass
        cli_meta = _lookup_cli_session_metadata(source.session_id) if _session_requires_cli_metadata_lookup(source) else {}
        is_messaging_session = _is_messaging_session_record(source) or _is_messaging_session_record(cli_meta)
        cli_messages = get_cli_session_messages(source.session_id) if is_messaging_session else []
        source_messages = (
            _merged_session_messages_for_display(source, cli_messages)
            if is_messaging_session and cli_messages
            else list(source.messages or [])
        )
        if keep_count is not None:
            forked_messages = source_messages[:keep_count]
        else:
            forked_messages = list(source_messages)

        # Derive title
        if custom_title:
            branch_title = custom_title
        else:
            source_title = source.title or "Untitled"
            branch_title = f"{source_title} (fork)"

        # Create new session inheriting workspace/model/profile
        branch = Session(
            workspace=source.workspace,
            model=source.model,
            profile=getattr(source, "profile", None),
            title=branch_title,
            messages=forked_messages,
            parent_session_id=source.session_id,
            session_source="fork",
        )
        with LOCK:
            SESSIONS[branch.session_id] = branch
            SESSIONS.move_to_end(branch.session_id)
            while len(SESSIONS) > SESSIONS_MAX:
                SESSIONS.popitem(last=False)

        # Persist only if there are messages (matches new_session pattern)
        if forked_messages:
            branch.save()
            publish_session_list_changed("session_branch")

        return j(handler, {
            "session_id": branch.session_id,
            "title": branch_title,
            "parent_session_id": source.session_id,
        })

    if parsed.path == "/api/session/compress/start":
        return _handle_session_compress_start(handler, body)

    if parsed.path == "/api/session/compress":
        return _handle_session_compress(handler, body)

    if parsed.path == "/api/session/conversation-rounds":
        return _handle_conversation_rounds(handler, body)

    if parsed.path == "/api/session/handoff-summary":
        return _handle_handoff_summary(handler, body)

    if parsed.path == "/api/session/retry":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            from app.domain.session_ops import retry_last
            result = retry_last(body["session_id"])
            return j(handler, {"ok": True, **result})
        except KeyError:
            return bad(handler, "Session not found", 404)
        except ValueError as e:
            return j(handler, {"error": str(e)})

    if parsed.path == "/api/session/undo":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            from app.domain.session_ops import undo_last
            result = undo_last(body["session_id"])
            return j(handler, {"ok": True, **result})
        except KeyError:
            return bad(handler, "Session not found", 404)
        except ValueError as e:
            return j(handler, {"error": str(e)})

    # ── YOLO mode toggle (POST) ──
    # Session-scoped only — stored in-memory on the server side.
    # Important lifecycle notes:
    #   • Page reload: state PERSISTS (frontend re-fetches via GET endpoint)
    #   • Cross-tab: state is SHARED (same server-side flag per session)
    #   • Server restart: state is LOST (in-memory only)
    #   • Cross-session: isolated (each session has its own flag)
    # Fixes #467
    if parsed.path == "/api/session/yolo":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        sid = body["session_id"]
        enabled = bool(body.get("enabled", True))
        if enabled:
            enable_session_yolo(sid)
            # Also resolve any pending approvals for this session so the
            # agent doesn't stay stuck waiting on an already-dismissed card.
            try:
                from tools.approval import _pending as _p, _lock as _l
                with _l:
                    _p.pop(sid, None)
            except Exception:
                pass
            resolve_gateway_approval(sid, "once", resolve_all=True)
        else:
            disable_session_yolo(sid)
        return j(handler, {"ok": True, "yolo_enabled": enabled})

    if parsed.path == "/api/btw":
        return _handle_btw(handler, body)

    if parsed.path == "/api/background":
        return _handle_background(handler, body)

    if parsed.path == "/api/goal":
        return _handle_goal_command(handler, body)

    if parsed.path == "/api/chat/start":
        return _handle_chat_start(handler, body, diag=diag)

    if parsed.path == "/api/chat":
        return _handle_chat_sync(handler, body)

    if parsed.path == "/api/chat/steer":
        from app.domain.streaming import _handle_chat_steer
        return _handle_chat_steer(handler, body)

    if parsed.path == "/api/terminal/start":
        return _handle_terminal_start(handler, body)

    if parsed.path == "/api/terminal/input":
        return _handle_terminal_input(handler, body)

    if parsed.path == "/api/terminal/resize":
        return _handle_terminal_resize(handler, body)

    if parsed.path == "/api/terminal/close":
        return _handle_terminal_close(handler, body)

    # ── Cron API (POST) ──
    # See GET-side comment above: wrap in cron_profile_context so writes go
    # to the TLS-active profile's jobs.json instead of the process default.
    if parsed.path == "/api/crons/create":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_create(handler, body)

    if parsed.path == "/api/crons/update":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_update(handler, body)

    if parsed.path == "/api/crons/delete":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_delete(handler, body)

    if parsed.path == "/api/crons/run":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_run(handler, body)

    if parsed.path == "/api/crons/pause":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_pause(handler, body)

    if parsed.path == "/api/crons/resume":
        from app.domain.profiles import cron_profile_context

        with cron_profile_context():
            return _handle_cron_resume(handler, body)

    # ── Git workspace ops (POST) ──
    if parsed.path == "/api/git/stage":
        return _handle_git_stage(handler, body)

    if parsed.path == "/api/git/unstage":
        return _handle_git_unstage(handler, body)

    if parsed.path == "/api/git/discard":
        return _handle_git_discard(handler, body)

    if parsed.path == "/api/git/commit-message":
        return _handle_git_commit_message(handler, body)

    if parsed.path == "/api/git/commit-message-selected":
        return _handle_git_commit_message_selected(handler, body)

    if parsed.path == "/api/git/commit":
        return _handle_git_commit(handler, body)

    if parsed.path == "/api/git/commit-selected":
        return _handle_git_commit_selected(handler, body)

    if parsed.path == "/api/git/fetch":
        return _handle_git_remote_action(handler, body, "fetch")

    if parsed.path == "/api/git/pull":
        return _handle_git_remote_action(handler, body, "pull")

    if parsed.path == "/api/git/push":
        return _handle_git_remote_action(handler, body, "push")

    if parsed.path == "/api/git/checkout":
        return _handle_git_checkout(handler, body)

    if parsed.path == "/api/git/stash-checkout":
        return _handle_git_stash_checkout(handler, body)

    # ── File ops (POST) ──
    if parsed.path == "/api/file/delete":
        return _handle_file_delete(handler, body)

    if parsed.path == "/api/file/save":
        return _handle_file_save(handler, body)

    if parsed.path == "/api/file/create":
        return _handle_file_create(handler, body)

    if parsed.path == "/api/file/rename":
        return _handle_file_rename(handler, body)

    if parsed.path == "/api/file/move":
        return _handle_file_move(handler, body)

    if parsed.path == "/api/file/create-dir":
        return _handle_create_dir(handler, body)

    if parsed.path == "/api/file/reveal":
        return _handle_file_reveal(handler, body)

    if parsed.path == "/api/file/path":
        return _handle_file_path(handler, body)

    if parsed.path == "/api/file/open-vscode":
        return _handle_file_open_vscode(handler, body)

    # ── Workspace management (POST) ──
    if parsed.path == "/api/workspaces/add":
        return _handle_workspace_add(handler, body)

    if parsed.path == "/api/workspaces/remove":
        return _handle_workspace_remove(handler, body)

    if parsed.path == "/api/workspaces/rename":
        return _handle_workspace_rename(handler, body)

    if parsed.path == "/api/workspaces/reorder":
        return _handle_workspace_reorder(handler, body)

    # ── Approval (POST) ──
    if parsed.path == "/api/approval/respond":
        return _handle_approval_respond(handler, body)

    # ── Clarify (POST) ──
    if parsed.path == "/api/clarify/respond":
        return _handle_clarify_respond(handler, body)

    # ── Commands (POST) ──
    if parsed.path == "/api/commands/exec":
        from app.domain.commands import execute_plugin_command

        command = str(body.get("command", "") or "").strip()
        if not command:
            return bad(handler, "command is required")
        try:
            return j(handler, {"output": execute_plugin_command(command)})
        except ValueError as e:
            return bad(handler, str(e), 400)
        except KeyError:
            return bad(handler, "Plugin command not found", 404)
        except RuntimeError as e:
            return bad(handler, _sanitize_error(e), 500)

    # ── Skills (POST) ──
    if parsed.path == "/api/skills/save":
        return _handle_skill_save(handler, body)

    if parsed.path == "/api/skills/delete":
        return _handle_skill_delete(handler, body)

    if parsed.path == "/api/skills/toggle":
        return _handle_skill_toggle(handler, body)

    if parsed.path == "/api/skills/install":
        return _handle_skill_install(handler, body)

    # ── Memory (POST) ──
    if parsed.path == "/api/memory/write":
        return _handle_memory_write(handler, body)

    # ── MCP discovery (POST) ──
    if parsed.path == "/api/mcp/discover":
        return _handle_mcp_discover(handler, parsed, body)

    if parsed.path.startswith("/api/mcp/servers/") and parsed.path.endswith("/test"):
        name = parsed.path[len("/api/mcp/servers/") : -len("/test")].rstrip("/")
        return _handle_mcp_server_test(handler, name, parsed, body)

    if parsed.path == "/api/mcp/servers/import":
        return _handle_mcp_servers_import(handler, parsed, body)

    # ── Profile API (POST) ──
    if parsed.path == "/api/profile/switch":
        name = body.get("name", "").strip()
        if not name:
            return bad(handler, "name is required")
        try:
            from app.core.security import get_current_user_from_legacy_handler
            from app.domain.profiles import (
                ProfileAccessError,
                _profiles_match,
                ensure_profile_switch_allowed,
                get_active_profile_name,
                set_request_profile,
                switch_profile,
                _validate_profile_name,
            )
            from app.domain.helpers import build_profile_cookie

            user = get_current_user_from_legacy_handler(handler)
            ensure_profile_switch_allowed(name, user)
            if name != 'default':
                _validate_profile_name(name)
            same_profile = _profiles_match(get_active_profile_name(), name)
            # process_wide=False: don't mutate the process-global _active_profile.
            # Per-client profile is managed via cookie + thread-local (#798).
            result = switch_profile(name, process_wide=False)
            if not same_profile:
                set_request_profile(name)
                from app.domain.config import invalidate_models_cache_after_profile_switch
                invalidate_models_cache_after_profile_switch()
            return j(handler, result, extra_headers={
                'Set-Cookie': build_profile_cookie(name),
            })
        except ProfileAccessError as exc:
            return bad(handler, str(exc), 403)
        except (ValueError, FileNotFoundError) as e:
            return bad(handler, _sanitize_error(e), 404)
        except RuntimeError as e:
            return bad(handler, str(e), 409)

    if parsed.path == "/api/profile/sync-from-default":
        from app.core.security import (
            AgentSoulAccessError,
            ensure_agent_soul_access,
            get_current_user_from_legacy_handler,
        )
        from app.domain.profiles import ProfileAccessError, ensure_profile_management_allowed

        name = body.get("name")
        if name is not None:
            name = str(name).strip()
            if not name:
                return bad(handler, "name cannot be empty")
        user = get_current_user_from_legacy_handler(handler)
        try:
            ensure_profile_management_allowed(user)
            ensure_agent_soul_access(user)
        except (ProfileAccessError, AgentSoulAccessError) as exc:
            return bad(handler, str(exc), 403)
        try:
            from app.domain.profiles import (
                sync_all_profiles_from_default_api,
                sync_profile_from_default_api,
            )

            if name:
                result = sync_profile_from_default_api(name)
            else:
                result = sync_all_profiles_from_default_api()
            return j(handler, result)
        except ValueError as e:
            return bad(handler, str(e))

    if parsed.path == "/api/profile/create":
        name = body.get("name", "").strip()
        if not name:
            return bad(handler, "name is required")
        import re as _re

        if not _re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", name):
            return bad(
                handler,
                "Invalid profile name: lowercase letters, numbers, hyphens, underscores only",
            )
        clone_from = body.get("clone_from")
        if clone_from is not None:
            clone_from = str(clone_from).strip()
            if not _re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", clone_from):
                return bad(handler, "Invalid clone_from name")
        base_url = body.get("base_url", "").strip() if body.get("base_url") else None
        api_key = body.get("api_key", "").strip() if body.get("api_key") else None
        default_model = body.get("default_model", "").strip() if body.get("default_model") else None
        model_provider = body.get("model_provider", "").strip() if body.get("model_provider") else None
        if base_url and not base_url.startswith(("http://", "https://")):
            return bad(handler, "base_url must start with http:// or https://")
        try:
            from app.core.security import get_current_user_from_legacy_handler
            from app.domain.profiles import ProfileAccessError, ensure_profile_create_allowed, create_profile_api

            ensure_profile_create_allowed(get_current_user_from_legacy_handler(handler))
            result = create_profile_api(
                name,
                clone_from=clone_from,
                clone_config=body.get("clone_config") if "clone_config" in body else None,
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
                model_provider=model_provider,
            )
            return j(handler, {"ok": True, "profile": result})
        except ProfileAccessError as exc:
            return bad(handler, str(exc), 403)
        except (ValueError, FileExistsError, RuntimeError) as e:
            return bad(handler, str(e))

    if parsed.path == "/api/profile/delete":
        name = body.get("name", "").strip()
        if not name:
            return bad(handler, "name is required")
        try:
            from app.core.security import get_current_user_from_legacy_handler
            from app.domain.profiles import (
                ProfileAccessError,
                delete_profile_api,
                ensure_profile_management_allowed,
                _validate_profile_name,
            )

            ensure_profile_management_allowed(get_current_user_from_legacy_handler(handler))
            _validate_profile_name(name)
            result = delete_profile_api(name)
            return j(handler, result)
        except ProfileAccessError as exc:
            return bad(handler, str(exc), 403)
        except (ValueError, FileNotFoundError) as e:
            return bad(handler, _sanitize_error(e))
        except RuntimeError as e:
            return bad(handler, str(e), 409)

    # ── Settings (POST) ──
    if parsed.path == "/api/settings":
        from app.domain.auth import (
            create_session,
            is_auth_enabled,
            parse_cookie,
            set_auth_cookie,
            verify_session,
        )

        if "bot_name" in body:
            body["bot_name"] = (str(body["bot_name"]) or "").strip() or "Hermes"

        auth_enabled_before = is_auth_enabled()
        current_cookie = parse_cookie(handler)
        logged_in_before = bool(current_cookie and verify_session(current_cookie))
        requested_password = bool(
            isinstance(body.get("_set_password"), str)
            and body.get("_set_password", "").strip()
        )
        requested_passwordless = bool(body.pop("_passwordless", False))
        requested_clear_password = bool(body.get("_clear_password") or requested_passwordless)
        if requested_passwordless:
            body["_clear_password"] = True

        # #1560: HERMES_WEBUI_PASSWORD env var takes precedence in
        # api.auth.get_password_hash(), so writing password_hash to settings.json
        # has no effect on auth. Refuse loudly with 409 instead of silently
        # succeeding — the previous behaviour returned 200 + a green save toast
        # while every subsequent login still required the env-var password.
        if requested_password or requested_clear_password:
            if os.getenv("HERMES_WEBUI_PASSWORD", "").strip():
                return bad(
                    handler,
                    "HERMES_WEBUI_PASSWORD env var is set — it overrides the settings password. "
                    "Unset the env var and restart the server before changing the password here.",
                    409,
                )
        if requested_passwordless:
            from app.domain.auth import _passkey_feature_flag_enabled
            from app.domain.passkeys import registered_credentials

            if not _passkey_feature_flag_enabled():
                return bad(handler, "Passkey support is disabled. Enable HERMES_WEBUI_PASSKEY before going passwordless.", 409)
            if not registered_credentials():
                return bad(handler, "Register a passkey before going passwordless.", 409)
        elif requested_clear_password:
            from app.domain.passkeys import clear_credentials

            clear_credentials()

        saved = save_settings(body)
        saved.pop("password_hash", None)  # never expose hash to client

        auth_enabled_after = is_auth_enabled()
        auth_just_enabled = bool(
            requested_password and auth_enabled_after and not auth_enabled_before
        )
        logged_in_after = logged_in_before
        new_cookie = None

        if auth_just_enabled and not logged_in_before:
            new_cookie = create_session()
            logged_in_after = True

        saved["auth_enabled"] = auth_enabled_after
        saved["logged_in"] = logged_in_after
        saved["auth_just_enabled"] = auth_just_enabled

        if not new_cookie:
            return j(handler, saved)

        response_body = json.dumps(saved, ensure_ascii=False, indent=2).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(response_body)))
        handler.send_header("Cache-Control", "no-store")
        set_auth_cookie(handler, new_cookie)
        _security_headers(handler)
        handler.end_headers()
        handler.wfile.write(response_body)
        return True

    if parsed.path == "/api/onboarding/oauth/start":
        from app.domain.auth import is_auth_enabled
        import os as _os
        if not is_auth_enabled() and not _os.getenv("HERMES_WEBUI_ONBOARDING_OPEN"):
            import ipaddress
            try:
                _xff = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                _xri = handler.headers.get("X-Real-IP", "").strip()
                _raw = handler.client_address[0]
                addr = ipaddress.ip_address(_xff or _xri or _raw)
                is_local = addr.is_loopback or addr.is_private
            except ValueError:
                is_local = False
            if not is_local:
                return bad(handler, "Onboarding OAuth is only available from local networks when auth is not enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1.", 403)
        try:
            return j(handler, start_onboarding_oauth_flow(body), extra_headers={"Cache-Control": "no-store"})
        except ValueError as e:
            return bad(handler, str(e))
        except RuntimeError as e:
            return bad(handler, str(e), 500)

    if parsed.path == "/api/onboarding/oauth/cancel":
        try:
            return j(handler, cancel_onboarding_oauth_flow(body), extra_headers={"Cache-Control": "no-store"})
        except ValueError as e:
            return bad(handler, str(e))

    if parsed.path == "/api/onboarding/setup":
        # Writing API keys to disk - restrict to local/private networks unless auth is active.
        # In Docker, requests arrive from the bridge network (172.x.x.x), not 127.0.0.1,
        # even when the user accesses via localhost:8787 on the host.
        # Behind a reverse proxy (nginx/Caddy/Traefik) or SSH tunnel, X-Forwarded-For
        # carries the real origin IP — read it first before falling back to the raw socket addr.
        # HERMES_WEBUI_ONBOARDING_OPEN=1 lets operators on remote servers explicitly bypass
        # the check when they control network access themselves (e.g. firewall + VPN).
        from app.domain.auth import is_auth_enabled
        import os as _os
        if not is_auth_enabled() and not _os.getenv("HERMES_WEBUI_ONBOARDING_OPEN"):
            import ipaddress
            try:
                # Prefer forwarded headers set by reverse proxies
                _xff = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                _xri = handler.headers.get("X-Real-IP", "").strip()
                _raw = handler.client_address[0]
                _ip_str = _xff or _xri or _raw
                addr = ipaddress.ip_address(_ip_str)
                is_local = addr.is_loopback or addr.is_private
            except ValueError:
                is_local = False
            if not is_local:
                return bad(handler, "Onboarding setup is only available from local networks when auth is not enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1.", 403)
        try:
            return j(handler, apply_onboarding_setup(body))
        except ValueError as e:
            return bad(handler, str(e))
        except RuntimeError as e:
            return bad(handler, str(e), 500)

    if parsed.path == "/api/onboarding/complete":
        return j(handler, complete_onboarding())

    if parsed.path == "/api/onboarding/probe":
        # Probe a self-hosted provider endpoint (#1499).  Validates the
        # configured base URL is reachable + parses /models, returns the
        # model catalog so the wizard can populate its dropdown.
        # Read-only: no config.yaml or .env writes happen here.  Same local-
        # network gate as /api/onboarding/setup (also writing-adjacent in
        # spirit because it carries an api_key the user typed).
        from app.domain.auth import is_auth_enabled
        import os as _os
        if not is_auth_enabled() and not _os.getenv("HERMES_WEBUI_ONBOARDING_OPEN"):
            import ipaddress
            try:
                _xff = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                _xri = handler.headers.get("X-Real-IP", "").strip()
                _raw = handler.client_address[0]
                _ip_str = _xff or _xri or _raw
                addr = ipaddress.ip_address(_ip_str)
                is_local = addr.is_loopback or addr.is_private
            except ValueError:
                is_local = False
            if not is_local:
                return bad(handler, "Onboarding probe is only available from local networks when auth is not enabled. To bypass this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1.", 403)
        provider = str((body or {}).get("provider") or "").strip().lower()
        base_url = str((body or {}).get("base_url") or "")
        api_key = str((body or {}).get("api_key") or "").strip() or None
        try:
            return j(handler, probe_provider_endpoint(provider, base_url, api_key))
        except Exception as e:
            return bad(handler, f"probe failed: {e}", 500)

    # ── Session pin (POST) ──
    if parsed.path == "/api/session/pin":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            s = get_session(body["session_id"])
            s = _ensure_full_session_before_mutation(body["session_id"], s)
        except KeyError:
            return bad(handler, "Session not found", 404)
        pin_requested = bool(body.get("pinned", True))
        # TOCTOU guard (Opus stage-389): the count check and the pin write
        # must happen under the same lock, otherwise two parallel pin
        # requests can both pass `len(pinned_ids) >= 3` against the same
        # snapshot and both succeed, leaving the user with 4 pins. The check
        # must be careful not to nest `all_sessions()` (which acquires LOCK
        # internally) inside a `with LOCK:` block — that's a deadlock since
        # LOCK is a non-reentrant `threading.Lock`. We snapshot the
        # persisted index outside the lock, then re-check the in-memory
        # mutation set inside the lock and commit the pin atomically.
        if pin_requested and not getattr(s, "pinned", False):
            # Pre-snapshot from persisted index (acquires LOCK internally,
            # so must run outside our own LOCK acquire below).
            persisted_pinned_ids = {
                _session_field(existing, "session_id", None) for existing in all_sessions()
                if _session_field(existing, "pinned", False) and not _session_field(existing, "archived", False)
            }
            with LOCK:
                # Final authoritative count: merge persisted-pinned with the
                # in-memory SESSIONS snapshot. SESSIONS may have pin mutations
                # that haven't yet flushed to the index, so the in-memory side
                # is the truth for in-flight contention.
                pinned_ids = set(persisted_pinned_ids)
                pinned_ids.update(
                    sid for sid, existing in SESSIONS.items()
                    if getattr(existing, "pinned", False) and not getattr(existing, "archived", False)
                )
                pinned_ids.discard(body["session_id"])
                pinned_sessions_limit = int(load_settings().get("pinned_sessions_limit", 3) or 3)
                if len(pinned_ids) >= pinned_sessions_limit:
                    return bad(handler, f"Up to {pinned_sessions_limit} sessions can be pinned. Unpin one before pinning another.", 400)
                # Mark in-memory pin state under LOCK so concurrent pin
                # requests see the increment immediately, even before
                # save() finishes flushing to disk.
                s.pinned = True
            with _get_session_agent_lock(body["session_id"]):
                s.save()
        else:
            with _get_session_agent_lock(body["session_id"]):
                s.pinned = pin_requested
                s.save()
        publish_session_list_changed("session_pin")
        return j(handler, {"ok": True, "session": s.compact()})

    # ── Session archive (POST) ──
    if parsed.path == "/api/session/archive":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        sid = body["session_id"]
        try:
            s = get_session(sid)
            # #1558: save() refuses metadata-only session stubs because their
            # messages list is intentionally empty. If a sidebar/status preload
            # left one in the LRU cache, upgrade to a full disk load before
            # mutating archived state so the guard stays intact.
            if getattr(s, "_loaded_metadata_only", False):
                s = Session.load(sid)
                if s is None:
                    raise KeyError(sid)
                with LOCK:
                    SESSIONS[sid] = s
        except KeyError:
            cli_meta = _lookup_cli_session_metadata(sid)
            if not cli_meta:
                return bad(handler, "Session not found", 404)
            if cli_meta.get("read_only"):
                return bad(handler, "Read-only imported sessions cannot be archived from WebUI", 400)
            if _is_messaging_session_record(cli_meta):
                s = Session(
                    session_id=sid,
                    title=cli_meta.get("title") or title_from(get_cli_session_messages(sid), "CLI Session"),
                    workspace=get_last_workspace(),
                    messages=[],
                    model=cli_meta.get("model") or "unknown",
                    created_at=cli_meta.get("created_at"),
                    updated_at=cli_meta.get("updated_at"),
                )
                s.is_cli_session = True
                s.source_tag = cli_meta.get("source_tag")
                s.raw_source = cli_meta.get("raw_source") or cli_meta.get("source_tag")
                s.session_source = cli_meta.get("session_source")
                s.source_label = cli_meta.get("source_label")
                s.user_id = cli_meta.get("user_id")
                s.chat_id = cli_meta.get("chat_id")
                s.chat_type = cli_meta.get("chat_type")
                s.thread_id = cli_meta.get("thread_id")
                s.session_key = cli_meta.get("session_key")
                s.platform = cli_meta.get("platform")
                s.save(touch_updated_at=False)
            else:
                msgs = get_cli_session_messages(sid)
                if not msgs:
                    return bad(handler, "Session not found", 404)
                s = import_cli_session(
                    sid,
                    cli_meta.get("title") or title_from(msgs, "CLI Session"),
                    msgs,
                    cli_meta.get("model") or "unknown",
                    profile=cli_meta.get("profile"),
                    created_at=cli_meta.get("created_at"),
                    updated_at=cli_meta.get("updated_at"),
                )
                s.is_cli_session = True
                s.source_tag = cli_meta.get("source_tag")
                s.raw_source = cli_meta.get("raw_source") or cli_meta.get("source_tag")
                s.session_source = cli_meta.get("session_source")
                s.source_label = cli_meta.get("source_label")
                s.user_id = cli_meta.get("user_id")
                s.chat_id = cli_meta.get("chat_id")
                s.chat_type = cli_meta.get("chat_type")
                s.thread_id = cli_meta.get("thread_id")
                s.session_key = cli_meta.get("session_key")
                s.platform = cli_meta.get("platform")
        with _get_session_agent_lock(sid):
            s.archived = bool(body.get("archived", True))
            s.save(touch_updated_at=False)
        publish_session_list_changed("session_archive")
        return j(handler, {"ok": True, "session": s.compact(), **_worktree_retained_payload(s)})

    # ── Session move to project (POST) ──
    if parsed.path == "/api/session/move":
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        try:
            s = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)
        # #1614: refuse moves into a project owned by another profile.
        target_pid = body.get("project_id") or None
        if target_pid:
            from app.domain.profiles import get_active_profile_name
            active_profile = get_active_profile_name()
            target = next(
                (p for p in load_projects() if p["project_id"] == target_pid),
                None,
            )
            if not target:
                return bad(handler, "Project not found", 404)
            if not _profiles_match(target.get("profile"), active_profile):
                return bad(handler, "Project not found", 404)
        with _get_session_agent_lock(body["session_id"]):
            s.project_id = target_pid
            s.save()
        publish_session_list_changed("session_move")
        return j(handler, {"ok": True, "session": s.compact()})

    # ── Project CRUD (POST) ──
    if parsed.path == "/api/projects/create":
        try:
            require(body, "name")
        except ValueError as e:
            return bad(handler, str(e))
        import re as _re
        from app.domain.profiles import get_active_profile_name

        name = body["name"].strip()[:128]
        if not name:
            return bad(handler, "name required")
        color = body.get("color")
        if color and not _re.match(r"^#[0-9a-fA-F]{3,8}$", color):
            return bad(handler, "Invalid color format")
        projects = load_projects()
        proj = {
            "project_id": uuid.uuid4().hex[:12],
            "name": name,
            "color": color,
            "profile": get_active_profile_name() or 'default',
            "created_at": time.time(),
        }
        projects.append(proj)
        save_projects(projects)
        return j(handler, {"ok": True, "project": proj})

    if parsed.path == "/api/projects/rename":
        try:
            require(body, "project_id", "name")
        except ValueError as e:
            return bad(handler, str(e))
        import re as _re
        from app.domain.profiles import get_active_profile_name

        projects = load_projects()
        proj = next(
            (p for p in projects if p["project_id"] == body["project_id"]), None
        )
        if not proj:
            return bad(handler, "Project not found", 404)
        # #1614: a project can only be renamed by the profile that owns it.
        active_profile = get_active_profile_name()
        if not _profiles_match(proj.get("profile"), active_profile):
            return bad(handler, "Project not found", 404)
        proj["name"] = body["name"].strip()[:128]
        if "color" in body:
            color = body["color"]
            if color and not _re.match(r"^#[0-9a-fA-F]{3,8}$", color):
                return bad(handler, "Invalid color format")
            proj["color"] = color
        save_projects(projects)
        return j(handler, {"ok": True, "project": proj})

    if parsed.path == "/api/projects/delete":
        try:
            require(body, "project_id")
        except ValueError as e:
            return bad(handler, str(e))
        from app.domain.profiles import get_active_profile_name
        projects = load_projects()
        proj = next(
            (p for p in projects if p["project_id"] == body["project_id"]), None
        )
        if not proj:
            return bad(handler, "Project not found", 404)
        # #1614: a project can only be deleted by the profile that owns it.
        active_profile = get_active_profile_name()
        if not _profiles_match(proj.get("profile"), active_profile):
            return bad(handler, "Project not found", 404)
        projects = [p for p in projects if p["project_id"] != body["project_id"]]
        save_projects(projects)
        # Unassign all sessions that belonged to this project
        if SESSION_INDEX_FILE.exists():
            try:
                index = json.loads(SESSION_INDEX_FILE.read_text(encoding="utf-8"))
                for entry in index:
                    if entry.get("project_id") == body["project_id"]:
                        try:
                            s = get_session(entry["session_id"])
                            s.project_id = None
                            s.save()
                        except Exception:
                            logger.debug("Failed to update session %s", entry.get("session_id"))
            except Exception:
                logger.debug("Failed to load session index for project unlink")
        return j(handler, {"ok": True})

    # ── Session import from JSON (POST) ──
    if parsed.path == "/api/session/import":
        return _handle_session_import(handler, body)

    # ── Self-update (POST) ──
    if parsed.path == "/api/updates/apply":
        target = body.get("target", "")
        if target not in ("webui", "agent"):
            return bad(handler, 'target must be "webui" or "agent"')
        from app.domain.updates import apply_update

        return j(handler, apply_update(target))

    if parsed.path == "/api/updates/force":
        target = body.get("target", "")
        if target not in ("webui", "agent"):
            return bad(handler, 'target must be "webui" or "agent"')
        from app.domain.updates import apply_force_update

        return j(handler, apply_force_update(target))

    if parsed.path == "/api/updates/summary":
        from app.domain.updates import summarize_update_payload

        updates = body.get("updates") if isinstance(body, dict) else {}
        target = body.get("target") if isinstance(body, dict) else None

        def _llm_update_summary(system_prompt: str, user_prompt: str) -> str:
            from app.domain import profiles as profiles_api

            active_profile = profiles_api.get_active_profile_name() or "default"

            with profiles_api.profile_env_for_background_worker(
                active_profile,
                "update summary",
                logger_override=logger,
            ):
                from app.domain.config import (
                    get_effective_default_model,
                    resolve_model_provider,
                    resolve_custom_provider_connection,
                )

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

                _main_model, _main_provider, _main_base_url = resolve_model_provider(get_effective_default_model())
                _main_api_key = None
                try:
                    from app.domain.oauth import resolve_runtime_provider_with_anthropic_env_lock
                    from hermes_cli.runtime_provider import resolve_runtime_provider

                    _rt = resolve_runtime_provider_with_anthropic_env_lock(
                        resolve_runtime_provider,
                        requested=_main_provider,
                    )
                    _main_api_key = _rt.get("api_key")
                    if not _main_provider:
                        _main_provider = _rt.get("provider")
                    if not _main_base_url:
                        _main_base_url = _rt.get("base_url")
                except Exception as _e:
                    logger.debug("update summary runtime provider resolution failed: %s", _e)
                if isinstance(_main_provider, str) and _main_provider.startswith("custom:"):
                    _cp_key, _cp_base = resolve_custom_provider_connection(_main_provider)
                    if not _main_api_key and _cp_key:
                        _main_api_key = _cp_key
                    if not _main_base_url and _cp_base:
                        _main_base_url = _cp_base

                main_runtime = {
                    "provider": _main_provider,
                    "model": _main_model,
                    "base_url": _main_base_url,
                    "api_key": _main_api_key,
                }

                try:
                    from agent.auxiliary_client import get_text_auxiliary_client

                    # Update summaries are a short text-compression/summarization task.
                    # Reuse the documented auxiliary.compression slot instead of
                    # inventing a WebUI-only auxiliary task name that users cannot
                    # discover in the Hermes Agent setup/config UI.
                    aux_client, aux_model = get_text_auxiliary_client(
                        "compression",
                        main_runtime=main_runtime,
                    )
                    if aux_client is not None and aux_model:
                        response = aux_client.chat.completions.create(
                            model=aux_model,
                            messages=messages,
                        )
                        return str(response.choices[0].message.content or "").strip()
                except Exception as _e:
                    logger.debug("update summary auxiliary model failed; falling back to main model: %s", _e)

                from run_agent import AIAgent

                agent = AIAgent(
                    model=_main_model,
                    provider=_main_provider,
                    base_url=_main_base_url,
                    api_key=_main_api_key,
                    platform="webui",
                    quiet_mode=True,
                    enabled_toolsets=[],
                    session_id=f"updates-summary-{uuid.uuid4().hex[:8]}",
                )
                result = agent.run_conversation(
                    user_message=user_prompt,
                    system_message=system_prompt,
                    conversation_history=[],
                    task_id=f"updates-summary-{uuid.uuid4().hex[:8]}",
                )
                return str(result.get("final_response") or "").strip()

        return j(handler, summarize_update_payload(updates, llm_callback=_llm_update_summary, target=target))

    # ── CLI session import (POST) ──
    if parsed.path == "/api/session/import_cli":
        return _handle_session_import_cli(handler, body)

    # ── Auth endpoints (POST) ──
    if parsed.path == "/api/auth/login":
        from app.domain.auth import set_auth_cookie
        from app.services.auth import AuthService

        client_ip = handler.client_address[0]
        username = (body.get("username") or "").strip() or None
        password = body.get("password", "")
        payload, status_code, cookie_val = AuthService().login(
            password,
            client_ip=client_ip,
            username=username,
        )
        if status_code != 200:
            err = payload.get("error") or payload.get("message") or "Login failed"
            return bad(handler, err, status_code)
        resp_body = json.dumps(payload).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(resp_body)))
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        if cookie_val:
            set_auth_cookie(handler, cookie_val)
        handler.end_headers()
        handler.wfile.write(resp_body)
        return True

    if parsed.path == "/api/auth/passkey/options":
        from app.domain.auth import _passkey_feature_flag_enabled, is_auth_enabled
        from app.domain.passkeys import PasskeyError, authentication_options

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled. Set HERMES_WEBUI_PASSKEY=1 or webui_passkey_enabled: true to enable."}, status=404)
        if not is_auth_enabled():
            return j(handler, {"error": "Auth not enabled"}, status=400)
        try:
            return j(handler, {"ok": True, "publicKey": authentication_options(handler)})
        except PasskeyError as e:
            return bad(handler, str(e), status=400)

    if parsed.path == "/api/auth/passkey/login":
        from app.domain.auth import _passkey_feature_flag_enabled, create_session, is_auth_enabled, set_auth_cookie
        from app.domain.auth import _check_login_rate, _record_login_attempt
        from app.domain.passkeys import PasskeyError, finish_login

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        if not is_auth_enabled():
            return j(handler, {"error": "Auth not enabled"}, status=400)
        client_ip = handler.client_address[0]
        if not _check_login_rate(client_ip):
            return j(handler, {"error": "Too many attempts. Try again in a minute."}, status=429)
        try:
            finish_login(body, handler)
        except PasskeyError as e:
            _record_login_attempt(client_ip)
            return bad(handler, str(e), status=401)
        cookie_val = create_session()
        from app.domain.auth import csrf_token_response_field

        login_payload = {"ok": True, **csrf_token_response_field(cookie_val)}
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        set_auth_cookie(handler, cookie_val)
        handler.end_headers()
        handler.wfile.write(json.dumps(login_payload).encode())
        return True

    if parsed.path == "/api/auth/passkey/register/options":
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import registration_options

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        return j(handler, {"ok": True, "publicKey": registration_options(handler)})

    if parsed.path == "/api/auth/passkey/register":
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import PasskeyError, finish_registration, registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        try:
            result = finish_registration(body, handler)
            result["credentials"] = registered_credentials()
            return j(handler, result)
        except PasskeyError as e:
            return bad(handler, str(e), status=400)

    if parsed.path == "/api/auth/passkey/delete":
        from app.domain.auth import _passkey_feature_flag_enabled, get_password_hash
        from app.domain.passkeys import PasskeyError, delete_credential, registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        try:
            credential_id = str(body.get("id") or "")
            creds = registered_credentials()
            if get_password_hash() is None and len(creds) <= 1 and any(c.get("id") == credential_id for c in creds):
                return bad(handler, "Set a password or disable auth before removing the last passkey.", 409)
            return j(handler, delete_credential(credential_id))
        except PasskeyError as e:
            return bad(handler, str(e), status=404)

    if parsed.path == "/api/auth/passkeys":
        from app.domain.auth import _passkey_feature_flag_enabled
        from app.domain.passkeys import registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"credentials": [], "disabled": True})
        return j(handler, {"credentials": registered_credentials()})

    if parsed.path == "/api/auth/logout":
        from app.domain.auth import clear_auth_cookie, invalidate_session, parse_cookie

        cookie_val = parse_cookie(handler)
        if cookie_val:
            invalidate_session(cookie_val)
        body = json.dumps({"ok": True}).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        clear_auth_cookie(handler)
        handler.end_headers()
        handler.wfile.write(body)
        return True

    # ── Checkpoints / Rollback (POST) ──
    if parsed.path == "/api/rollback/restore":
        if not body:
            return bad(handler, "request body is required")
        workspace = body.get("workspace", "")
        checkpoint = body.get("checkpoint", "")
        if not workspace or not checkpoint:
            return bad(handler, "workspace and checkpoint are required")
        try:
            from app.domain.rollback import restore_checkpoint
            return j(handler, restore_checkpoint(workspace, checkpoint))
        except ValueError as e:
            return bad(handler, str(e))
        except Exception as e:
            logger.exception("rollback/restore failed")
            return bad(handler, str(e), status=500)

    return False  # 404


def handle_patch(handler, parsed) -> bool:
    """Handle all PATCH routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    body = read_body(handler)
    if parsed.path.startswith("/api/mcp/servers/"):
        name = parsed.path[len("/api/mcp/servers/"):]
        return _handle_mcp_server_toggle(handler, name, body, parsed)
    if parsed.path.startswith("/api/kanban/"):
        from app.domain.kanban_bridge import handle_kanban_patch

        result = handle_kanban_patch(handler, parsed, body)
        if result is False:
            return _kanban_unknown_endpoint(handler, parsed, "PATCH")
        return True
    return False


def handle_delete(handler, parsed) -> bool:
    """Handle all DELETE routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    body = read_body(handler)
    if parsed.path.startswith("/api/mcp/servers/"):
        name = parsed.path[len("/api/mcp/servers/"):]
        return _handle_mcp_server_delete(handler, name, parsed, body)
    if parsed.path.startswith("/api/kanban/"):
        from app.domain.kanban_bridge import handle_kanban_delete

        result = handle_kanban_delete(handler, parsed, body)
        if result is False:
            return _kanban_unknown_endpoint(handler, parsed, "DELETE")
        return True
    return False


def handle_put(handler, parsed) -> bool:
    """Handle all PUT routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": "Cross-origin request rejected"}, status=403)
    body = read_body(handler)
    if parsed.path.startswith("/api/mcp/servers/"):
        name = parsed.path[len("/api/mcp/servers/"):]
        return _handle_mcp_server_update(handler, name, body, parsed)
    return False

# ── GET route helpers ─────────────────────────────────────────────────────────

# MIME types for static file serving. Hoisted to module scope to avoid
# rebuilding the dict on every request.
_STATIC_MIME = {
    "css": "text/css",
    "js": "application/javascript",
    "html": "text/html",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "ico": "image/x-icon",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
}
# MIME types that are text-based and should carry charset=utf-8
_TEXT_MIME_TYPES = {"text/css", "application/javascript", "text/html", "image/svg+xml", "text/plain"}

# MIME types worth gzipping. Image and font formats (png/jpg/webp/woff2) are
# already compressed; gzip would only add CPU and a few bytes of framing.
_COMPRESSIBLE_MIME = {
    "text/css", "application/javascript", "text/html", "image/svg+xml",
    "application/json", "text/plain",
}

# In-process cache for raw bytes, compressed bytes, and ETag. The cache is keyed
# by absolute path and invalidated on (size, high-precision mtime) change, so a
# redeploy is picked up without a process restart. Missing/random paths never
# enter the cache; memory cost is bounded by the static/ tree's served files.
_STATIC_CACHE: dict = {}
_STATIC_CACHE_LOCK = threading.Lock()
# Archive-only vanilla assets (tests); never exposed over HTTP.
_STATIC_LEGACY_ROOT = (REPO_ROOT / "static-legacy").resolve()


def _serve_static(handler, parsed):
    static_root = (REPO_ROOT / "static").resolve()
    # Strip the leading '/static/' prefix, then resolve and sandbox
    rel = parsed.path[len("/static/") :]
    static_file = (static_root / rel).resolve()
    try:
        static_file.relative_to(static_root)
    except ValueError:
        return j(handler, {"error": "not found"}, status=404)
    # Block symlink escape into static-legacy/ (archive reference only).
    try:
        static_file.relative_to(_STATIC_LEGACY_ROOT)
        return j(handler, {"error": "not found"}, status=404)
    except ValueError:
        pass
    if not static_file.exists() or not static_file.is_file():
        return j(handler, {"error": "not found"}, status=404)
    ext = static_file.suffix.lower()
    ct = _STATIC_MIME.get(ext.lstrip("."), "text/plain")
    ct_header = f"{ct}; charset=utf-8" if ct in _TEXT_MIME_TYPES else ct

    # Look up or populate the per-file cache (raw, optional gzip, ETag).
    # Keyed by absolute path; invalidated by (size, nanosecond mtime).
    st = static_file.stat()
    sig = (st.st_size, st.st_mtime_ns)
    cache_key = str(static_file)
    raw = gz = etag = None
    with _STATIC_CACHE_LOCK:
        cached = _STATIC_CACHE.get(cache_key)
        if cached and cached[0] == sig:
            _, raw, gz, etag = cached
    if raw is None:
        raw = static_file.read_bytes()
        # Weak ETag: equality semantics, derived from filesystem identity.
        etag = f'W/"{sig[0]:x}-{sig[1]:x}"'
        gz = (gzip.compress(raw, compresslevel=6)
              if ct in _COMPRESSIBLE_MIME and len(raw) > 1024
              else None)
        with _STATIC_CACHE_LOCK:
            _STATIC_CACHE[cache_key] = (sig, raw, gz, etag)

    # The page template substitutes __WEBUI_VERSION__ at request time (see the
    # `/`/`/index.html`/`/session/` branch above), and static/sw.js's
    # SHELL_ASSETS list relies on the same convention. So a fingerprinted URL
    # is safe to cache aggressively: any redeploy changes the URL.
    version_values = parse_qs(parsed.query, keep_blank_values=True).get("v", [""])
    has_fingerprint = bool(version_values[0])
    cache_control = (
        "public, max-age=31536000, immutable" if has_fingerprint
        else "public, max-age=300"
    )

    # 304 short-circuit on conditional GET.
    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", cache_control)
        if gz is not None:
            handler.send_header("Vary", "Accept-Encoding")
        handler.end_headers()
        return True

    accept_enc = (handler.headers.get("Accept-Encoding") or "").lower()
    use_gzip = gz is not None and "gzip" in accept_enc
    body = gz if use_gzip else raw

    handler.send_response(200)
    handler.send_header("Content-Type", ct_header)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", cache_control)
    if gz is not None:
        handler.send_header("Vary", "Accept-Encoding")
    if use_gzip:
        handler.send_header("Content-Encoding", "gzip")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _serve_react_assets(handler, parsed) -> bool:
    """Serve fingerprinted files from the active Vite dist/assets directory."""
    dist_root = _spa_dist_root()
    if dist_root is None:
        return j(handler, {"error": "not found"}, status=404)
    if not parsed.path.startswith("/assets/"):
        return j(handler, {"error": "not found"}, status=404)
    rel = parsed.path[len("/assets/") :]
    static_file = (dist_root / "assets" / rel).resolve()
    assets_root = (dist_root / "assets").resolve()
    try:
        static_file.relative_to(assets_root)
    except ValueError:
        return j(handler, {"error": "not found"}, status=404)
    if not static_file.exists() or not static_file.is_file():
        return j(handler, {"error": "not found"}, status=404)
    ext = static_file.suffix.lower()
    ct = _STATIC_MIME.get(ext.lstrip("."), "application/octet-stream")
    ct_header = f"{ct}; charset=utf-8" if ct in _TEXT_MIME_TYPES else ct

    st = static_file.stat()
    sig = (st.st_size, st.st_mtime_ns)
    cache_key = str(static_file)
    raw = gz = etag = None
    with _STATIC_CACHE_LOCK:
        cached = _STATIC_CACHE.get(cache_key)
        if cached and cached[0] == sig:
            _, raw, gz, etag = cached
    if raw is None:
        raw = static_file.read_bytes()
        etag = f'W/"{sig[0]:x}-{sig[1]:x}"'
        gz = (
            gzip.compress(raw, compresslevel=6)
            if ct in _COMPRESSIBLE_MIME and len(raw) > 1024
            else None
        )
        with _STATIC_CACHE_LOCK:
            _STATIC_CACHE[cache_key] = (sig, raw, gz, etag)

    cache_control = "public, max-age=31536000, immutable"
    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", cache_control)
        if gz is not None:
            handler.send_header("Vary", "Accept-Encoding")
        handler.end_headers()
        return True

    accept_enc = (handler.headers.get("Accept-Encoding") or "").lower()
    use_gzip = gz is not None and "gzip" in accept_enc
    body = gz if use_gzip else raw

    handler.send_response(200)
    handler.send_header("Content-Type", ct_header)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", cache_control)
    if gz is not None:
        handler.send_header("Vary", "Accept-Encoding")
    if use_gzip:
        handler.send_header("Content-Encoding", "gzip")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _handle_session_export(handler, parsed):
    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    try:
        s = get_session(sid)
    except KeyError:
        return bad(handler, "Session not found", 404)
    safe = redact_session_data(s.__dict__)
    payload = json.dumps(safe, ensure_ascii=False, indent=2)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header(
        "Content-Disposition", f'attachment; filename="hermes-{sid}.json"'
    )
    handler.send_header("Content-Length", str(len(payload.encode("utf-8"))))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload.encode("utf-8"))
    return True


def _session_search_message_text(message):
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


def _session_search_preview(text, query, max_len=124):
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    q = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized or not q:
        return ""
    idx = normalized.lower().find(q.lower())
    if idx < 0:
        return ""

    max_len = max(32, int(max_len or 124))
    if len(normalized) <= max_len:
        return normalized

    context = max(12, (max_len - len(q)) // 2)
    start = max(0, idx - context)
    end = min(len(normalized), idx + len(q) + context)
    if start > 0:
        while start < idx and normalized[start] != " ":
            start += 1
        if start >= idx:
            start = max(0, idx - context)
    if end < len(normalized):
        while end > idx + len(q) and normalized[end - 1] != " ":
            end -= 1
        if end <= idx + len(q):
            end = min(len(normalized), idx + len(q) + context)
    excerpt = normalized[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(normalized):
        excerpt = excerpt + "..."
    return excerpt


def _handle_sessions_search(handler, parsed):
    qs = parse_qs(parsed.query)
    q = qs.get("q", [""])[0].lower().strip()
    content_search = qs.get("content", ["1"])[0] == "1"
    depth = int(qs.get("depth", ["5"])[0])
    if not q:
        safe_sessions = []
        for s in all_sessions():
            item = dict(s)
            if isinstance(item.get("title"), str):
                item["title"] = _redact_text(item["title"])
            safe_sessions.append(item)
        return j(handler, {"sessions": safe_sessions})
    results = []
    for s in all_sessions():
        title_match = q in (s.get("title") or "").lower()
        if title_match:
            item = dict(s, match_type="title")
            if isinstance(item.get("title"), str):
                item["title"] = _redact_text(item["title"])
            results.append(item)
            continue
        if content_search:
            try:
                sess = get_session(s["session_id"])
                msgs = sess.messages[:depth] if depth else sess.messages
                for m in msgs:
                    c = _session_search_message_text(m)
                    if q in str(c).lower():
                        item = dict(s, match_type="content")
                        preview = _session_search_preview(c, q)
                        if preview:
                            item["match_preview"] = _redact_text(preview)
                        if isinstance(item.get("title"), str):
                            item["title"] = _redact_text(item["title"])
                        results.append(item)
                        break
            except (KeyError, Exception):
                pass
    return j(handler, {"sessions": results, "query": q, "count": len(results)})


def _handle_list_dir(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0].strip()
    ws_param = qs.get("workspace", [""])[0].strip()
    if not sid and not ws_param:
        return bad(handler, "session_id or workspace is required")
    if ws_param:
        from app.domain.workspace import (
            ensure_profile_workspace_exists,
            resolve_trusted_workspace,
        )

        try:
            ws_root = resolve_trusted_workspace(ws_param)
        except ValueError as exc:
            return bad(handler, str(exc), 400)
        ensure_profile_workspace_exists(ws_root)
        workspace = str(ws_root)
    else:
        try:
            s = get_session(sid)
            workspace = s.workspace
        except KeyError:
            # Fallback for CLI sessions not loaded in WebUI memory
            try:
                cli_meta = None
                for cs in get_cli_sessions():
                    if cs["session_id"] == sid:
                        cli_meta = cs
                        break
                if not cli_meta:
                    return bad(handler, "Session not found", 404)
                workspace = cli_meta.get("workspace", "")
            except Exception:
                return bad(handler, "Session not found", 404)
    try:
        rel_path = qs.get("path", ["."])[0]
        entries = list_dir(Path(workspace), rel_path)
        return j(
            handler,
            {
                "entries": entries,
                "signature": dir_signature(Path(workspace), rel_path, entries),
                "path": rel_path,
            },
        )
    except (FileNotFoundError, ValueError) as e:
        return bad(handler, _sanitize_error(e), 404)


def _sse_with_id(handler, event, data, event_id=None):
    if event_id:
        handler.wfile.write(f"id: {event_id}\n".encode("utf-8"))
    _sse(handler, event, data)


def _parse_run_journal_after_seq(qs: dict) -> int | None:
    raw = qs.get("after_seq", [None])[0]
    if raw in (None, ""):
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _replay_run_journal(handler, stream_id: str, after_seq: int | None) -> bool:
    from app.domain.chat_streaming import replay_run_journal_to_handler

    return replay_run_journal_to_handler(handler, stream_id, after_seq)


def _handle_sse_stream(handler, parsed):
    from app.domain.chat_streaming import write_legacy_chat_sse_stream

    return write_legacy_chat_sse_stream(
        handler,
        parsed,
        disconnect_errors=_CLIENT_DISCONNECT_ERRORS,
    )


def _terminal_session_and_workspace(body_or_query):
    sid = str(body_or_query.get("session_id", "")).strip()
    if not sid:
        raise ValueError("session_id required")
    try:
        s = get_session(sid)
    except KeyError:
        raise KeyError("Session not found")
    workspace = resolve_trusted_workspace(getattr(s, "workspace", "") or "")
    return sid, workspace


def _handle_terminal_start(handler, body):
    try:
        sid, workspace = _terminal_session_and_workspace(body)
        from app.domain.terminal import start_terminal
        term = start_terminal(
            sid,
            workspace,
            rows=int(body.get("rows") or 24),
            cols=int(body.get("cols") or 80),
            restart=bool(body.get("restart")),
        )
        return j(
            handler,
            {
                "ok": True,
                "session_id": sid,
                "workspace": term.workspace,
                "running": term.is_alive(),
            },
        )
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def _handle_terminal_input(handler, body):
    try:
        require(body, "session_id")
        data = str(body.get("data", ""))
        if len(data) > 8192:
            return bad(handler, "input too large", 413)
        from app.domain.terminal import write_terminal
        write_terminal(body["session_id"], data)
        return j(handler, {"ok": True})
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def _handle_terminal_resize(handler, body):
    try:
        require(body, "session_id")
        from app.domain.terminal import resize_terminal
        resize_terminal(
            body["session_id"],
            rows=int(body.get("rows") or 24),
            cols=int(body.get("cols") or 80),
        )
        return j(handler, {"ok": True})
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def _handle_terminal_close(handler, body):
    try:
        require(body, "session_id")
        from app.domain.terminal import close_terminal
        closed = close_terminal(body["session_id"])
        return j(handler, {"ok": True, "closed": closed})
    except ValueError as e:
        return bad(handler, str(e), 400)


def _handle_terminal_output(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id required")
    from app.domain.terminal import get_terminal
    term = get_terminal(sid)
    if term is None:
        return j(handler, {"error": "terminal not running"}, status=404)

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "close")
    handler.end_headers()
    try:
        while True:
            try:
                event, data = term.output.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b": terminal heartbeat\n\n")
                handler.wfile.flush()
                if term.closed.is_set() and term.output.empty():
                    _sse(handler, "terminal_closed", {"exit_code": term.proc.poll()})
                    break
                continue
            _sse(handler, event, data)
            if event in ("terminal_closed", "terminal_error"):
                break
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    return True


def _gateway_sse_probe_payload(settings, watcher):
    enabled = bool(settings.get('show_cli_sessions'))
    # Use the public is_alive() accessor where available (current GatewayWatcher);
    # fall back to the private _thread check for any older in-memory instance
    # that might still be hanging around mid-upgrade, and for test doubles that
    # don't implement the full public API.
    if watcher is None:
        watcher_alive = False
    elif hasattr(watcher, 'is_alive') and callable(getattr(watcher, 'is_alive')):
        watcher_alive = bool(watcher.is_alive())
    else:
        _t = getattr(watcher, '_thread', None)
        watcher_alive = _t is not None and _t.is_alive()
    payload = {
        'enabled': enabled,
        'fallback_poll_ms': 30000,
        'ok': enabled and watcher_alive,
        'watcher_running': watcher_alive,
    }
    if not enabled:
        payload['error'] = 'agent sessions not enabled'
        return payload, 404
    if not watcher_alive:
        payload['error'] = 'watcher not started'
        return payload, 503
    return payload, 200


def _handle_gateway_sse_stream(handler, parsed):
    """SSE endpoint for real-time gateway session updates.
    Streams change events from the gateway watcher background thread.
    Only active when show_cli_sessions (show_agent_sessions) setting is enabled.
    """
    settings = load_settings()

    from app.domain.gateway_watcher import get_watcher
    watcher = get_watcher()

    probe = parse_qs(parsed.query).get('probe', [''])[0].lower() in {'1', 'true', 'yes'}
    if probe:
        payload, status = _gateway_sse_probe_payload(settings, watcher)
        return j(handler, payload, status=status)

    # Check if the feature is enabled
    if not settings.get('show_cli_sessions'):
        return j(handler, {'error': 'agent sessions not enabled'}, status=404)

    # Same watcher_alive semantics as the probe path — centralised via
    # the helper so both branches stay in sync.
    _probe_body, _probe_status = _gateway_sse_probe_payload(settings, watcher)
    if not _probe_body['watcher_running']:
        return j(handler, {'error': 'watcher not started'}, status=503)

    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Connection', 'close')
    handler.end_headers()

    q = watcher.subscribe()
    try:
        # Send initial snapshot immediately
        from app.domain.models import get_cli_sessions
        initial = get_cli_sessions()
        _sse(handler, 'sessions_changed', {'sessions': initial})

        while True:
            try:
                event_data = q.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
                continue
            if event_data is None:
                break  # watcher is stopping
            _sse(handler, event_data.get('type', 'sessions_changed'), event_data)
    except _CLIENT_DISCONNECT_ERRORS:
        pass
    finally:
        watcher.unsubscribe(q)
    return True


def _handle_session_events_stream(handler):
    """SSE endpoint for lightweight session-list invalidation events."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Connection', 'close')
    handler.end_headers()

    q = subscribe_session_events()
    try:
        while True:
            try:
                event_data = q.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
                continue
            _sse(handler, event_data.get('type', 'sessions_changed'), event_data)
    except _CLIENT_DISCONNECT_ERRORS:
        pass
    finally:
        unsubscribe_session_events(q)
    return True


def _content_disposition_value(disposition: str, filename: str) -> str:
    """Build a latin-1-safe Content-Disposition value with RFC 5987 filename*."""
    import urllib.parse as _up

    safe_name = Path(filename).name.replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
        for ch in safe_name
    ).strip(" .")
    if not ascii_fallback:
        suffix = Path(safe_name).suffix
        ascii_suffix = "".join(
            ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
            for ch in suffix
        )
        ascii_fallback = f"download{ascii_suffix}" if ascii_suffix else "download"
    quoted_name = _up.quote(safe_name, safe="")
    return (
        f'{disposition}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quoted_name}"
    )


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single HTTP bytes range into inclusive start/end offsets."""
    if not range_header or not range_header.startswith("bytes=") or file_size < 1:
        return None
    spec = range_header.split("=", 1)[1].strip()
    if "," in spec or "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            # suffix range: bytes=-500
            suffix_len = int(end_s)
            if suffix_len <= 0:
                return None
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
            if start < 0:
                return None
            end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return None
        return start, end
    except ValueError:
        return None


def _serve_file_bytes(handler, target: Path, mime: str, disposition: str, cache_control: str, *, csp: str | None = None, inline_filename: bool = True):
    """Serve a file with correct MIME/disposition and optional byte-range support."""
    try:
        file_size = target.stat().st_size
    except PermissionError:
        return bad(handler, "Permission denied", 403)
    except Exception:
        return bad(handler, "Could not stat file", 500)

    byte_range = _parse_range_header(handler.headers.get("Range", ""), file_size)
    if handler.headers.get("Range") and byte_range is None:
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{file_size}")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Length", "0")
        _security_headers(handler)
        handler.end_headers()
        return True

    start, end = byte_range if byte_range else (0, max(0, file_size - 1))
    content_length = end - start + 1 if file_size else 0
    handler.send_response(206 if byte_range else 200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(content_length))
    handler.send_header("Accept-Ranges", "bytes")
    if byte_range:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
    handler.send_header("Cache-Control", cache_control)
    cd_header = (
        "inline"
        if disposition == "inline" and not inline_filename
        else _content_disposition_value(disposition, target.name)
    )
    handler.send_header("Content-Disposition", cd_header)
    if csp:
        # Sandboxed inline HTML must remain frameable for workspace previews;
        # X-Frame-Options: DENY would block the iframe before CSP sandbox applies.
        handler.send_header("Content-Security-Policy", csp)
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "same-origin")
        handler.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)",
        )
    else:
        _security_headers(handler)
    handler.end_headers()

    if content_length:
        try:
            with target.open("rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)
        except PermissionError:
            return True
    return True


def _html_preview_with_blank_base(
    raw: bytes,
    *,
    workspace_virtual: str | None = None,
    workspace_disk_root: Path | None = None,
    html_disk_path: Path | None = None,
) -> bytes:
    from app.domain.workspace import inject_workspace_html_preview_enhancements

    return inject_workspace_html_preview_enhancements(
        raw,
        workspace_virtual=workspace_virtual,
        workspace_disk_root=workspace_disk_root,
        html_disk_path=html_disk_path,
    )


def _workspace_virtual_for_file_handler(ws_param: str, session=None) -> str | None:
    from app.domain.workspace import agent_facing_workspace_path, nested_workspaces_enabled

    if not nested_workspaces_enabled():
        return None
    if ws_param:
        return agent_facing_workspace_path(ws_param)
    if session is not None:
        return agent_facing_workspace_path(getattr(session, "workspace", ""))
    return None


def _workspace_disk_root_for_file_handler(ws_param: str, session=None) -> Path | None:
    if ws_param:
        return _resolve_trusted_workspace_root(ws_param)
    if session is not None:
        try:
            return Path(session.workspace).resolve()
        except OSError:
            return Path(session.workspace)
    return None


def _serve_inline_html_preview(
    handler,
    target: Path,
    cache_control: str,
    *,
    csp: str,
    plain_inline_disposition: bool = False,
    workspace_virtual: str | None = None,
    workspace_disk_root: Path | None = None,
):
    """Serve sandboxed workspace HTML preview with links targeting a new tab."""
    try:
        body = _html_preview_with_blank_base(
            target.read_bytes(),
            workspace_virtual=workspace_virtual,
            workspace_disk_root=workspace_disk_root,
            html_disk_path=target,
        )
    except PermissionError:
        return bad(handler, "Permission denied", 403)
    except Exception:
        return bad(handler, "Could not read file", 500)

    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Accept-Ranges", "none")
    handler.send_header("Cache-Control", cache_control)
    if plain_inline_disposition:
        handler.send_header("Content-Disposition", "inline")
    else:
        handler.send_header("Content-Disposition", _content_disposition_value("inline", target.name))
    handler.send_header("Content-Security-Policy", csp)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "same-origin")
    handler.send_header(
        "Permissions-Policy",
        "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)",
    )
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _handle_media(handler, parsed):
    """Serve a local file by absolute path for inline display in the chat.

    Security:
    - Path must resolve to an allowed root (hermes home, /tmp, common dirs)
    - Auth-gated when auth is enabled
    - Only image MIME types are served inline; all others force download
    - SVG always served as attachment (XSS risk)
    - No path traversal: resolved path must stay within an allowed root
    - Additional roots can be added via MEDIA_ALLOWED_ROOTS env var
      (os.pathsep-separated list of absolute paths; ":" on POSIX, ";" on Windows)
    """
    import os as _os
    from app.domain.auth import is_auth_enabled, parse_cookie, verify_session
    from app.domain.profiles import get_active_hermes_home
    _HOME = Path(_os.path.expanduser("~"))
    try:
        _HERMES_HOME = get_active_hermes_home().expanduser().resolve()
    except Exception:
        _HERMES_HOME = Path(_os.getenv("HERMES_HOME", str(_HOME / ".hermes"))).expanduser()

    # Auth check
    if is_auth_enabled():
        cv = parse_cookie(handler)
        if not (cv and verify_session(cv)):
            body = b'{"error":"Authentication required"}'
            handler.send_response(401)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return

    qs = parse_qs(parsed.query)
    raw_path = qs.get("path", [""])[0].strip()
    if not raw_path:
        return bad(handler, "path parameter required", 400)

    # Resolve the path and check it is within an allowed root
    try:
        target = Path(raw_path).resolve()
    except Exception:
        return bad(handler, "Invalid path", 400)

    # Allowed roots: hermes home, /tmp, and active workspace.
    # Intentionally NOT the entire home dir — that would expose ~/.ssh,
    # ~/.aws, browser profiles, etc. to any authenticated user.
    allowed_roots = [
        _HERMES_HOME.resolve(),
        Path("/tmp").resolve(),
        (_HOME / ".hermes").resolve(),
    ]
    try:
        from app.domain.config import STATE_DIR
        allowed_roots.append(STATE_DIR.resolve())
    except Exception:
        pass
    try:
        from app.domain.upload import _attachment_root
        allowed_roots.append(_attachment_root())
    except Exception:
        pass
    # Also allow the active workspace directory (where screenshots land)
    try:
        from app.domain.workspace import get_last_workspace
        ws = Path(get_last_workspace()).resolve()
        if ws.is_dir():
            allowed_roots.append(ws)
    except Exception:
        pass

    # Also allow additional roots from MEDIA_ALLOWED_ROOTS env var
    # (os.pathsep-separated list; ":" on POSIX, ";" on Windows).
    extra_roots = _os.environ.get("MEDIA_ALLOWED_ROOTS", "").strip()
    if extra_roots:
        for root in extra_roots.split(_os.pathsep):
            root = root.strip()
            if root:
                try:
                    rp = Path(root).resolve()
                    if rp.is_dir():
                        allowed_roots.append(rp)
                except Exception:
                    pass

    within_allowed = any(
        _os.path.commonpath([str(target), str(root)]) == str(root)
        for root in allowed_roots
        if root.exists()
    )
    if not within_allowed:
        return bad(handler, "Path not in allowed location", 403)

    if not target.exists() or not target.is_file():
        return j(handler, {"error": "not found"}, status=404)

    # Determine MIME type
    ext = target.suffix.lower()
    mime = MIME_MAP.get(ext, "application/octet-stream")

    # Only serve safe media/PDF types inline when explicitly requested. HTML is
    # allowed inline only with a CSP sandbox so "open full page" can work without
    # granting same-origin access to the WebUI. SVG is always a download (XSS risk).
    _INLINE_IMAGE_TYPES = {
        "image/png", "image/jpeg", "image/gif", "image/webp",
        "image/x-icon", "image/bmp",
    }
    _INLINE_PREVIEW_TYPES = _INLINE_IMAGE_TYPES | {
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac",
        "audio/ogg", "audio/opus", "audio/flac",
        "video/mp4", "video/quicktime", "video/webm", "video/ogg",
        "application/pdf",
    }
    _DOWNLOAD_TYPES = {"image/svg+xml"}  # SVG: XSS risk, force download
    inline_preview = qs.get("inline", [""])[0] == "1"
    html_inline_ok = inline_preview and mime == "text/html"
    disposition = "inline" if (
        mime not in _DOWNLOAD_TYPES and (
            mime in _INLINE_IMAGE_TYPES or (inline_preview and mime in _INLINE_PREVIEW_TYPES)
            or html_inline_ok
        )
    ) else "attachment"
    # _serve_file_bytes sends Content-Security-Policy when csp is set.
    csp = "sandbox allow-scripts" if html_inline_ok else None
    return _serve_file_bytes(handler, target, mime, disposition, "private, max-age=3600", csp=csp)


def _file_raw_target(session, sid: str, rel: str) -> Path | None:
    """Resolve /api/file/raw paths from the workspace or this session's uploads."""
    rel = str(rel or '').strip()
    if not rel:
        return None
    try:
        from app.domain.workspace import resolve_session_workspace

        workspace_root = resolve_session_workspace(
            getattr(session, "workspace", None) or ""
        )
    except ValueError:
        try:
            workspace_root = Path(getattr(session, "workspace", "") or "").expanduser().resolve()
        except OSError:
            workspace_root = None

    try:
        from app.domain.upload import resolve_workspace_uploads_relative_path

        uploads_hit = resolve_workspace_uploads_relative_path(
            rel,
            session_workspace=getattr(session, "workspace", None) or "",
            session_id=sid,
        )
        if uploads_hit is not None:
            return uploads_hit
    except Exception:
        pass

    if workspace_root is not None:
        try:
            target = safe_resolve(workspace_root, rel)
        except ValueError:
            target = None
        if target and target.exists() and target.is_file():
            return target

    try:
        from app.domain.upload import (
            WORKSPACE_UPLOADS_SUBDIR,
            _attachment_root,
            _session_attachment_dir,
            iter_session_upload_dirs,
            resolve_upload_basename_in_dir,
            trusted_hermes_file_roots,
        )

        attachment_root = _attachment_root()
        sanitized_sid = re.sub(r'[^\w.\-]', '_', str(sid or 'session'))[:120]

        abs_candidate = Path(rel).expanduser()
        if abs_candidate.is_absolute():
            try:
                resolved = abs_candidate.resolve()
                if resolved.exists() and resolved.is_file():
                    allowed_roots = list(trusted_hermes_file_roots())
                    if workspace_root is not None:
                        allowed_roots.append(workspace_root)
                    for allowed_root in allowed_roots:
                        try:
                            if resolved.is_relative_to(allowed_root):
                                return resolved
                        except ValueError:
                            continue
                    if resolved.is_relative_to(attachment_root):
                        rel_parts = resolved.relative_to(attachment_root).parts
                        if rel_parts and rel_parts[0] == sanitized_sid:
                            return resolved
            except (ValueError, OSError):
                pass

        basename = Path(rel).name
        if basename:
            inbox_hit = resolve_upload_basename_in_dir(_session_attachment_dir(sid), basename)
            if inbox_hit is not None:
                return inbox_hit

            if workspace_root is not None:
                try:
                    uploads_rel = f"{WORKSPACE_UPLOADS_SUBDIR}/{basename}"
                    uploads_target = safe_resolve(workspace_root, uploads_rel)
                    if uploads_target.exists() and uploads_target.is_file():
                        return uploads_target
                except ValueError:
                    pass

            for uploads_dir in iter_session_upload_dirs(
                getattr(session, "workspace", None) or ""
            ):
                uploads_hit = resolve_upload_basename_in_dir(uploads_dir, basename)
                if uploads_hit is not None:
                    return uploads_hit
    except Exception:
        return None
    return None


def _resolve_trusted_workspace_root(ws_param: str) -> Path | None:
    """Resolve a profile-trusted workspace root from a registry path string."""
    from app.domain.workspace import (
        ensure_profile_workspace_exists,
        resolve_trusted_workspace,
    )

    try:
        ws_root = resolve_trusted_workspace(ws_param)
    except ValueError:
        return None
    ensure_profile_workspace_exists(ws_root)
    return Path(ws_root)


def _workspace_file_target(ws_param: str, rel: str) -> Path | None:
    """Resolve a workspace-relative file path without a chat session."""
    ws_root = _resolve_trusted_workspace_root(ws_param)
    if ws_root is None:
        return None
    rel = str(rel or "").strip()
    if not rel:
        return None
    try:
        from app.domain.upload import resolve_workspace_uploads_relative_path

        uploads_hit = resolve_workspace_uploads_relative_path(
            rel,
            session_workspace=ws_param,
        )
        if uploads_hit is not None:
            return uploads_hit
    except Exception:
        pass
    try:
        target = safe_resolve(ws_root, rel)
    except ValueError:
        return None
    if target and target.exists() and target.is_file():
        return target
    return None


def _resolve_file_mutation_workspace(body: dict) -> tuple[Path | None, str | None, int]:
    """Resolve workspace root for file mutations (delete/rename/etc.)."""
    sid = str(body.get("session_id") or "").strip()
    ws_param = str(body.get("workspace") or "").strip()
    if not sid and not ws_param:
        return None, "session_id or workspace is required", 400
    if ws_param:
        root = _resolve_trusted_workspace_root(ws_param)
        if root is None:
            return None, "invalid workspace", 400
        return root, None, 200
    try:
        s = get_session(sid)
    except KeyError:
        return None, "Session not found", 404
    return Path(s.workspace), None, 200


# ─── /api/folder/download ───────────────────────────────────────────────────
# Configurable caps. Match the HERMES_WEBUI_MAX_UPLOAD_MB style used elsewhere
# (api/config.py) so operators have one consistent env-var convention.
# Bound on per-request wall-clock and bandwidth, not RSS. The zip streams
# straight into handler.wfile, so peak memory is the per-file read buffer
# inside zipfile, not the cap value.
def _folder_zip_max_bytes() -> int:
    try:
        mb = int(os.getenv("HERMES_WEBUI_FOLDER_ZIP_MAX_MB", "1024"))
    except ValueError:
        mb = 1024
    return max(1, mb) * 1024 * 1024


def _folder_zip_max_files() -> int:
    try:
        return max(1, int(os.getenv("HERMES_WEBUI_FOLDER_ZIP_MAX_FILES", "50000")))
    except ValueError:
        return 50000


def _folder_download_collect(target: Path, workspace_root: Path,
                              max_bytes: int, max_files: int):
    """Walk target dir; return (files, total_bytes, hit_limit_reason_or_None).

    files is a list of (filesystem_path, archive_name) tuples ready for
    ZipFile.write. Symlinks escaping the workspace are skipped.
    """
    import os as _os
    files = []
    total_bytes = 0
    for root, dirs, names in _os.walk(target, followlinks=False):
        root_path = Path(root)
        try:
            if not root_path.resolve().is_relative_to(workspace_root):
                dirs[:] = []
                continue
        except (ValueError, OSError):
            dirs[:] = []
            continue
        for name in names:
            fp = root_path / name
            if fp.is_symlink():
                try:
                    if not fp.resolve().is_relative_to(workspace_root):
                        continue
                except (ValueError, OSError):
                    continue
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if len(files) >= max_files:
                return files, total_bytes, "max_files"
            if total_bytes + size > max_bytes:
                return files, total_bytes, "max_bytes"
            try:
                arcname = fp.relative_to(target)
            except ValueError:
                continue
            files.append((fp, str(arcname)))
            total_bytes += size
    return files, total_bytes, None


def _handle_folder_download(handler, parsed):
    """GET /api/folder/download?session_id=...&path=...

    Streams a zip of <session.workspace>/<path>. Symlinks escaping the
    workspace are skipped. Empty folders return an empty (valid) zip.
    Respects HERMES_WEBUI_FOLDER_ZIP_MAX_MB and HERMES_WEBUI_FOLDER_ZIP_MAX_FILES.
    Pre-flights the walk so size/count failures return a clean 413 with JSON
    body BEFORE any zip bytes are sent.
    """
    import zipfile
    from urllib.parse import parse_qs

    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    try:
        s = get_session(sid)
    except KeyError:
        return bad(handler, "Session not found", 404)

    rel = qs.get("path", [""])[0]
    try:
        target = safe_resolve(Path(s.workspace), rel)
    except ValueError:
        return bad(handler, "invalid path", 400)
    if not target.exists():
        return j(handler, {"error": "not found"}, status=404)
    if not target.is_dir():
        return bad(handler, "path must be a directory; use /api/file/raw for single files", 400)

    workspace_root = Path(s.workspace).resolve()
    max_bytes = _folder_zip_max_bytes()
    max_files = _folder_zip_max_files()

    files, total_bytes, limit_hit = _folder_download_collect(
        target, workspace_root, max_bytes, max_files
    )
    if limit_hit == "max_files":
        return j(handler, {
            "error": "too many files",
            "limit": max_files,
            "configure": "HERMES_WEBUI_FOLDER_ZIP_MAX_FILES",
        }, status=413)
    if limit_hit == "max_bytes":
        return j(handler, {
            "error": "folder too large",
            "limit_bytes": max_bytes,
            "configure": "HERMES_WEBUI_FOLDER_ZIP_MAX_MB",
        }, status=413)

    zip_name = (target.name or "workspace") + ".zip"
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header(
        "Content-Disposition",
        _content_disposition_value("attachment", zip_name),
    )
    handler.send_header("Cache-Control", "no-store")
    # Under HTTP/1.1 (Handler.protocol_version, see server.py post-#2836)
    # a response with no Content-Length and no Transfer-Encoding requires
    # Connection: close so the client knows the body ends at FIN. The ZIP
    # is built on-the-fly so we cannot send Content-Length up front; mirror
    # the SSE-endpoint pattern #2836 uses. Without this header the client
    # hangs waiting for the next pipelined response after the central
    # directory bytes finish. Caught by Opus pre-release advisor on
    # stage-batch11.
    handler.send_header("Connection", "close")
    handler.end_headers()

    written = 0
    with zipfile.ZipFile(handler.wfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for fp, arcname in files:
            try:
                zf.write(fp, arcname=arcname)
                written += 1
            except (OSError, PermissionError) as e:
                logger.warning("folder-download: skipping %s: %s", fp, e)
    logger.info(
        "folder-download: streamed %d/%d files (~%d bytes) from %s",
        written, len(files), total_bytes, target,
    )


def _handle_file_view(handler, parsed):
    """Serve workspace HTML/PDF inline in a top-level browser tab.

    Serves file bytes directly (no iframe/embed subresource) so Chromium forks
    like Brave do not treat the navigation as a file download.
    """
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0].strip()
    ws_param = qs.get("workspace", [""])[0].strip()
    if not sid and not ws_param:
        return bad(handler, "session_id or workspace is required")
    rel = qs.get("path", [""])[0]
    session = None
    if ws_param:
        target = _workspace_file_target(ws_param, rel)
    else:
        try:
            session = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        target = _file_raw_target(session, sid, rel)
    if target is None:
        return j(handler, {"error": "not found"}, status=404)
    try:
        file_size = target.stat().st_size
    except OSError:
        return j(handler, {"error": "not found"}, status=404)
    if file_size > PREVIEW_MAX_BYTES:
        return bad(
            handler,
            f"File too large ({file_size} bytes, max {PREVIEW_MAX_BYTES})",
            413,
        )
    ext = target.suffix.lower()
    mime = MIME_MAP.get(ext, "application/octet-stream")
    if mime == "text/html" or ext in {".html", ".htm"}:
        csp = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"
        virt = _workspace_virtual_for_file_handler(ws_param, session)
        disk_root = _workspace_disk_root_for_file_handler(ws_param, session)
        return _serve_inline_html_preview(
            handler,
            target,
            "no-store",
            csp=csp,
            plain_inline_disposition=True,
            workspace_virtual=virt,
            workspace_disk_root=disk_root,
        )
    if mime == "application/pdf" or ext == ".pdf":
        return _serve_file_bytes(
            handler, target, "application/pdf", "inline", "no-store", inline_filename=False
        )
    return _serve_file_bytes(
        handler, target, mime, "inline", "no-store", inline_filename=False
    )


def _handle_file_raw(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0].strip()
    ws_param = qs.get("workspace", [""])[0].strip()
    if not sid and not ws_param:
        return bad(handler, "session_id or workspace is required")
    rel = qs.get("path", [""])[0]
    force_download = qs.get("download", [""])[0] == "1"
    session = None
    if ws_param:
        target = _workspace_file_target(ws_param, rel)
    else:
        try:
            session = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        target = _file_raw_target(session, sid, rel)
    if target is None:
        return j(handler, {"error": "not found"}, status=404)
    ext = target.suffix.lower()
    mime = MIME_MAP.get(ext, "application/octet-stream")
    # Security: force download for dangerous MIME types to prevent XSS.
    # Exception: ?inline=1 permits text/html to be served inline for the
    # sandboxed workspace HTML preview iframe (sandbox="allow-scripts" with no
    # allow-same-origin, so the iframe cannot access parent cookies/storage).
    inline_preview = qs.get("inline", [""])[0] == "1"
    dangerous_types = {"text/html", "application/xhtml+xml", "image/svg+xml"}
    html_inline_ok = inline_preview and mime == "text/html"
    disposition = "attachment" if force_download or (mime in dangerous_types and not html_inline_ok) else "inline"
    # Defense-in-depth for ?inline=1 HTML: even though the workspace.js iframe
    # sets sandbox="allow-scripts", a user could be tricked into opening the
    # ?inline=1 URL directly in a top-level tab (e.g. via a chat link), which
    # would render the HTML in the WebUI's origin without iframe sandbox. The
    # CSP sandbox directive applies the same isolation server-side: without
    # allow-same-origin, the document is treated as a unique opaque origin and
    # cannot read WebUI cookies, localStorage, or postMessage to the parent.
    csp = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox" if html_inline_ok else None
    virt = _workspace_virtual_for_file_handler(ws_param, session) if html_inline_ok else None
    disk_root = _workspace_disk_root_for_file_handler(ws_param, session) if html_inline_ok else None
    # _serve_file_bytes sends Content-Security-Policy when csp is set.
    if html_inline_ok:
        return _serve_inline_html_preview(
            handler,
            target,
            "no-store",
            csp=csp,
            workspace_virtual=virt,
            workspace_disk_root=disk_root,
        )
    return _serve_file_bytes(handler, target, mime, disposition, "no-store", csp=csp)


def _handle_file_read(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0].strip()
    ws_param = qs.get("workspace", [""])[0].strip()
    if not sid and not ws_param:
        return bad(handler, "session_id or workspace is required")
    rel = qs.get("path", [""])[0]
    if not rel:
        return bad(handler, "path is required")
    if ws_param:
        ws_root = _resolve_trusted_workspace_root(ws_param)
        if ws_root is None:
            return bad(handler, "invalid workspace", 400)
        workspace = ws_root
    else:
        try:
            s = get_session(sid)
        except KeyError:
            return bad(handler, "Session not found", 404)
        workspace = Path(s.workspace)
    try:
        return j(handler, read_file_content(workspace, rel))
    except (FileNotFoundError, ValueError) as e:
        return bad(handler, _sanitize_error(e), 404)


def _handle_approval_pending(handler, parsed):
    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    p, total = _approval_head_snapshot(sid)
    if p:
        return j(handler, {"pending": p, "pending_count": total})
    return j(handler, {"pending": None, "pending_count": 0})


def _handle_approval_sse_stream(handler, parsed):
    """SSE endpoint for real-time approval notifications.

    Long-lived connection that pushes approval events the moment they arrive,
    replacing the 1.5s polling loop.  The frontend uses EventSource and falls
    back to HTTP polling if the connection fails.
    """
    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")

    # Subscribe AND snapshot atomically under a single _lock acquisition so a
    # submit_pending() that fires between the two cannot be lost. If we
    # snapshot first then subscribe (the naive ordering), an approval that
    # arrives in the gap is appended to _pending (after our snapshot) AND
    # notified to subscribers (before we joined) — leaving the client unaware
    # until the next event arrives.
    q = queue.Queue(maxsize=16)
    initial_pending = None
    initial_count = 0
    with _lock:
        _approval_sse_subscribers.setdefault(sid, []).append(q)
        initial_pending, initial_count = _approval_head_locked(sid)

    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Connection', 'close')
    handler.end_headers()

    from app.domain.streaming import _sse

    # Push initial state immediately so the client doesn't miss anything.
    _sse(handler, 'initial', {"pending": initial_pending, "pending_count": initial_count})

    try:
        while True:
            try:
                payload = q.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                # Keepalive — SSE comment line prevents proxy/CDN timeout.
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
                continue
            if payload is None:
                break  # signal to close
            _sse(handler, 'approval', payload)
    except _CLIENT_DISCONNECT_ERRORS:
        pass  # client went away — normal for long-lived connections
    finally:
        _approval_sse_unsubscribe(sid, q)


def _handle_approval_inject(handler, parsed):
    """Inject a fake pending approval -- loopback-only, used by automated tests."""
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    key = qs.get("pattern_key", ["test_pattern"])[0]
    cmd = qs.get("command", ["rm -rf /tmp/test"])[0]
    if sid:
        submit_pending(
            sid,
            {
                "command": cmd,
                "pattern_key": key,
                "pattern_keys": [key],
                "description": "test pattern",
            },
        )
        return j(handler, {"ok": True, "session_id": sid})
    return j(handler, {"error": "session_id required"}, status=400)


def _handle_clarify_pending(handler, parsed):
    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    pending = get_clarify_pending(sid)
    if pending:
        return j(handler, {"pending": pending})
    return j(handler, {"pending": None})


def _handle_clarify_sse_stream(handler, parsed):
    """SSE endpoint for real-time clarify notifications.

    Long-lived connection that pushes clarify events the moment they arrive,
    replacing the 1.5s polling loop.  The frontend uses EventSource and falls
    back to HTTP polling if the connection fails.
    """
    if clarify_sse_subscribe is None:
        return bad(handler, "clarify SSE not available")

    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")

    # Subscribe AND snapshot atomically.  We import clarify's _lock so that
    # subscribe and the snapshot read happen under the same mutex — same
    # pattern as the approval SSE handler.
    #
    # NOTE: We must NOT call clarify.get_pending() here — it acquires _lock
    # internally, which would deadlock since clarify._lock is a non-reentrant
    # threading.Lock.  Instead, read _gateway_queues / _pending inline under
    # the lock we already hold.
    from app.domain.clarify import (
        _lock as _clarify_lock,
        _clarify_sse_subscribers as _clarify_subs,
        _gateway_queues as _clarify_gateway_queues,
        _pending as _clarify_pending,
    )
    q = queue.Queue(maxsize=16)
    initial_pending = None
    initial_count = 0
    with _clarify_lock:
        _clarify_subs.setdefault(sid, []).append(q)
        gw_q = _clarify_gateway_queues.get(sid) or []
        if gw_q:
            initial_pending = dict(gw_q[0].data)
            initial_count = len(gw_q)
        else:
            _legacy = _clarify_pending.get(sid)
            if _legacy:
                initial_pending = dict(_legacy)
                initial_count = 1

    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Connection', 'close')
    handler.end_headers()

    from app.domain.streaming import _sse

    # Push initial state immediately so the client doesn't miss anything.
    _sse(handler, 'initial', {"pending": initial_pending, "pending_count": initial_count})

    try:
        while True:
            try:
                payload = q.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
                continue
            if payload is None:
                break
            _sse(handler, 'clarify', payload)
    except _CLIENT_DISCONNECT_ERRORS:
        pass
    finally:
        clarify_sse_unsubscribe(sid, q)


def _handle_clarify_inject(handler, parsed):
    """Inject a fake pending clarify prompt -- loopback-only, used by automated tests."""
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    question = qs.get("question", ["Which option?"])[0]
    choices = qs.get("choices", [])
    if sid:
        submit_clarify_pending(
            sid,
            {
                "question": question,
                "choices_offered": choices,
                "session_id": sid,
                "kind": "clarify",
            },
        )
        return j(handler, {"ok": True, "session_id": sid})
    return j(handler, {"error": "session_id required"}, status=400)


def _handle_live_models(handler, parsed):
    """Return the live model list for a provider.

    Delegates to the agent's provider_model_ids() which handles:
    - OpenRouter: live fetch from /api/v1/models
    - Anthropic: live fetch from /v1/models (API key or OAuth token)
    - Copilot: live fetch from app.domain.githubcopilot.com/models with correct headers
    - openai-codex: Codex OAuth endpoint + local ~/.codex/ cache fallback
    - Nous: live fetch from inference-api.nousresearch.com/v1/models
    - DeepSeek, kimi-coding, opencode-zen/go, custom: generic OpenAI-compat /v1/models
    - ZAI, MiniMax, Google/Gemini: fall back to static list (non-standard endpoints)
    - All others: static _PROVIDER_MODELS fallback

    The agent already maintains all provider-specific auth and endpoint logic
    in one place; the WebUI inherits it rather than duplicating it.

    Query params:
        provider  (optional) — provider ID; defaults to active profile provider
    """
    qs = parse_qs(parsed.query)
    provider = (qs.get("provider", [""])[0] or "").lower().strip()

    try:
        from app.domain.config import get_config as _gc
        cfg = _gc()
        if not provider:
            provider = cfg.get("model", {}).get("provider") or ""
        if not provider:
            return j(handler, {"error": "no_provider", "models": []})

        # Normalize provider alias so 'z.ai' -> 'zai', 'x.ai' -> 'xai', etc.
        # The browser sends whatever active_provider the static endpoint returned;
        # without normalization, provider_model_ids() misses the alias and returns [].
        # Uses the WebUI-owned table (api/config._resolve_provider_alias) which
        # works even when hermes_cli is not on sys.path.
        from app.domain.config import _resolve_provider_alias
        provider = _resolve_provider_alias(provider)

        cache_key = _live_models_cache_key(provider)
        cached = _get_cached_live_models(cache_key)
        if cached is not None:
            return j(handler, cached)

        def _finish(payload: dict):
            _set_cached_live_models(cache_key, payload)
            return j(handler, payload)

        # Delegate to the agent's live-fetch + fallback resolver.
        # provider_model_ids() tries live endpoints first and falls back to
        # the static _PROVIDER_MODELS list — it never raises.
        try:
            import sys as _sys
            import os as _os
            _agent_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                       "..", "..", ".hermes", "hermes-agent")
            _agent_dir = _os.path.normpath(_agent_dir)
            if _agent_dir not in _sys.path:
                _sys.path.insert(0, _agent_dir)
            from hermes_cli.models import provider_model_ids as _pmi
            ids = _pmi(provider)
        except Exception as _import_err:
            logger.debug("provider_model_ids import failed for %s: %s", provider, _import_err)
            ids = []

        if not ids:
            custom_provider_entry = None

            def _custom_provider_entries_for_request():
                if not (provider == "custom" or provider.startswith("custom:")):
                    return []
                try:
                    from app.domain.config import _custom_provider_slug_from_name
                    _cp_entries = cfg.get("custom_providers", [])
                    if not isinstance(_cp_entries, list):
                        return []
                    _matches = []
                    for _cp in _cp_entries:
                        if not isinstance(_cp, dict):
                            continue
                        _slug = _custom_provider_slug_from_name(_cp.get("name", ""))
                        if provider.startswith("custom:"):
                            if _slug == provider:
                                _matches.append(_cp)
                        elif provider == "custom" and not _slug:
                            _matches.append(_cp)
                    return _matches
                except Exception:
                    return []

            def _custom_provider_model_ids(_cp):
                _ids = []

                def _append(_mid):
                    _mid = str(_mid or "").strip()
                    if _mid and _mid not in _ids:
                        _ids.append(_mid)

                _append(_cp.get("model", ""))
                _models = _cp.get("models")
                if isinstance(_models, dict):
                    for _mid in _models:
                        if isinstance(_mid, str):
                            _append(_mid)
                elif isinstance(_models, list):
                    for _item in _models:
                        if isinstance(_item, str):
                            _append(_item)
                        elif isinstance(_item, dict):
                            _append(_item.get("id") or _item.get("model") or _item.get("name"))
                return _ids

            def _custom_provider_api_key(_cp):
                _raw = _cp.get("api_key")
                if _raw is not None:
                    _key = str(_raw).strip()
                    if _key.startswith("${") and _key.endswith("}") and len(_key) > 3:
                        _key = os.getenv(_key[2:-1], "").strip()
                    if _key:
                        return _key
                _env = str(_cp.get("key_env") or "").strip()
                return os.getenv(_env, "").strip() if _env else ""

            # For 'custom' and 'custom:*' providers, provider_model_ids()
            # returns [] because they aren't real hermes_cli endpoints.
            # Fall back to the custom_providers entries from config.yaml so
            # the live-model enrichment step can add any models that weren't
            # already in the static list (issue #1619).
            if provider == "custom" or provider.startswith("custom:"):
                for _cp in _custom_provider_entries_for_request():
                    if custom_provider_entry is None:
                        custom_provider_entry = _cp
                    ids.extend(_custom_provider_model_ids(_cp))
            
            # If still no ids, try fetching from base_url directly (OpenAI-compat endpoint)
            if not ids and (provider == "custom" or provider.startswith("custom:")):
                _base_url = None
                _api_key = None
                if custom_provider_entry:
                    _base_url = custom_provider_entry.get("base_url")
                    _api_key = _custom_provider_api_key(custom_provider_entry)
                else:
                    _model_cfg = cfg.get("model", {})
                    _base_url = _model_cfg.get("base_url")
                    _api_key = _model_cfg.get("api_key")
                if _base_url and _api_key:
                    try:
                        import urllib.request
                        import json
                        
                        # Build the models endpoint URL
                        # AxonHub and similar OpenAI-compat endpoints serve /v1/models
                        _ep = _base_url.rstrip("/")
                        # If base_url already ends with /v1, use /models; otherwise add /v1/models
                        if _ep.endswith("/v1"):
                            _models_url = f"{_ep}/models"
                        else:
                            _models_url = f"{_ep}/v1/models"
                        
                        _req = urllib.request.Request(
                            _models_url,
                            headers={"Authorization": f"Bearer {_api_key}"},
                        )
                        
                        with urllib.request.urlopen(_req, timeout=8) as _resp:
                            _body = json.loads(_resp.read())
                        
                        # Parse response: {"data": [{"id": "model1", ...}, ...]}
                        if isinstance(_body, dict):
                            _data = _body.get("data", [])
                            if isinstance(_data, list):
                                ids = [m.get("id", "") for m in _data if m.get("id")]
                        elif isinstance(_body, list):
                            ids = [m.get("id", m) if isinstance(m, dict) else m for m in _body]
                        
                        if ids:
                            logger.debug("Live-fetched %d models from custom provider %s", len(ids), _base_url)
                        else:
                            logger.debug("Custom provider returned no models from %s", _base_url)
                    
                    except Exception as _fetch_err:
                        logger.debug("Live fetch from custom provider failed: %s", _fetch_err)

        # ── OpenAI-compat live fetch fallback ──────────────────────────────────
        # When provider_model_ids() is unavailable or returns [] for a provider
        # that exposes a standard /v1/models endpoint, fetch directly.  This
        # eliminates the need to keep _PROVIDER_MODELS in sync for providers
        # that have a discoverable API (#871).
        #
        # WARNING: This uses synchronous urllib.request which blocks the worker
        # thread for up to 8 seconds on timeout. This is acceptable because:
        #  (a) the server uses threading (not async), so other requests continue;
        #  (b) the frontend shows the static list immediately and enriches in
        #      the background via _fetchLiveModels(), so the user never waits.
        if not ids:
            _ep = _OPENAI_COMPAT_ENDPOINTS.get(provider)
            if _ep:
                try:
                    import urllib.request
                    _providers_cfg = cfg.get("providers", {})
                    _prov = _providers_cfg.get(provider, {}) if isinstance(_providers_cfg, dict) else {}
                    # Only use provider-scoped key — never fall back to a top-level
                    # api_key which may belong to a different provider.
                    _key = _prov.get("api_key") if isinstance(_prov, dict) else None
                    if not _key:
                        _key = cfg.get("model", {}).get("api_key")
                    if _key:
                        _req = urllib.request.Request(
                            f"{_ep}/models",
                            headers={"Authorization": f"Bearer {_key}"},
                        )
                        with urllib.request.urlopen(_req, timeout=8) as _resp:
                            _body = json.loads(_resp.read())
                        ids = [m.get("id", "") for m in _body.get("data", []) if m.get("id")]
                        logger.debug("Live-fetched %d models from %s /v1/models", len(ids), provider)
                except Exception as _fetch_err:
                    logger.debug("Live fetch from %s failed: %s", provider, _fetch_err)
                    # Fall through to static list below

        # Static fallback — only reached when live fetch also failed.
        if not ids:
            from app.domain.config import _PROVIDER_MODELS as _pm
            ids = [m["id"] for m in _pm.get(provider, [])]
        if not ids:
            return _finish({"provider": provider, "models": [], "count": 0})

        # For Nous Portal, apply the same featured-set cap that
        # /api/models uses so background enrichment via _fetchLiveModels()
        # doesn't undo the dropdown trim — otherwise a 397-model catalog
        # would still flood the picker after the initial render finished
        # the cap. The full list is returned via the main /api/models
        # endpoint's extra_models field for /model autocomplete; the live
        # endpoint is purely a dropdown-enrichment surface, so it should
        # match the dropdown's visibility budget. (#1567)
        if provider == "nous":
            try:
                from app.domain.config import _build_nous_featured_set
                _default_model = (cfg.get("model", {}) or {}).get("model") if isinstance(cfg.get("model"), dict) else None
                _featured, _ = _build_nous_featured_set(ids, selected_model_id=_default_model)
                ids = _featured
            except Exception:
                logger.debug("Failed to apply Nous featured-set cap for /api/models/live")

        # Normalise to {id, label} — provider_model_ids() returns plain string IDs.
        # For ollama-cloud use the shared Ollama formatter (handles `:variant` suffix).
        # For all other providers use a simpler hyphen-split capitaliser.
        from app.domain.config import _format_ollama_label as _fmt_ollama

        def _make_label(mid):
            """Best-effort human label from a model ID string."""
            if provider in ("ollama", "ollama-cloud"):
                return _fmt_ollama(mid)
            # Preserve slashes for router IDs like "anthropic/claude-sonnet-4.6"
            display = mid.split("/")[-1] if "/" in mid else mid
            parts = display.split("-")
            result = []
            for p in parts:
                pl = p.lower()
                if pl == "gpt":
                    result.append("GPT")
                elif pl in ("claude", "gemini", "gemma", "llama", "mistral",
                            "qwen", "deepseek", "grok", "kimi", "glm"):
                    result.append(p.capitalize())
                elif p[:1].isdigit():
                    result.append(p)  # version numbers: 5.4, 3.5, 4.6 — unchanged
                else:
                    result.append(p.capitalize())
            label = " ".join(result)
            # Restore well-known uppercase tokens that title-casing breaks
            for orig in ("GPT", "GLM", "API", "AI", "XL", "MoE"):
                label = label.replace(orig.title(), orig)
            return label

        models_out = [{"id": mid, "label": _make_label(mid)} for mid in ids if mid]
        return _finish({"provider": provider, "models": models_out,
                        "count": len(models_out)})

    except Exception as _e:
        logger.debug("_handle_live_models failed for %s: %s", provider, _e)
        return j(handler, {"error": str(_e), "models": []})


def _handle_cron_history(handler, parsed):
    """List cron run output files with metadata (no content).

    Returns lightweight file listing so the frontend can render a run history
    without fetching full output for every run.
    """
    from cron.jobs import OUTPUT_DIR as CRON_OUT
    import re as _re

    qs = parse_qs(parsed.query)
    job_id = qs.get("job_id", [""])[0]
    if not job_id:
        return j(handler, {"error": "job_id required"}, status=400)
    # Defense-in-depth: cron job_ids are 12-char hex from the agent's scheduler.
    # Without validation, a job_id of "../<other>" would let an authenticated
    # caller enumerate .md filenames in adjacent directories under CRON_OUT's
    # parent. Mirror the rollback checkpoint id regex shape.
    # (Opus pre-release advisor finding.)
    if not _re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", job_id) or job_id in (".", ".."):
        return j(handler, {"error": "invalid job_id"}, status=400)
    # Reject malformed offset/limit instead of letting int() raise ValueError
    # and surface as a confusing 500. Clamp to safe ranges.
    try:
        offset = max(0, int(qs.get("offset", ["0"])[0]))
        limit = max(1, min(500, int(qs.get("limit", ["50"])[0])))
    except (ValueError, TypeError):
        return j(handler, {"error": "offset and limit must be integers"}, status=400)
    out_dir = CRON_OUT / job_id
    runs = []
    total = 0
    if out_dir.exists():
        all_files = sorted(out_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        total = len(all_files)
        page = all_files[offset:offset + limit]
        for f in page:
            try:
                st = f.stat()
                usage = _cron_output_usage_metadata(
                    f.read_text(encoding="utf-8", errors="replace")
                )
                runs.append({
                    "filename": f.name,
                    "size": st.st_size,
                    "modified": st.st_mtime,
                    "usage": usage,
                })
            except OSError:
                logger.debug("Failed to stat cron output file %s", f)
    return j(handler, {"job_id": job_id, "runs": runs, "total": total, "offset": offset})


def _handle_cron_run_detail(handler, parsed):
    """Return full content of a single cron run output file."""
    from cron.jobs import OUTPUT_DIR as CRON_OUT
    import re as _re

    qs = parse_qs(parsed.query)
    job_id = qs.get("job_id", [""])[0]
    filename = qs.get("filename", [""])[0]
    if not job_id or not filename:
        return j(handler, {"error": "job_id and filename required"}, status=400)
    # Validate job_id shape (defense-in-depth even though the resolve+is_relative_to
    # check below catches traversal — fail-closed at the parameter boundary so
    # malformed job_ids return a 400 from the validator rather than a 400 from
    # the path resolver).
    if not _re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}", job_id) or job_id in (".", ".."):
        return j(handler, {"error": "invalid job_id"}, status=400)
    # Prevent path traversal — resolve and verify it stays within the job's output dir
    fpath = (CRON_OUT / job_id / filename).resolve()
    if not fpath.is_relative_to(CRON_OUT.resolve()):
        return j(handler, {"error": "invalid filename"}, status=400)
    if not fpath.exists():
        return j(handler, {"error": "run not found"}, status=404)
    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
        snippet = _cron_output_snippet(content)
        usage = _cron_output_usage_metadata(content)
        return j(handler, {"job_id": job_id, "filename": filename,
                           "content": content, "snippet": snippet,
                           "usage": usage})
    except Exception as e:
        return j(handler, {"error": str(e)}, status=500)


def _cron_output_usage_metadata(text: str) -> dict:
    """Extract optional token/cost metadata from a cron output markdown file."""
    import re as _re

    head = text.split("## Response", 1)[0].split("# Response", 1)[0]
    usage: dict = {}

    def _intish(value: str):
        cleaned = _re.sub(r"[^0-9]", "", value or "")
        return int(cleaned) if cleaned else None

    def _floatish(value: str):
        match = _re.search(r"[-+]?\d+(?:\.\d+)?", (value or "").replace(",", ""))
        return float(match.group(0)) if match else None

    for raw_line in head.splitlines():
        line = raw_line.strip()
        model_match = _re.match(r"\*\*(?:Model|Model Used):\*\*\s*(.+)$", line, _re.I)
        if model_match:
            usage["model"] = model_match.group(1).strip()
            continue
        provider_match = _re.match(r"\*\*Provider:\*\*\s*(.+)$", line, _re.I)
        if provider_match:
            usage["provider"] = provider_match.group(1).strip()
            continue
        cost_match = _re.match(r"\*\*(?:Estimated cost|Cost):\*\*\s*(.+)$", line, _re.I)
        if cost_match:
            cost = _floatish(cost_match.group(1))
            if cost is not None:
                usage["estimated_cost_usd"] = cost
            continue
        duration_match = _re.match(r"\*\*(?:Duration|Elapsed):\*\*\s*(.+)$", line, _re.I)
        if duration_match:
            seconds = _floatish(duration_match.group(1))
            if seconds is not None:
                usage["duration_seconds"] = seconds
            continue
        tokens_match = _re.match(r"\*\*Tokens:\*\*\s*(.+)$", line, _re.I)
        if tokens_match:
            value = tokens_match.group(1)
            input_match = _re.search(r"([0-9][0-9,]*)\s*(?:input|in)\b", value, _re.I)
            output_match = _re.search(r"([0-9][0-9,]*)\s*(?:output|out)\b", value, _re.I)
            total_match = _re.search(r"([0-9][0-9,]*)\s*(?:total\s*)?tokens?\b", value, _re.I)
            if input_match:
                usage["input_tokens"] = _intish(input_match.group(1))
            if output_match:
                usage["output_tokens"] = _intish(output_match.group(1))
            if total_match and "total_tokens" not in usage:
                usage["total_tokens"] = _intish(total_match.group(1))

    if "total_tokens" not in usage:
        total = sum(int(usage.get(k) or 0) for k in ("input_tokens", "output_tokens"))
        if total:
            usage["total_tokens"] = total
    return usage


def _cron_output_snippet(text: str, limit: int = 600) -> str:
    """Extract the response body from a cron output .md file for preview.

    Contract: cron output files use markdown front-matter followed by a
    ``## Response`` (or ``# Response``) heading that marks the start of the
    agent's reply.  This function locates that heading and returns everything
    after it (up to *limit* chars).  If no heading is found the entire text
    is returned — callers should be aware that front-matter fields (model,
    timestamp, …) may appear in the snippet.
    """
    lines = text.split("\n")
    response_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("## Response") or line.startswith("# Response"):
            response_idx = i
            break
    body = ("\n".join(lines[response_idx + 1:]) if response_idx >= 0 else "\n".join(lines)).strip()
    return body[:limit] or "(empty)"


def _handle_cron_output(handler, parsed):
    from cron.jobs import OUTPUT_DIR as CRON_OUT

    qs = parse_qs(parsed.query)
    job_id = qs.get("job_id", [""])[0]
    limit = int(qs.get("limit", ["5"])[0])
    if not job_id:
        return j(handler, {"error": "job_id required"}, status=400)
    out_dir = CRON_OUT / job_id
    outputs = []
    if out_dir.exists():
        files = sorted(out_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
        for f in files:
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
                outputs.append({"filename": f.name, "content": _cron_output_content_window(txt)})
            except Exception:
                logger.debug("Failed to read cron output file %s", f)
    return j(handler, {"job_id": job_id, "outputs": outputs})


def _handle_cron_status(handler, parsed):
    """Return running status for one or all cron jobs."""
    qs = parse_qs(parsed.query)
    job_id = qs.get("job_id", [""])[0]
    if job_id:
        running, elapsed = _is_cron_running(job_id)
        return j(handler, {"job_id": job_id, "running": running, "elapsed": round(elapsed, 1)})
    # Return status for all running jobs
    with _RUNNING_CRON_LOCK:
        all_running = {jid: round(time.time() - t, 1) for jid, t in _RUNNING_CRON_JOBS.items()}
    return j(handler, {"running": all_running})


def _handle_cron_recent(handler, parsed):
    """Return cron jobs that have completed since a given timestamp."""
    import datetime

    qs = parse_qs(parsed.query)
    since = float(qs.get("since", ["0"])[0])
    try:
        from cron.jobs import list_jobs

        jobs = list_jobs(include_disabled=True)
        completions = []
        for job in jobs:
            last_run = job.get("last_run_at")
            if not last_run:
                continue
            if isinstance(last_run, str):
                try:
                    ts = datetime.datetime.fromisoformat(
                        last_run.replace("Z", "+00:00")
                    ).timestamp()
                except (ValueError, TypeError):
                    continue
            else:
                ts = float(last_run)
            if ts > since:
                completions.append(
                    {
                        "job_id": job.get("id", ""),
                        "name": job.get("name", "Unknown"),
                        "status": job.get("last_status", "unknown"),
                        "completed_at": ts,
                        "toast_notifications": job.get("toast_notifications") is not False,
                    }
                )
        return j(handler, {"completions": completions, "since": since})
    except ImportError:
        return j(handler, {"completions": [], "since": since})


def _handle_memory_read(handler):
    from app.core.security import (
        filter_memory_payload_for_user,
        get_current_user_from_legacy_handler,
    )

    try:
        from app.domain.profiles import get_active_hermes_home

        home = get_active_hermes_home()
        mem_dir = home / "memories"
    except ImportError:
        home = Path.home() / ".hermes"
        mem_dir = home / "memories"
    mem_file = mem_dir / "MEMORY.md"
    user_file = mem_dir / "USER.md"
    soul_file = home / "SOUL.md"
    memory = (
        mem_file.read_text(encoding="utf-8", errors="replace")
        if mem_file.exists()
        else ""
    )
    user = (
        user_file.read_text(encoding="utf-8", errors="replace")
        if user_file.exists()
        else ""
    )
    soul = (
        soul_file.read_text(encoding="utf-8", errors="replace")
        if soul_file.exists()
        else ""
    )
    payload = {
        "memory": _redact_text(memory),
        "user": _redact_text(user),
        "soul": _redact_text(soul),
        "memory_path": str(mem_file),
        "user_path": str(user_file),
        "soul_path": str(soul_file),
        "memory_mtime": mem_file.stat().st_mtime if mem_file.exists() else None,
        "user_mtime": user_file.stat().st_mtime if user_file.exists() else None,
        "soul_mtime": soul_file.stat().st_mtime if soul_file.exists() else None,
        "external_notes_enabled": _external_notes_sources_enabled(),
    }
    current_user = get_current_user_from_legacy_handler(handler)
    return j(handler, filter_memory_payload_for_user(payload, current_user))


# ── POST route helpers ────────────────────────────────────────────────────────


def _handle_sessions_cleanup(handler, body, zero_only=False):
    cleaned = 0
    for p in SESSION_DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            s = Session.load(p.stem)
            if zero_only:
                should_delete = s and len(s.messages) == 0
            else:
                should_delete = s and s.title == "Untitled" and len(s.messages) == 0
            if should_delete:
                with LOCK:
                    SESSIONS.pop(p.stem, None)
                p.unlink(missing_ok=True)
                cleaned += 1
        except Exception:
            logger.debug("Failed to clean up session file %s", p)
    if SESSION_INDEX_FILE.exists():
        SESSION_INDEX_FILE.unlink(missing_ok=True)
    return j(handler, {"ok": True, "cleaned": cleaned})


def _handle_btw(handler, body):
    """POST /api/btw — ephemeral side question using session context.

    Creates a temporary hidden session, streams the answer via SSE, then
    discards the session. The parent session is not modified.
    """
    try:
        require(body, "session_id")
        require(body, "question")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)
    question = str(body["question"]).strip()
    if not question:
        return bad(handler, "question is required")
    # Duplicate-stream guard (same pattern as chat/start)
    current_stream_id = getattr(s, "active_stream_id", None)
    if current_stream_id:
        with STREAMS_LOCK:
            if current_stream_id in STREAMS:
                return j(handler, {"error": "session already has an active stream"}, status=409)
        s.active_stream_id = None
    # Create ephemeral hidden session inheriting context
    from app.domain.models import new_session as _new_session
    model_provider = getattr(s, 'model_provider', None)
    ephemeral = _new_session(
        workspace=s.workspace,
        model=s.model,
        model_provider=model_provider,
        profile=getattr(s, 'profile', None),
    )
    # Copy conversation history for context (agent reads from messages)
    ephemeral.messages = list(s.messages or [])
    ephemeral.title = f"btw: {question[:60]}"
    ephemeral.save()
    stream_id = uuid.uuid4().hex
    ephemeral.active_stream_id = stream_id
    ephemeral.save()
    stream = create_stream_channel()
    with STREAMS_LOCK:
        STREAMS[stream_id] = stream
    from app.domain.background import track_btw
    track_btw(body["session_id"], ephemeral.session_id, stream_id, question)
    from app.domain.chat_streaming import run_agent_streaming_in_request_context

    def _run_btw() -> None:
        run_agent_streaming_in_request_context(
            lambda: _run_agent_streaming(
                ephemeral.session_id,
                question,
                s.model,
                s.workspace,
                stream_id,
                None,
                ephemeral=True,
                model_provider=model_provider,
            )
        )

    thr = threading.Thread(target=_run_btw, daemon=True)
    thr.start()
    return j(handler, {"stream_id": stream_id, "session_id": ephemeral.session_id, "parent_session_id": body["session_id"]})


def _handle_background(handler, body):
    """POST /api/background — run prompt in parallel background agent.

    Creates a hidden session, starts streaming in a daemon thread.
    Frontend polls /api/background/status for completed results.
    """
    try:
        require(body, "session_id")
        require(body, "prompt")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)
    prompt = str(body["prompt"]).strip()
    if not prompt:
        return bad(handler, "prompt is required")
    from app.domain.models import new_session as _new_session
    model_provider = getattr(s, 'model_provider', None)
    bg = _new_session(
        workspace=s.workspace,
        model=s.model,
        model_provider=model_provider,
        profile=getattr(s, 'profile', None),
    )
    bg.title = f"bg: {prompt[:60]}"
    bg.save()
    stream_id = uuid.uuid4().hex
    bg.active_stream_id = stream_id
    bg.save()
    stream = create_stream_channel()
    with STREAMS_LOCK:
        STREAMS[stream_id] = stream
    task_id = uuid.uuid4().hex[:8]
    from app.domain.background import track_background, complete_background
    parent_sid = body["session_id"]
    bg_sid = bg.session_id
    track_background(parent_sid, bg_sid, stream_id, task_id, prompt)

    from app.domain.chat_streaming import run_agent_streaming_in_request_context

    def _run_bg_and_notify():
        """Run the background agent, then mark the tracked task `done` with the
        last assistant reply so `/api/background/status` can surface it.  Without
        this, `complete_background()` is never called and the result is lost —
        `get_results()` would see a forever-`running` task and return nothing.
        """
        try:
            run_agent_streaming_in_request_context(
                lambda: _run_agent_streaming(
                    bg_sid,
                    prompt,
                    s.model,
                    s.workspace,
                    stream_id,
                    None,
                    model_provider=model_provider,
                )
            )
            # Reload the bg session from disk and extract the final assistant reply.
            try:
                from app.domain.models import Session as _Session
                reloaded = _Session.load(bg_sid)
                _answer = ""
                for _m in reversed((reloaded.messages if reloaded else None) or []):
                    if not isinstance(_m, dict) or _m.get("role") != "assistant":
                        continue
                    if _m.get("_error"):
                        continue
                    _content = str(_m.get("content") or "").strip()
                    if _content:
                        _answer = _content
                        break
                complete_background(parent_sid, task_id, _answer or "(no answer produced)")
            except Exception:
                complete_background(parent_sid, task_id, "(background task failed)")
            # Best-effort cleanup of the hidden bg session file so it doesn't
            # clutter the sidebar or SESSION_DIR. The index is pruned on the
            # next rebuild via _index_entry_exists().
            try:
                (SESSION_DIR / f"{bg_sid}.json").unlink(missing_ok=True)
            except Exception:
                pass
        except Exception:
            try:
                complete_background(parent_sid, task_id, "(background task failed)")
            except Exception:
                pass

    thr = threading.Thread(target=_run_bg_and_notify, daemon=True)
    thr.start()
    return j(handler, {"task_id": task_id, "stream_id": stream_id, "session_id": bg.session_id})


def _checkpoint_user_message_for_eager_session_save(s, msg: str, attachments, started_at: float | None) -> None:
    """Materialize the current user turn for eager first-turn persistence.

    The streaming thread still receives ``pending_user_message`` so existing
    cancel/recovery/final-merge paths keep their current contract. Eager mode
    only adds a durable display-message checkpoint before the agent launches.
    """
    if not msg:
        return
    existing = list(getattr(s, "messages", None) or [])
    if existing:
        latest = existing[-1]
        if isinstance(latest, dict) and latest.get("role") == "user":
            latest_text = " ".join(str(latest.get("content") or "").split())
            msg_text = " ".join(str(msg or "").split())
            if latest_text == msg_text:
                return
    user_msg = {"role": "user", "content": msg}
    if isinstance(started_at, (int, float)) and started_at > 0:
        user_msg["timestamp"] = int(started_at)
    if attachments:
        user_msg["attachments"] = list(attachments)
    s.messages.append(user_msg)


def _is_default_or_empty_session_title(title) -> bool:
    return str(title or "").strip() in ("", "Untitled", "New Chat")


def _provisional_title_from_prompt(prompt: str, fallback: str = "Untitled") -> str:
    text = str(prompt or "").strip()
    if not text:
        return fallback
    return title_from([{"role": "user", "content": text}], fallback) or fallback


def _prepare_chat_start_session_for_stream(
    s,
    *,
    msg: str,
    attachments,
    workspace: str,
    model: str,
    model_provider,
    stream_id: str,
    started_at: float | None = None,
):
    """Persist chat-start state according to webui.session_save_mode.

    ``deferred`` keeps the existing sidecar/WAL-backed behaviour: save pending
    fields but leave the display transcript empty until the agent merges the
    result. ``eager`` additionally writes the current user turn into messages so
    a process restart immediately after /api/chat/start preserves the prompt as
    a normal session message. Empty sessions are never saved here because this
    helper only runs after a non-empty message is validated.
    """
    s.workspace = workspace
    s.model = model
    s.model_provider = model_provider
    s.active_stream_id = stream_id
    s.pending_user_message = msg
    s.pending_attachments = attachments
    s.pending_started_at = started_at if started_at is not None else time.time()
    current_title = getattr(s, "title", None)
    if _is_default_or_empty_session_title(current_title):
        existing_messages = list(getattr(s, "messages", None) or [])
        if existing_messages:
            recovered_title = title_from(existing_messages, current_title or "Untitled")
            if recovered_title and not _is_default_or_empty_session_title(recovered_title):
                s.title = recovered_title
            else:
                provisional_title = _provisional_title_from_prompt(msg, current_title or "Untitled")
                if provisional_title and not _is_default_or_empty_session_title(provisional_title):
                    s.title = provisional_title
        else:
            provisional_title = _provisional_title_from_prompt(msg, current_title or "Untitled")
            if provisional_title and not _is_default_or_empty_session_title(provisional_title):
                s.title = provisional_title
    if get_webui_session_save_mode() == "eager":
        _checkpoint_user_message_for_eager_session_save(
            s,
            msg,
            attachments,
            s.pending_started_at,
        )
    s.save()


def _is_hidden_empty_session(s) -> bool:
    return (
        getattr(s, "title", "Untitled") == "Untitled"
        and not getattr(s, "messages", None)
        and not getattr(s, "active_stream_id", None)
        and not getattr(s, "pending_user_message", None)
        and not getattr(s, "worktree_path", None)
    )


def _start_chat_stream_for_session(
    s,
    *,
    msg: str,
    attachments=None,
    workspace: str,
    model: str,
    model_provider=None,
    normalized_model: bool = False,
    diag=None,
    goal_related: bool = False,
):
    """Persist pending state, register an SSE channel, and start an agent turn."""
    attachments = attachments or []
    from app.domain.upload import stage_chat_attachments_to_workspace

    attachments, msg = stage_chat_attachments_to_workspace(
        attachments,
        workspace,
        message=msg,
    )
    # Prevent duplicate runs in the same session while a stream is still active.
    # This commonly happens after page refresh/reconnect races and can produce
    # duplicated clarify cards for what appears to be a single user request.
    from app.domain.chat_streaming import (
        new_chat_stream_id,
        register_chat_stream_channel,
        session_has_live_active_stream,
        start_chat_agent_worker,
    )

    diag.stage("active_stream_check") if diag else None
    current_active, current_stream_id = session_has_live_active_stream(s)
    if current_stream_id:
        if current_active:
            diag.stage("response_write") if diag else None
            return {
                "error": "session already has an active stream",
                "active_stream_id": current_stream_id,
                "_status": 409,
            }
        # Stale stream id from a previous run; clear and continue.
        diag.stage("stale_stream_cleanup") if diag else None
        _clear_stale_stream_state(s)

    # #1932: check if this session has a pending goal continuation flag.
    # The streaming hook sets PENDING_GOAL_CONTINUATION when goal_continue fires,
    # so the next chat/start for this session is automatically treated as goal-related.
    if not goal_related and s.session_id in PENDING_GOAL_CONTINUATION:
        goal_related = True
        PENDING_GOAL_CONTINUATION.discard(s.session_id)

    stream_id = new_chat_stream_id()
    session_lock = _get_session_agent_lock(s.session_id)
    diag.stage("session_lock_wait") if diag else None
    with session_lock:
        diag.stage("save_pending_state") if diag else None
        was_hidden_empty_session = _is_hidden_empty_session(s)
        _prepare_chat_start_session_for_stream(
            s,
            msg=msg,
            attachments=attachments,
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            stream_id=stream_id,
        )
    if was_hidden_empty_session:
        publish_session_list_changed("session_new")
    diag.stage("turn_journal_submitted") if diag else None
    journal_event = {}
    try:
        from app.domain.turn_journal import append_turn_journal_event
        journal_event = append_turn_journal_event(
            s.session_id,
            {
                "event": "submitted",
                "stream_id": stream_id,
                "role": "user",
                "content": msg,
                "attachments": attachments,
                "workspace": workspace,
                "model": model,
                "model_provider": model_provider,
                "created_at": s.pending_started_at,
            },
        )
    except Exception:
        logger.warning("Failed to append submitted turn journal event", exc_info=True)
    diag.stage("set_last_workspace") if diag else None
    set_last_workspace(workspace)
    diag.stage("stream_registration") if diag else None
    register_chat_stream_channel(stream_id, goal_related=goal_related)
    diag.stage("worker_thread_start") if diag else None
    start_chat_agent_worker(
        s.session_id,
        msg,
        model,
        workspace,
        stream_id,
        attachments,
        model_provider=model_provider,
        goal_related=goal_related,
    )
    response = {
        "stream_id": stream_id,
        "session_id": s.session_id,
        "pending_started_at": s.pending_started_at,
        "turn_id": journal_event.get("turn_id"),
        "title": s.title,
    }
    if normalized_model:
        response["effective_model"] = model
    if model_provider:
        response["effective_model_provider"] = model_provider
    return response


def _runtime_runner_client_factory():
    """Return the runner-local client when a supervised backend exists.

    Slice 4d wires the `/api/chat/start` selection point without silently falling
    back to the legacy in-process runtime when `runner-local` is explicitly
    requested. The supervised runner backend itself is intentionally not created
    in this helper yet; a later slice can replace this factory with the concrete
    client while keeping the route contract stable.
    """
    raise NotImplementedError("runner-local chat backend is not configured")


def _chat_start_response_from_run_start(result):
    """Expose only the legacy browser-facing chat-start response fields."""
    payload = dict(getattr(result, "payload", {}) or {})
    response = {}
    for key in (
        "stream_id",
        "session_id",
        "pending_started_at",
        "turn_id",
        "title",
        "effective_model",
        "effective_model_provider",
        "error",
        "active_stream_id",
        "_status",
    ):
        if key in payload:
            response[key] = payload[key]
    response.setdefault("stream_id", result.stream_id)
    response.setdefault("session_id", result.session_id)
    return response


def _runtime_adapter_goal_action(goal_args: str) -> str:
    """Return the bounded RuntimeAdapter goal action for WebUI /goal args."""
    action = str(goal_args or "").strip().lower()
    if not action or action == "status":
        return "status"
    if action in ("pause", "resume"):
        return action
    if action in ("clear", "stop", "done"):
        return "clear"
    return "set"


def _handle_goal_command(handler, body):
    """Handle WebUI /goal command controls and optional kickoff stream."""
    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)

    requested_profile = str(body.get("profile") or "").strip()
    if requested_profile:
        try:
            from app.domain.profiles import _PROFILE_ID_RE

            if requested_profile != "default" and not _PROFILE_ID_RE.fullmatch(requested_profile):
                return bad(handler, "invalid profile", 400)
        except ImportError:
            requested_profile = ""
    if requested_profile and not _profiles_match(getattr(s, "profile", None), requested_profile):
        has_persisted_turns = bool(
            getattr(s, "messages", None)
            or getattr(s, "context_messages", None)
            or getattr(s, "pending_user_message", None)
        )
        if not has_persisted_turns:
            s.profile = requested_profile

    current_stream_id = getattr(s, "active_stream_id", None)
    stream_running = False
    if current_stream_id:
        with STREAMS_LOCK:
            stream_running = current_stream_id in STREAMS
        if not stream_running:
            _clear_stale_stream_state(s)

    try:
        from app.domain.profiles import get_hermes_home_for_profile

        profile_home = get_hermes_home_for_profile(getattr(s, "profile", None))
    except Exception:
        profile_home = None

    from app.domain.goals import goal_command_payload, goal_state_snapshot, restore_goal_state

    goal_args = str(body.get("args", "") or body.get("text", "") or "")
    goal_action = goal_args.strip().lower()
    will_kickoff = bool(
        goal_args.strip()
        and goal_action not in ("status", "pause", "resume", "clear", "stop", "done")
        and not stream_running
    )
    workspace = model = model_provider = normalized_model = None
    previous_goal_state = None
    if will_kickoff:
        try:
            workspace = str(resolve_trusted_workspace(body.get("workspace") or s.workspace))
        except ValueError as e:
            return bad(handler, str(e))
        requested_model = body.get("model") or s.model
        requested_provider = (
            body.get("model_provider")
            if "model_provider" in body
            else getattr(s, "model_provider", None)
        )
        model, model_provider, normalized_model = _resolve_compatible_session_model_state(
            requested_model,
            requested_provider,
        )
        previous_goal_state = goal_state_snapshot(s.session_id, profile_home=profile_home)

    from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

    def _legacy_goal_update(session_id: str, _action: str, text: str) -> dict:
        return goal_command_payload(
            session_id,
            text,
            stream_running=stream_running,
            profile_home=profile_home,
        )

    goal_adapter_action = _runtime_adapter_goal_action(goal_args)
    if runtime_adapter_enabled():
        adapter = LegacyJournalRuntimeAdapter(goal_delegate=_legacy_goal_update)
        control_result = adapter.update_goal(
            s.session_id,
            goal_adapter_action,
            goal_args,
        )
        # Slice 3c keeps the adapter as a structural seam only.  Preserve the
        # public /api/goal response by passing through the legacy payload rather
        # than deriving HTTP behavior from ControlResult.accepted/status.
        payload = dict(control_result.payload)
    else:
        payload = _legacy_goal_update(s.session_id, goal_adapter_action, goal_args)
    if not payload.get("ok", True):
        status = 409 if payload.get("error") == "agent_running" else 400
        return j(handler, payload, status=status)

    kickoff_prompt = str(payload.get("kickoff_prompt") or "").strip()
    if kickoff_prompt:
        if workspace is None:
            try:
                workspace = str(resolve_trusted_workspace(body.get("workspace") or s.workspace))
            except ValueError as e:
                return bad(handler, str(e))
        if model is None:
            requested_model = body.get("model") or s.model
            requested_provider = (
                body.get("model_provider")
                if "model_provider" in body
                else getattr(s, "model_provider", None)
            )
            model, model_provider, normalized_model = _resolve_compatible_session_model_state(
                requested_model,
                requested_provider,
            )
        stream_response = _start_chat_stream_for_session(
            s,
            msg=kickoff_prompt,
            attachments=[],
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            normalized_model=normalized_model,
            goal_related=True,
        )
        status = int(stream_response.pop("_status", 200) or 200)
        payload.update(stream_response)
        if status >= 400:
            restore_goal_state(s.session_id, previous_goal_state, profile_home=profile_home)
            payload["ok"] = False
            return j(handler, payload, status=status)

    return j(handler, payload)


def _handle_chat_start(handler, body, diag=None):
    try:
        diag.stage("validate_session_id") if diag else None
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        diag.stage("get_session") if diag else None
        try:
            s = get_session(body["session_id"])
        except KeyError:
            return bad(handler, "Session not found", 404)
        diag.stage("validate_profile") if diag else None
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            try:
                from app.domain.profiles import _PROFILE_ID_RE

                if requested_profile != "default" and not _PROFILE_ID_RE.fullmatch(requested_profile):
                    return bad(handler, "invalid profile", 400)
            except ImportError:
                requested_profile = ""
        if requested_profile and not _profiles_match(getattr(s, "profile", None), requested_profile):
            has_persisted_turns = bool(
                getattr(s, "messages", None)
                or getattr(s, "context_messages", None)
                or getattr(s, "pending_user_message", None)
            )
            if not has_persisted_turns:
                # Empty sessions are placeholders. If the user switches profiles
                # before sending the first turn, run the placeholder under the
                # currently-selected profile instead of the stale one stamped at
                # creation time.
                s.profile = requested_profile
        diag.stage("normalize_message") if diag else None
        msg = str(body.get("message", "")).strip()
        if not msg:
            return bad(handler, "message is required")
        diag.stage("normalize_attachments") if diag else None
        attachments = _normalize_chat_attachments(body.get("attachments") or [])[:20]
        diag.stage("resolve_workspace") if diag else None
        try:
            workspace = _resolve_chat_workspace_with_recovery(s, body.get("workspace"))
        except ValueError as e:
            return bad(handler, str(e))
        from app.domain.upload import normalize_chat_attachment_records
        from app.domain.workspace import _profile_home_for_workspace_access

        try:
            from app.domain.profiles import get_hermes_home_for_profile

            _session_profile_home = (
                _profile_home_for_workspace_access()
                or get_hermes_home_for_profile(getattr(s, "profile", None))
            )
        except Exception:
            _session_profile_home = _profile_home_for_workspace_access()

        attachments = normalize_chat_attachment_records(
            attachments,
            session_workspace=workspace,
            session_id=s.session_id,
            profile_home=_session_profile_home,
        )
        requested_model = body.get("model") or s.model
        requested_provider = (
            body.get("model_provider")
            if "model_provider" in body
            else getattr(s, "model_provider", None)
        )
        diag.stage("resolve_model_provider") if diag else None
        model, model_provider, normalized_model = _resolve_compatible_session_model_state(
            requested_model,
            requested_provider,
        )
        from app.domain.runtime_adapter import (
            LegacyJournalRuntimeAdapter,
            StartRunRequest,
            build_runtime_adapter,
            runtime_adapter_enabled,
            runtime_adapter_runner_enabled,
        )

        if runtime_adapter_enabled() or runtime_adapter_runner_enabled():
            def _legacy_start_run(request: StartRunRequest) -> dict:
                return _start_chat_stream_for_session(
                    s,
                    msg=request.message,
                    attachments=request.attachments,
                    workspace=request.workspace or workspace,
                    model=request.model or model,
                    model_provider=request.provider or model_provider,
                    normalized_model=normalized_model,
                    diag=diag,
                )

            def _legacy_adapter_factory():
                return LegacyJournalRuntimeAdapter(start_run_delegate=_legacy_start_run)

            try:
                adapter = build_runtime_adapter(
                    legacy_adapter_factory=_legacy_adapter_factory,
                    runner_client_factory=_runtime_runner_client_factory,
                )
                if adapter is None:
                    raise NotImplementedError("runtime adapter selection returned no adapter")
                result = adapter.start_run(
                    StartRunRequest(
                        session_id=s.session_id,
                        message=msg,
                        attachments=attachments,
                        workspace=workspace,
                        profile=getattr(s, "profile", None),
                        provider=model_provider,
                        model=model,
                        source="webui",
                        metadata={"route": "/api/chat/start"},
                    )
                )
            except NotImplementedError as exc:
                return j(handler, {"error": str(exc)}, status=501)
            response = _chat_start_response_from_run_start(result)
        else:
            response = _start_chat_stream_for_session(
                s,
                msg=msg,
                attachments=attachments,
                workspace=workspace,
                model=model,
                model_provider=model_provider,
                normalized_model=normalized_model,
                diag=diag,
            )
        status = int(response.pop("_status", 200) or 200)
        diag.stage("response_write") if diag else None
        return j(handler, response, status=status)
    finally:
        if diag:
            diag.finish()



def _resolve_chat_workspace_with_recovery(s, requested_workspace) -> str:
    """Recover stale implicit session workspaces without hiding explicit errors."""
    explicit = requested_workspace not in (None, "")
    candidate = requested_workspace if explicit else getattr(s, "workspace", None)
    try:
        return str(resolve_trusted_workspace(candidate))
    except ValueError:
        if explicit:
            raise
    fallback = str(resolve_trusted_workspace(get_last_workspace()))
    s.workspace = fallback
    try:
        s.save()
    except Exception:
        pass
    return fallback


def _normalize_chat_attachments(raw_attachments):
    """Normalize attachment payloads from the browser.

    Older clients send a list of filenames. Newer clients send upload result
    objects containing name/path/mime/size so image attachments can be supplied
    to Hermes as native multimodal inputs for the current turn.
    """
    normalized = []
    if not isinstance(raw_attachments, list):
        return normalized
    for item in raw_attachments:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("filename") or "").strip()
            path = str(item.get("path") or "").strip()
            workspace_rel = str(item.get("workspace_rel") or "").strip()
            mime = str(item.get("mime") or "").strip()
            att = {
                "name": name or path or Path(workspace_rel).name,
                "path": path or workspace_rel,
                "mime": mime,
            }
            if workspace_rel:
                att["workspace_rel"] = workspace_rel
            size = item.get("size")
            if isinstance(size, int):
                att["size"] = size
            is_image = item.get("is_image")
            if isinstance(is_image, bool):
                att["is_image"] = is_image
            normalized.append(att)
        else:
            value = str(item).strip()
            if value:
                normalized.append({"name": value, "path": "", "mime": ""})
    return normalized


def _handle_chat_sync(handler, body):
    """Fallback synchronous chat endpoint (POST /api/chat). Not used by frontend."""
    s = get_session(body["session_id"])
    msg = str(body.get("message", "")).strip()
    if not msg:
        return j(handler, {"error": "empty message"}, status=400)
    try:
        workspace = str(resolve_trusted_workspace(body.get("workspace") or s.workspace))
    except ValueError as e:
        return bad(handler, str(e))
    with _get_session_agent_lock(s.session_id):
        s.workspace = workspace
        model, model_provider = _resolve_compatible_session_model_state(
            body.get("model") or s.model,
            body.get("model_provider") if "model_provider" in body else getattr(s, "model_provider", None),
        )[:2]
        s.model = model
        s.model_provider = model_provider
    from app.domain.streaming import _ENV_LOCK

    with _ENV_LOCK:
        old_cwd = os.environ.get("TERMINAL_CWD")
        os.environ["TERMINAL_CWD"] = str(workspace)
        old_exec_ask = os.environ.get("HERMES_EXEC_ASK")
        old_session_key = os.environ.get("HERMES_SESSION_KEY")
        os.environ["HERMES_EXEC_ASK"] = "1"
        os.environ["HERMES_SESSION_KEY"] = s.session_id
    try:
        from run_agent import AIAgent

        with CHAT_LOCK:
            from app.domain.config import (
                resolve_model_provider,
                resolve_custom_provider_connection,
            )

            _model, _provider, _base_url = resolve_model_provider(
                model_with_provider_context(s.model, getattr(s, "model_provider", None))
            )
            # Resolve API key via Hermes runtime provider (matches gateway behaviour)
            _api_key = None
            try:
                from app.domain.config import resolve_webui_runtime_provider

                _rt = resolve_webui_runtime_provider(requested=_provider)
                _api_key = _rt.get("api_key")
                # Also use runtime provider/base_url if the webui config didn't resolve them
                if not _provider:
                    _provider = _rt.get("provider")
                if not _base_url:
                    _base_url = _rt.get("base_url")
            except Exception as _e:
                print(
                    f"[webui] WARNING: resolve_runtime_provider failed: {_e}",
                    flush=True,
                )
            if isinstance(_provider, str) and _provider.startswith("custom:"):
                _cp_key, _cp_base = resolve_custom_provider_connection(_provider)
                if not _api_key and _cp_key:
                    _api_key = _cp_key
                if not _base_url and _cp_base:
                    _base_url = _cp_base
            agent = AIAgent(
                model=_model,
                provider=_provider,
                base_url=_base_url,
                api_key=_api_key,
                # Identify browser-originated sessions as WebUI so Hermes Agent
                # does not inject CLI-specific terminal/output guidance.
                platform="webui",
                quiet_mode=True,
                enabled_toolsets=_resolve_cli_toolsets(),
                session_id=s.session_id,
            )
            from app.domain.streaming import (
                _dedupe_replayed_context_messages,
                _merge_display_messages_after_agent_result,
                _restore_display_reasoning_metadata,
                _restore_reasoning_metadata,
                _sanitize_messages_for_api,
                _context_messages_for_new_turn,
                _workspace_context_prefix,
            )
            from app.domain.workspace import build_workspace_agent_system_message
            from app.domain.profiles import get_hermes_home_for_profile

            _sync_profile_home = get_hermes_home_for_profile(getattr(s, "profile", None))
            _sync_workspace_virtual = None
            try:
                from app.domain.workspace import (
                    disk_path_to_virtual,
                    is_virtual_workspace_path,
                    nested_workspaces_enabled,
                )

                if is_virtual_workspace_path(str(s.workspace)):
                    _sync_workspace_virtual = str(s.workspace).strip()
                elif nested_workspaces_enabled() and _sync_profile_home:
                    _sync_workspace_virtual = disk_path_to_virtual(
                        Path(str(s.workspace)),
                        _sync_profile_home,
                    )
            except Exception:
                _sync_workspace_virtual = None
            workspace_ctx = _workspace_context_prefix(
                str(s.workspace),
                profile_home=_sync_profile_home,
                active_workspace_virtual=_sync_workspace_virtual,
            )
            workspace_system_msg = build_workspace_agent_system_message(
                s.workspace,
                profile_home=_sync_profile_home,
            )

            _previous_messages = list(s.messages or [])
            _previous_context_messages = list(_context_messages_for_new_turn(s, msg))

            result = agent.run_conversation(
                user_message=workspace_ctx + msg,
                system_message=workspace_system_msg,
                conversation_history=_sanitize_messages_for_api(
                    _previous_context_messages,
                    cfg=get_config(),
                    provider=_provider,
                    model=_model,
                ),
                task_id=s.session_id,
                persist_user_message=msg,
            )
    finally:
        with _ENV_LOCK:
            if old_cwd is None:
                os.environ.pop("TERMINAL_CWD", None)
            else:
                os.environ["TERMINAL_CWD"] = old_cwd
            if old_exec_ask is None:
                os.environ.pop("HERMES_EXEC_ASK", None)
            else:
                os.environ["HERMES_EXEC_ASK"] = old_exec_ask
            if old_session_key is None:
                os.environ.pop("HERMES_SESSION_KEY", None)
            else:
                os.environ["HERMES_SESSION_KEY"] = old_session_key
    with _get_session_agent_lock(s.session_id):
        _result_messages = result.get("messages") or _previous_context_messages
        _next_context_messages = _restore_reasoning_metadata(
            _previous_context_messages,
            _result_messages,
        )
        _next_context_messages = _dedupe_replayed_context_messages(
            _previous_context_messages,
            _next_context_messages,
        )
        s.context_messages = _next_context_messages
        s.messages = _merge_display_messages_after_agent_result(
            _previous_messages,
            _previous_context_messages,
            _restore_display_reasoning_metadata(_previous_messages, _result_messages),
            msg,
        )
        # Only auto-generate title when still default; preserves user renames
        if s.title == "Untitled":
            s.title = title_from(s.messages, s.title)
        s.save()
    # Sync to state.db for /insights (opt-in setting)
    try:
        if load_settings().get("sync_to_insights"):
            from app.domain.state_sync import sync_session_usage

            sync_session_usage(
                session_id=s.session_id,
                input_tokens=s.input_tokens or 0,
                output_tokens=s.output_tokens or 0,
                estimated_cost=s.estimated_cost,
                model=s.model,
                title=s.title,
                message_count=len(s.messages),
                # #2762 / #2827 parity with api/streaming.py:5078: pass the
                # session's profile explicitly so a future refactor that
                # backgrounds this handler doesn't silently leak writes to
                # the wrong profile's state.db. HTTP thread today, but
                # defense-in-depth. Opus pre-release advisor MUST-FIX.
                profile=getattr(s, 'profile', None),
            )
    except Exception:
        logger.debug("Failed to update session cost tracking")
    return j(
        handler,
        {
            "answer": result.get("final_response") or "",
            "status": "done" if result.get("completed", True) else "partial",
            "session": s.compact() | {"messages": s.messages},
            "result": {k: v for k, v in result.items() if k != "messages"},
        },
    )


def _handle_cron_create(handler, body):
    try:
        require(body, "prompt", "schedule")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        from cron.jobs import create_job, update_job

        profile = _normalize_cron_profile_value(body.get("profile"))
        toast_notifications = body.get("toast_notifications") is not False
        job = create_job(
            prompt=body["prompt"],
            schedule=body["schedule"],
            name=body.get("name") or None,
            deliver=body.get("deliver") or "local",
            skills=body.get("skills") or [],
            model=body.get("model") or None,
        )
        post_create_updates = {}
        if profile is not None:
            post_create_updates["profile"] = profile
        if not toast_notifications:
            post_create_updates["toast_notifications"] = False
        if post_create_updates:
            job = update_job(job["id"], post_create_updates) or job
        return j(handler, {"ok": True, "job": _cron_job_for_api(job)})
    except Exception as e:
        return j(handler, {"error": str(e)}, status=400)


def _handle_cron_delivery_options(handler):
    """Return available delivery platforms for cron jobs."""
    try:
        from cron.scheduler import _KNOWN_DELIVERY_PLATFORMS
    except Exception:
        _KNOWN_DELIVERY_PLATFORMS = frozenset()
    platforms = [
        {"value": "local", "label": "Local (save output only)"},
        {"value": "origin", "label": "Origin (reply to creator)"}
    ]
    for name in sorted(_KNOWN_DELIVERY_PLATFORMS):
        platforms.append({"value": name, "label": name.capitalize()})
    return j(handler, {"platforms": platforms})


def _handle_cron_update(handler, body):
    try:
        require(body, "job_id")
    except ValueError as e:
        return bad(handler, str(e))
    from cron.jobs import update_job

    try:
        updates = {}
        for k, v in body.items():
            if k == "job_id":
                continue
            if k == "profile":
                updates[k] = _normalize_cron_profile_value(v)
            elif v is not None:
                updates[k] = v
    except ValueError as e:
        return bad(handler, str(e))
    job = update_job(body["job_id"], updates)
    if not job:
        return bad(handler, "Job not found", 404)
    return j(handler, {"ok": True, "job": _cron_job_for_api(job)})


def _handle_cron_delete(handler, body):
    try:
        require(body, "job_id")
    except ValueError as e:
        return bad(handler, str(e))
    from cron.jobs import remove_job

    ok = remove_job(body["job_id"])
    if not ok:
        return bad(handler, "Job not found", 404)
    return j(handler, {"ok": True, "job_id": body["job_id"]})


def _handle_cron_run(handler, body):
    job_id = body.get("job_id", "")
    if not job_id:
        return bad(handler, "job_id required")
    from cron.jobs import get_job

    job = get_job(job_id)
    if not job:
        return bad(handler, "Job not found", 404)
    # Prevent double-run: reject if the job is already tracked as running
    already_running, elapsed = _is_cron_running(job_id)
    if already_running:
        return j(handler, {"ok": False, "job_id": job_id, "status": "already_running",
                            "elapsed": round(elapsed, 1)})
    _mark_cron_running(job_id)
    # Capture the TLS-active profile home now — the thread runs after the
    # request finishes, so TLS is gone by then.
    #
    # Resolve directly without a try/except: get_active_hermes_home() does
    # in-memory dict reads + a single Path.is_dir() stat, so the only way
    # it could raise from inside a request handler is if api.profiles
    # itself partially failed to import (in which case we'd already be
    # 500-ing the whole request). A silent fallback to None here would
    # re-introduce the exact bug #1573 fixes — the worker thread would
    # run unpinned against the process-global HERMES_HOME — so we'd
    # rather let any unexpected exception 500 the request than corrupt
    # cross-profile state.
    from app.domain.profiles import get_active_hermes_home

    _profile_home = get_active_hermes_home()
    _execution_profile_home = _profile_home_for_cron_job(job)
    threading.Thread(target=_run_cron_tracked, args=(job, _profile_home, _execution_profile_home), daemon=True).start()
    return j(handler, {"ok": True, "job_id": job_id, "status": "running"})


def _handle_cron_pause(handler, body):
    job_id = body.get("job_id", "")
    if not job_id:
        return bad(handler, "job_id required")
    from cron.jobs import pause_job

    result = pause_job(job_id, reason=body.get("reason"))
    if result:
        return j(handler, {"ok": True, "job": result})
    return bad(handler, "Job not found", 404)


def _handle_cron_resume(handler, body):
    job_id = body.get("job_id", "")
    if not job_id:
        return bad(handler, "job_id required")
    from cron.jobs import resume_job

    result = resume_job(job_id)
    if result:
        return j(handler, {"ok": True, "job": result})
    return bad(handler, "Job not found", 404)


def _git_session(handler, session_id: str):
    if not session_id:
        bad(handler, "session_id required")
        return None
    try:
        return get_session(session_id)
    except KeyError:
        bad(handler, "Session not found", 404)
        return None


def _git_session_workspace(handler, session_id: str):
    session = _git_session(handler, session_id)
    if session is None:
        return None
    from app.domain.workspace import resolve_session_workspace

    return resolve_session_workspace(session.workspace)


def _git_session_and_workspace(handler, session_id: str):
    session = _git_session(handler, session_id)
    if session is None:
        return None, None
    from app.domain.workspace import resolve_session_workspace

    return session, resolve_session_workspace(session.workspace)


def _git_locked_by_active_stream(session) -> bool:
    stream_id = getattr(session, "active_stream_id", None)
    if not stream_id:
        return False
    try:
        from app.domain.config import STREAMS, STREAMS_LOCK

        with STREAMS_LOCK:
            return stream_id in STREAMS
    except Exception:
        return False


def _git_reject_destructive_if_unsafe(handler, session) -> bool:
    from app.domain.workspace_git import (
        GitWorkspaceError,
        WORKSPACE_GIT_DESTRUCTIVE_ENV,
        workspace_git_destructive_enabled,
    )

    if not workspace_git_destructive_enabled():
        _git_bad(
            handler,
            GitWorkspaceError(
                f"Destructive workspace Git operations are disabled. Set {WORKSPACE_GIT_DESTRUCTIVE_ENV}=1 to enable them.",
                "destructive_git_disabled",
            ),
            status=403,
        )
        return True
    if _git_locked_by_active_stream(session):
        _git_bad(
            handler,
            GitWorkspaceError(
                "A session run is active. Wait for it to finish before running this Git operation.",
                "active_stream",
            ),
            status=409,
        )
        return True
    return False


def _handle_git_status(handler, parsed):
    qs = parse_qs(parsed.query)
    workspace = _git_session_workspace(handler, qs.get("session_id", [""])[0])
    if workspace is None:
        return True
    try:
        from app.domain.workspace_git import GitWorkspaceError, git_status

        return j(handler, {"git": git_status(workspace)})
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_branches(handler, parsed):
    qs = parse_qs(parsed.query)
    workspace = _git_session_workspace(handler, qs.get("session_id", [""])[0])
    if workspace is None:
        return True
    try:
        from app.domain.workspace_git import GitWorkspaceError, git_branches

        return j(handler, {"branches": git_branches(workspace)})
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_diff(handler, parsed):
    qs = parse_qs(parsed.query)
    workspace = _git_session_workspace(handler, qs.get("session_id", [""])[0])
    if workspace is None:
        return True
    path = qs.get("path", [""])[0]
    kind = qs.get("kind", ["unstaged"])[0]
    if not path:
        return bad(handler, "path required")
    try:
        from app.domain.workspace_git import GitWorkspaceError, git_diff

        return j(handler, {"diff": git_diff(workspace, path, kind)})
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _git_bad(handler, err, status: int = 400):
    return j(
        handler,
        {
            "error": _sanitize_error(err),
            "code": getattr(err, "code", "git_failed") or "git_failed",
        },
        status=status,
    )


def _git_paths_from_body(body) -> list[str]:
    raw_paths = body.get("paths")
    if raw_paths is None and body.get("path"):
        raw_paths = [body.get("path")]
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, list):
        raise ValueError("paths must be a list")
    return [str(path) for path in raw_paths]


def _handle_git_stage(handler, body):
    try:
        require(body, "session_id")
        paths = _git_paths_from_body(body)
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_stage

        return j(handler, {"ok": True, "git": git_stage(workspace, paths)})
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_unstage(handler, body):
    try:
        require(body, "session_id")
        paths = _git_paths_from_body(body)
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_unstage

        return j(handler, {"ok": True, "git": git_unstage(workspace, paths)})
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_discard(handler, body):
    try:
        require(body, "session_id")
        paths = _git_paths_from_body(body)
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_discard

        return j(
            handler,
            {
                "ok": True,
                "git": git_discard(
                    workspace,
                    paths,
                    delete_untracked=bool(body.get("delete_untracked")),
                ),
            },
        )
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _llm_git_commit_message(system_prompt: str, user_prompt: str, session=None) -> str:
    from app.domain import profiles as profiles_api

    active_profile = profiles_api.get_active_profile_name() or "default"
    with profiles_api.profile_env_for_background_worker(
        active_profile,
        "git commit message",
        logger_override=logger,
    ):
        from app.domain.config import (
            get_effective_default_model,
            model_with_provider_context,
            resolve_custom_provider_connection,
            resolve_model_provider,
        )

        session_model = str(getattr(session, "model", "") or "").strip()
        session_provider = str(getattr(session, "model_provider", "") or "").strip() or None
        model_for_resolution = (
            model_with_provider_context(session_model, session_provider)
            if session_model
            else get_effective_default_model()
        )
        _main_model, _main_provider, _main_base_url = resolve_model_provider(model_for_resolution)
        _main_api_key = None
        try:
            from app.domain.oauth import resolve_runtime_provider_with_anthropic_env_lock
            from hermes_cli.runtime_provider import resolve_runtime_provider

            _rt = resolve_runtime_provider_with_anthropic_env_lock(
                resolve_runtime_provider,
                requested=_main_provider,
            )
            _main_api_key = _rt.get("api_key")
            if not _main_provider:
                _main_provider = _rt.get("provider")
            if not _main_base_url:
                _main_base_url = _rt.get("base_url")
        except Exception as _e:
            logger.debug("git commit message runtime provider resolution failed: %s", _e)
        if isinstance(_main_provider, str) and _main_provider.startswith("custom:"):
            _cp_key, _cp_base = resolve_custom_provider_connection(_main_provider)
            if not _main_api_key and _cp_key:
                _main_api_key = _cp_key
            if not _main_base_url and _cp_base:
                _main_base_url = _cp_base

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        main_runtime = {
            "provider": _main_provider,
            "model": _main_model,
            "base_url": _main_base_url,
            "api_key": _main_api_key,
        }
        try:
            from agent.auxiliary_client import get_text_auxiliary_client

            aux_client, aux_model = get_text_auxiliary_client(
                "compression",
                main_runtime=main_runtime,
            )
            if aux_client is not None and aux_model:
                response = aux_client.chat.completions.create(
                    model=aux_model,
                    messages=messages,
                )
                return str(response.choices[0].message.content or "").strip()
        except Exception as _e:
            logger.debug("git commit message auxiliary model failed; falling back to main model: %s", _e)

        from run_agent import AIAgent

        agent = AIAgent(
            model=_main_model,
            provider=_main_provider,
            base_url=_main_base_url,
            api_key=_main_api_key,
            platform="webui",
            quiet_mode=True,
            enabled_toolsets=[],
            session_id=f"git-commit-message-{uuid.uuid4().hex[:8]}",
        )
        result = agent.run_conversation(
            user_message=user_prompt,
            system_message=system_prompt,
            conversation_history=[],
            task_id=f"git-commit-message-{uuid.uuid4().hex[:8]}",
        )
        return str(result.get("final_response") or "").strip()


def _handle_git_commit_message(handler, body):
    from app.domain.workspace_git import (
        GitWorkspaceError,
        clean_generated_commit_message,
        staged_commit_message_prompt,
    )

    try:
        require(body, "session_id")
        session = get_session(body["session_id"])
        workspace = Path(session.workspace)

        prompt = staged_commit_message_prompt(workspace)
        message = clean_generated_commit_message(
            _llm_git_commit_message(prompt["system_prompt"], prompt["user_prompt"], session=session)
        )
        if not message:
            raise GitWorkspaceError("No commit message was generated")
        return j(handler, {"ok": True, "message": message, "truncated": bool(prompt.get("truncated"))})
    except KeyError:
        return bad(handler, "Session not found", 404)
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)
    except Exception as e:
        logger.exception("git commit message generation failed")
        return bad(handler, _sanitize_error(e), 500)


def _handle_git_commit_message_selected(handler, body):
    from app.domain.workspace_git import (
        GitWorkspaceError,
        clean_generated_commit_message,
        selected_commit_message_prompt,
    )

    try:
        require(body, "session_id")
        paths = _git_paths_from_body(body)
        session = get_session(body["session_id"])
        workspace = Path(session.workspace)

        prompt = selected_commit_message_prompt(workspace, paths)
        message = clean_generated_commit_message(
            _llm_git_commit_message(prompt["system_prompt"], prompt["user_prompt"], session=session)
        )
        if not message:
            raise GitWorkspaceError("No commit message was generated")
        return j(handler, {"ok": True, "message": message, "truncated": bool(prompt.get("truncated"))})
    except KeyError:
        return bad(handler, "Session not found", 404)
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)
    except Exception as e:
        logger.exception("selected git commit message generation failed")
        return bad(handler, _sanitize_error(e), 500)


def _handle_git_commit(handler, body):
    try:
        require(body, "session_id", "message")
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_commit

        return j(handler, git_commit(workspace, body.get("message", "")))
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_commit_selected(handler, body):
    try:
        require(body, "session_id", "message")
        paths = _git_paths_from_body(body)
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_commit_selected

        return j(handler, git_commit_selected(workspace, body.get("message", ""), paths))
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_remote_action(handler, body, action: str):
    try:
        require(body, "session_id")
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if action in {"pull", "push"} and _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_fetch, git_pull, git_push

        actions = {
            "fetch": git_fetch,
            "pull": git_pull,
            "push": git_push,
        }
        return j(handler, actions[action](workspace))
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_checkout(handler, body):
    try:
        require(body, "session_id", "ref", "mode")
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_checkout

        result = git_checkout(
            workspace,
            str(body.get("ref", "")),
            str(body.get("mode", "local")),
            new_branch=body.get("new_branch"),
            track=bool(body.get("track")),
            dirty_mode=str(body.get("dirty_mode", "block")),
        )
        return j(
            handler,
            {
                "ok": True,
                "git": result.get("status"),
                "branches": result.get("branches"),
                "current_branch": result.get("current_branch"),
                "message": result.get("message", ""),
            },
        )
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_git_stash_checkout(handler, body):
    try:
        require(body, "session_id", "ref", "mode")
        session, workspace = _git_session_and_workspace(handler, body["session_id"])
        if workspace is None:
            return True
        if _git_reject_destructive_if_unsafe(handler, session):
            return True
        from app.domain.workspace_git import GitWorkspaceError, git_stash_and_checkout

        result = git_stash_and_checkout(
            workspace,
            str(body.get("ref", "")),
            str(body.get("mode", "local")),
            new_branch=body.get("new_branch"),
            track=bool(body.get("track")),
        )
        return j(
            handler,
            {
                "ok": True,
                "git": result.get("status"),
                "branches": result.get("branches"),
                "current_branch": result.get("current_branch"),
                "message": result.get("message", ""),
                "stash_name": result.get("stash_name", ""),
                "stashed": bool(result.get("stashed")),
                "restored_stash": result.get("restored_stash"),
                "restore_failed": bool(result.get("restore_failed")),
                "restore_error": result.get("restore_error", ""),
                "restore_stash": result.get("restore_stash"),
            },
        )
    except ValueError as e:
        return bad(handler, str(e))
    except GitWorkspaceError as e:
        return _git_bad(handler, e)


def _handle_file_delete(handler, body):
    try:
        require(body, "path")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        target = safe_resolve(workspace, body["path"])
        if not target.exists():
            return bad(handler, "File not found", 404)
        if target.is_dir():
            if not body.get("recursive"):
                return bad(handler, "Set recursive=true to delete directories")
            shutil.rmtree(target)
        else:
            target.unlink()
        return j(handler, {"ok": True, "path": body["path"]})
    except (ValueError, PermissionError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_save(handler, body):
    try:
        require(body, "path")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        target = safe_resolve(workspace, body["path"])
        if not target.exists():
            return bad(handler, "File not found", 404)
        if target.is_dir():
            return bad(handler, "Cannot save: path is a directory")
        target.write_text(body.get("content", ""), encoding="utf-8")
        return j(
            handler, {"ok": True, "path": body["path"], "size": target.stat().st_size}
        )
    except (ValueError, PermissionError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_create(handler, body):
    try:
        require(body, "path")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        target = safe_resolve(workspace, body["path"])
        if target.exists():
            return bad(handler, "File already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = body.get("content", "")
        if body.get("encoding") == "base64":
            import base64

            from app.domain.config import MAX_UPLOAD_BYTES

            try:
                data = base64.b64decode(content, validate=True)
            except Exception:
                return bad(handler, "Invalid base64 content")
            if len(data) > MAX_UPLOAD_BYTES:
                return bad(
                    handler,
                    f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)",
                    413,
                )
            target.write_bytes(data)
        else:
            target.write_text(content, encoding="utf-8")
        return j(
            handler, {"ok": True, "path": str(target.relative_to(workspace))}
        )
    except (ValueError, PermissionError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_rename(handler, body):
    try:
        require(body, "path", "new_name")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        source = safe_resolve(workspace, body["path"])
        if not source.exists():
            return bad(handler, "File not found", 404)
        new_name = body["new_name"].strip()
        if not new_name or "/" in new_name or ".." in new_name:
            return bad(handler, "Invalid file name")
        dest = source.parent / new_name
        if dest.exists():
            return bad(handler, f'A file named "{new_name}" already exists')
        source.rename(dest)
        new_rel = str(dest.relative_to(workspace))
        return j(handler, {"ok": True, "old_path": body["path"], "new_path": new_rel})
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_move(handler, body):
    try:
        require(body, "path")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        source = safe_resolve(workspace, body["path"])
        if not source.exists():
            return bad(handler, "File not found", 404)

        dest_dir_raw = body.get("dest_dir")
        dest_dir_rel = (
            ""
            if dest_dir_raw is None
            else str(dest_dir_raw).strip().replace("\\", "/").strip("./")
        )
        if dest_dir_rel in (".", "/"):
            dest_dir_rel = ""

        new_name = str(body.get("new_name") or source.name).strip()
        if not new_name or "/" in new_name or ".." in new_name:
            return bad(handler, "Invalid file name")

        if dest_dir_rel:
            dest_parent = safe_resolve(workspace, dest_dir_rel)
            if not dest_parent.exists():
                return bad(handler, "Destination directory not found", 404)
            if not dest_parent.is_dir():
                return bad(handler, "Destination is not a directory", 400)
        else:
            dest_parent = workspace

        dest = dest_parent / new_name
        if source.resolve() == dest.resolve():
            return j(
                handler,
                {
                    "ok": True,
                    "old_path": body["path"],
                    "new_path": str(dest.relative_to(workspace)),
                },
            )

        if source.is_dir():
            try:
                dest.relative_to(source)
                return bad(
                    handler,
                    "Cannot move a folder into itself or its children",
                    400,
                )
            except ValueError:
                pass

        if dest.exists():
            return bad(
                handler,
                f'A file named "{new_name}" already exists in the destination',
            )

        source.rename(dest)
        new_rel = str(dest.relative_to(workspace))
        return j(handler, {"ok": True, "old_path": body["path"], "new_path": new_rel})
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_create_dir(handler, body):
    try:
        require(body, "path")
    except ValueError as e:
        return bad(handler, str(e))
    workspace, err, status = _resolve_file_mutation_workspace(body)
    if err:
        return bad(handler, err, status)
    try:
        target = safe_resolve(workspace, body["path"])
        if target.exists():
            return bad(handler, "Path already exists")
        target.mkdir(parents=True)
        return j(
            handler, {"ok": True, "path": str(target.relative_to(workspace))}
        )
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_reveal(handler, body):
    try:
        require(body, "session_id", "path")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)
    try:
        target = safe_resolve(Path(s.workspace), body["path"])
        if not target.exists():
            # Include the resolved server-side path in the error message so
            # the frontend toast can show *which* file the system expected.
            # Useful when a stale session row still references a deleted file
            # (#1764 — Cygnus's screenshot showed a "Failed to reveal: not
            # found" toast that dropped the path entirely, leaving no clue
            # what was missing).
            return bad(handler, f"File not found: {target}", 404)

        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", "-R", str(target)])
        elif system == "Windows":
            subprocess.Popen(["explorer.exe", "/select," + str(target)])
        else:
            # Linux / other — open parent directory
            subprocess.Popen(["xdg-open", str(target.parent)])

        return j(handler, {"ok": True, "path": body["path"]})
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_path(handler, body):
    """Resolve a relative workspace-rooted path into an absolute on-disk path.

    The right-click "Copy file path" action (#1764) wants to put the
    absolute path on the user's clipboard so they can paste it into a
    terminal, editor, or anywhere else without having to round-trip through
    the OS file browser. The frontend can't compute the absolute path on
    its own — `safe_resolve` joins against the session's workspace root
    which only the server knows. The handler here is a thin lookup; no
    filesystem mutation, no OS-specific dispatch. We do NOT require the
    target to exist (unlike `_handle_file_reveal`) — copying the path of a
    just-deleted file is still useful, and refusing would force callers
    to special-case 404s for an action that cannot fail destructively.
    """
    try:
        require(body, "session_id", "path")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)
    try:
        target = safe_resolve(Path(s.workspace), body["path"])
        return j(handler, {"ok": True, "path": str(target)})
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_file_open_vscode(handler, body):
    """Open a workspace file or folder in VS Code (#2735).

    Reads optional ``vscode`` config block from config.yaml:

        vscode:
          command: code          # executable on PATH; defaults to "code"
          host_path_prefix: /home/user/projects       # Docker host path
          container_path_prefix: /app/workspace       # matching container path

    If ``host_path_prefix`` and ``container_path_prefix`` are both set,
    paths that begin with ``container_path_prefix`` are translated to the
    host prefix before being handed to VS Code.  This lets users running
    Hermes WebUI inside Docker still open files in their local editor.
    """
    try:
        require(body, "session_id", "path")
    except ValueError as e:
        return bad(handler, str(e))
    try:
        s = get_session(body["session_id"])
    except KeyError:
        return bad(handler, "Session not found", 404)
    try:
        target = safe_resolve(Path(s.workspace), body["path"])
        if not target.exists():
            return bad(handler, f"File not found: {target}", 404)

        target_str = str(target)

        # Optional Docker host/container path translation
        from app.domain.config import get_config as _get_cfg  # noqa: PLC0415
        vscode_cfg = _get_cfg().get("vscode", {})
        if not isinstance(vscode_cfg, dict):
            vscode_cfg = {}
        container_prefix = vscode_cfg.get("container_path_prefix", "")
        host_prefix = vscode_cfg.get("host_path_prefix", "")
        if container_prefix and host_prefix and target_str.startswith(container_prefix):
            target_str = host_prefix + target_str[len(container_prefix):]

        cmd = vscode_cfg.get("command", "code")
        # Resolve the command to an absolute path so subprocess.Popen finds it
        # even when the server process inherits a minimal PATH (e.g. when
        # launched via start.sh on macOS where /usr/local/bin may be absent).
        resolved_cmd = shutil.which(cmd)
        if resolved_cmd is None:
            # Try common VS Code installation paths as fallback.
            # macOS: /usr/local/bin/code (symlink) or app bundle CLI
            # Linux: /usr/bin/code or snap
            # Windows: user-install under %LOCALAPPDATA%, system-install under %PROGRAMFILES%
            _local_app_data = os.environ.get("LOCALAPPDATA", "")
            _prog_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
            _prog_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")
            _vscode_fallbacks = [
                # macOS
                "/usr/local/bin/code",
                "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                # Linux
                "/usr/bin/code",
                "/snap/bin/code",
                # Windows (user install)
                os.path.join(_local_app_data, "Programs", "Microsoft VS Code", "bin", "code.cmd"),
                # Windows (system install)
                os.path.join(_prog_files, "Microsoft VS Code", "bin", "code.cmd"),
                os.path.join(_prog_files_x86, "Microsoft VS Code", "bin", "code.cmd"),
            ]
            for fb in _vscode_fallbacks:
                if fb and Path(fb).exists():
                    resolved_cmd = fb
                    break
        if resolved_cmd is None:
            return bad(
                handler,
                f"VS Code command not found: {cmd!r}. "
                "Install VS Code and ensure the 'code' CLI is on PATH, "
                "or set vscode.command in config.yaml to the full path.",
            )
        subprocess.Popen([resolved_cmd, target_str])

        return j(handler, {"ok": True, "path": body["path"]})
    except (ValueError, PermissionError, OSError) as e:
        return bad(handler, _sanitize_error(e))


def _handle_workspace_add(handler, body):
    # Strip surrounding paired quotes BEFORE any further processing — macOS
    # Finder's "Copy as Pathname" wraps paths in single quotes, and users
    # routinely paste those quoted strings into the Add Space input.
    # Doing this at the route entry means every downstream check (blocked
    # system path, validate_workspace_to_add, duplicate detection) sees the
    # cleaned form.
    path_str = _strip_surrounding_quotes(body.get("path", "").strip())
    name = body.get("name", "").strip()
    auto_create = body.get("create", False)
    if not path_str:
        return bad(handler, "path is required")
    # Validate the path is NOT a blocked system root BEFORE any filesystem mutation.
    # This prevents creating orphan directories on rejected paths (#782 review).
    # _is_blocked_system_path honours user-tmp carve-outs (e.g. /var/folders on
    # macOS) so pytest's tmp_path_factory paths and other legit user-tmp dirs
    # still register cleanly.
    candidate = Path(path_str).expanduser().resolve()
    if _is_blocked_system_path(candidate):
        return bad(handler, f"Path points to a system directory: {candidate}")
    # Now safe to create the directory if requested
    if auto_create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            return bad(handler, f"Could not create directory: {_sanitize_error(e)}")
    # Full validation (exists, is_dir) — should pass now that dir exists
    try:
        p = validate_workspace_to_add(path_str)
    except ValueError as e:
        return bad(handler, str(e))
    wss = load_workspaces()
    if len(wss) >= MAX_WORKSPACES_PER_PROFILE:
        return bad(
            handler,
            "Each profile can only have one workspace. "
            "It is created automatically under the profile directory.",
        )
    if any(w["path"] == str(p) for w in wss):
        return bad(handler, "Workspace already in list")
    wss.append({"path": str(p), "name": name or p.name})
    save_workspaces(wss)
    return j(handler, {"ok": True, "workspaces": wss})


def _handle_workspace_remove(handler, body):
    path_str = body.get("path", "").strip()
    if not path_str:
        return bad(handler, "path is required")
    return bad(
        handler,
        "The profile workspace cannot be removed. Each profile keeps one auto-created workspace.",
    )


def _handle_workspace_rename(handler, body):
    path_str = body.get("path", "").strip()
    name = body.get("name", "").strip()
    if not path_str or not name:
        return bad(handler, "path and name are required")
    wss = load_workspaces()
    for w in wss:
        if w["path"] == path_str:
            w["name"] = name
            break
    else:
        return bad(handler, "Workspace not found", 404)
    save_workspaces(wss)
    return j(handler, {"ok": True, "workspaces": wss})


def _handle_workspace_reorder(handler, body):
    """Reorder workspaces by providing an ordered list of paths.

    Accepts {"paths": ["path1", "path2", ...]}. The workspaces list is
    rewritten so that entries appear in the given order. Any workspace
    not included in the request is appended at the end (preserves data).
    """
    paths = body.get("paths", [])
    if not paths or not isinstance(paths, list):
        return bad(handler, "paths is required and must be a list")
    wss = load_workspaces()
    by_path = {w["path"]: w for w in wss}
    # Build reordered list: given order first, then any omitted entries
    reordered = []
    seen = set()
    for p in paths:
        p = p.strip()
        if p in by_path and p not in seen:
            reordered.append(by_path[p])
            seen.add(p)
    # Append any workspaces not mentioned (safety net)
    for w in wss:
        if w["path"] not in seen:
            reordered.append(w)
    save_workspaces(reordered)
    return j(handler, {"ok": True, "workspaces": reordered})


def _resolve_approval_legacy(sid: str, approval_id: str, choice: str) -> bool:
    """Resolve an approval through the existing callback path.

    Slice 3b keeps the RuntimeAdapter as a protocol translator: it delegates to
    this legacy helper rather than owning approval queues or callback state.
    """
    # Pop the targeted entry from the pending queue by approval_id. Old clients
    # that omit approval_id still resolve the oldest entry for compatibility.
    pending = None
    found_target = False
    gateway_keys = []
    with _lock:
        queue = _pending.get(sid)
        if isinstance(queue, list):
            if approval_id:
                # Find and remove the specific entry by approval_id.
                for i, entry in enumerate(queue):
                    if entry.get("approval_id") == approval_id:
                        pending = queue.pop(i)
                        found_target = True
                        break
                else:
                    # A stale explicit id must not accidentally approve the
                    # oldest queued command; duplicate/stale responses are
                    # bounded as not-active by the adapter route.
                    pending = None
            else:
                pending = queue.pop(0) if queue else None
                found_target = pending is not None
            if not queue:
                _pending.pop(sid, None)
        elif queue:
            # Legacy single-dict value.
            if not approval_id or queue.get("approval_id") == approval_id:
                pending = _pending.pop(sid, None)
                found_target = pending is not None
        # When no _pending entry found, peek into _gateway_queues for
        # pattern_keys so session-level approval still works. The gateway
        # path is the primary mechanism during active streaming; _pending
        # is only used for UI polling/SSE notification.
        # NOTE: Gateway queue entries don't carry approval_id, so when
        # approval_id is given and _pending is empty, we assume the gateway
        # entry at the head of the queue corresponds. This is safe because
        # gateway entries are consumed synchronously with _pending entries
        # under the same lock — there is no interleaving where a stale
        # approval_id could match a different gateway entry.
        if not pending:
            gw_queue = _gateway_queues.get(sid)
            if gw_queue and len(gw_queue) > 0:
                gw_entry = gw_queue[0]
                # _gateway_queues stores _ApprovalEntry objects; their
                # .data dict carries command, pattern_key, pattern_keys.
                gw_data = getattr(gw_entry, 'data', None) or {}
                gateway_keys = gw_data.get("pattern_keys") or [gw_data.get("pattern_key", "")]
                # Peek is not strict — a concurrent resolver may pop a
                # different gateway entry before we reach
                # resolve_gateway_approval below, but approve_session is
                # idempotent over the session key set so the outcome is
                # the same regardless of which entry wins the race.
                found_target = True
        # Notify SSE subscribers of the new head (or empty state) so the UI
        # surfaces any trailing approvals that were queued behind this one
        # without waiting for the next submit_pending. Without this, a parallel
        # tool-call scenario (#527) would leave the second approval invisible
        # in the SSE path until the next event ever fired (the agent thread
        # would be parked indefinitely from the user's perspective).
        if isinstance(_pending.get(sid), list) and _pending[sid]:
            _approval_sse_notify_locked(sid, _pending[sid][0], len(_pending[sid]))
        else:
            _approval_sse_notify_locked(sid, None, 0)

    # Collect keys from both _pending and _gateway_queues
    keys_from_pending = pending.get("pattern_keys") or [pending.get("pattern_key", "")] if pending else []
    all_keys = [k for k in keys_from_pending if k] + [k for k in gateway_keys if k]
    if choice == "session":
        for k in all_keys:
            approve_session(sid, k)
    elif choice == "always":
        for k in all_keys:
            approve_session(sid, k)
            approve_permanent(k)
        save_permanent_allowlist(_permanent_approved)
    # Unblock the agent thread waiting in the gateway approval queue.
    # This is the primary signal when streaming is active — the agent
    # thread is parked in entry.event.wait() and needs to be woken up.
    gateway_resolved = 0
    if found_target or not approval_id:
        gateway_resolved = resolve_gateway_approval(sid, choice, resolve_all=False) or 0
    # Keep the historical no-id response path truthy for old clients/tests while
    # making stale explicit ids bounded as not-active for Slice 3b.
    return bool(pending) or bool(gateway_resolved) or not bool(approval_id)


def _handle_approval_respond(handler, body):
    sid = body.get("session_id", "")
    if not sid:
        return bad(handler, "session_id is required")
    choice = body.get("choice", "deny")
    if choice not in ("once", "session", "always", "deny"):
        return bad(handler, f"Invalid choice: {choice}")
    approval_id = body.get("approval_id", "")

    from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

    if runtime_adapter_enabled():
        adapter = LegacyJournalRuntimeAdapter(approval_delegate=_resolve_approval_legacy)
        ok = adapter.respond_approval(sid, approval_id, choice).accepted
    else:
        ok = _resolve_approval_legacy(sid, approval_id, choice)
    return j(handler, {"ok": ok, "choice": choice})


def _resolve_clarify_legacy(sid: str, clarify_id: str, response: str) -> bool:
    """Resolve clarify through the existing callback path without new state."""
    # When a stable clarify_id is provided, match the specific entry so stale
    # or late responses from the frontend are reliably rejected (issue #2639).
    if clarify_id:
        from app.domain.clarify import resolve_clarify_by_id
        return resolve_clarify_by_id(sid, clarify_id, response)
    # Legacy path: resolve the oldest pending entry.  Return the REAL result
    # instead of the old unconditional True so the frontend can detect when
    # there is no pending prompt to resolve.
    resolved = resolve_clarify(sid, response, resolve_all=False)
    return bool(resolved)


def _handle_clarify_respond(handler, body):
    sid = body.get("session_id", "")
    if not sid:
        return bad(handler, "session_id is required")
    response = body.get("response")
    if response is None:
        response = body.get("answer")
    if response is None:
        response = body.get("choice")
    response = str(response or "").strip()
    if not response:
        return bad(handler, "response is required")
    clarify_id = body.get("clarify_id", "")

    from app.domain.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

    if runtime_adapter_enabled():
        adapter = LegacyJournalRuntimeAdapter(clarify_delegate=_resolve_clarify_legacy)
        ok = adapter.respond_clarify(sid, clarify_id, response).accepted
    else:
        ok = _resolve_clarify_legacy(sid, clarify_id, response)

    if not ok:
        # Both the runtime adapter and legacy paths set ok=False for
        # stale/expired/wrong-session responses.  The 409 status applies
        # uniformly regardless of which path resolved the clarify request.
        return j(handler, {
            "ok": False,
            "error": "Clarification prompt expired or not found. The agent may have already proceeded.",
            "stale": True,
        }, status=409)

    return j(handler, {"ok": True, "response": response})


class _ManualCompressionMemoryHandler:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def payload(self):
        raw = self.wfile.getvalue().decode("utf-8")
        return json.loads(raw) if raw else {}


def _manual_compression_cleanup_locked(now=None):
    now = time.time() if now is None else now
    for sid, job in list(_MANUAL_COMPRESSION_JOBS.items()):
        if job.get("status") == "running":
            continue
        updated_at = float(job.get("updated_at") or job.get("started_at") or now)
        if now - updated_at > _MANUAL_COMPRESSION_JOB_TTL_SECONDS:
            _MANUAL_COMPRESSION_JOBS.pop(sid, None)


def _manual_compression_status_payload(job):
    status = job.get("status") or "running"
    payload = {
        "ok": status not in {"error", "cancelled"},
        "status": status,
        "session_id": job.get("session_id"),
        "focus_topic": job.get("focus_topic"),
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
    }
    if status == "done":
        result = job.get("result")
        if isinstance(result, dict):
            payload.update(result)
        payload["status"] = "done"
        payload["ok"] = True
    elif status == "error":
        payload["ok"] = False
        payload["error"] = job.get("error") or "Compression failed"
        payload["error_status"] = int(job.get("error_status") or 400)
    elif status == "cancelled":
        payload["ok"] = False
        payload["error"] = job.get("error") or "Compression cancelled"
        payload["error_status"] = int(job.get("error_status") or 409)
    return payload


def _run_manual_compression_job(sid, body):
    memory_handler = _ManualCompressionMemoryHandler()
    try:
        try:
            session = get_session(sid)
        except KeyError:
            session = None
        if session is not None:
            from app.domain import profiles as profiles_api

            with profiles_api.profile_env_for_background_worker(session, "manual compression", logger_override=logger):
                _handle_session_compress(memory_handler, body)
        else:
            _handle_session_compress(memory_handler, body)
        status = int(memory_handler.status or 500)
        payload = memory_handler.payload()
        with _MANUAL_COMPRESSION_JOBS_LOCK:
            job = _MANUAL_COMPRESSION_JOBS.get(sid)
            if not job:
                return
            now = time.time()
            if status >= 400 or not isinstance(payload, dict) or payload.get("error"):
                job.update(
                    {
                        "status": "error",
                        "error": str((payload or {}).get("error") or "Compression failed"),
                        "error_status": status,
                        "updated_at": now,
                    }
                )
            else:
                job.update(
                    {
                        "status": "done",
                        "result": payload,
                        "updated_at": now,
                    }
                )
    except Exception as exc:
        logger.warning("Manual compression worker failed for session %s: %s", sid, exc)
        with _MANUAL_COMPRESSION_JOBS_LOCK:
            job = _MANUAL_COMPRESSION_JOBS.get(sid)
            if job:
                job.update(
                    {
                        "status": "error",
                        "error": f"Compression failed: {_sanitize_error(exc)}",
                        "error_status": 500,
                        "updated_at": time.time(),
                    }
                )


def _handle_session_compress_start(handler, body):
    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))

    sid = str(body.get("session_id") or "").strip()
    if not sid:
        return bad(handler, "session_id is required")
    try:
        s = get_session(sid)
    except KeyError:
        return bad(handler, "Session not found", 404)
    if getattr(s, "active_stream_id", None):
        return bad(handler, "Session is still streaming; wait for the current turn to finish.", 409)

    focus_topic = str(body.get("focus_topic") or body.get("topic") or "").strip()[:500] or None
    job_body = {"session_id": sid}
    if focus_topic:
        job_body["focus_topic"] = focus_topic

    now = time.time()
    with _MANUAL_COMPRESSION_JOBS_LOCK:
        _manual_compression_cleanup_locked(now)
        existing = _MANUAL_COMPRESSION_JOBS.get(sid)
        if existing:
            existing_payload = _manual_compression_status_payload(existing)
            if existing_payload.get("status") == "running":
                return j(handler, existing_payload)
            # Stage-344 Opus SHOULD-FIX (#2128): always start fresh on re-invoke.
            # The prior implementation short-circuited and returned a stale `done`
            # payload for the full 10-minute TTL window when /compress/start was
            # re-invoked, so a user closing the tab mid-compress and re-running
            # /compress on a fresh open would get the previous result back rather
            # than a new compression. Drop the entry and fall through to the
            # fresh-worker path below.
            _MANUAL_COMPRESSION_JOBS.pop(sid, None)
        job = {
            "session_id": sid,
            "focus_topic": focus_topic,
            "status": "running",
            "started_at": now,
            "updated_at": now,
        }
        _MANUAL_COMPRESSION_JOBS[sid] = job

    worker = threading.Thread(
        target=_run_manual_compression_job,
        args=(sid, job_body),
        name=f"manual-compress-{sid[:8]}",
        daemon=True,
    )
    worker.start()

    with _MANUAL_COMPRESSION_JOBS_LOCK:
        return j(handler, _manual_compression_status_payload(_MANUAL_COMPRESSION_JOBS.get(sid, job)))


def _handle_session_compress_status(handler, sid):
    sid = str(sid or "").strip()
    if not sid:
        return bad(handler, "session_id is required")
    with _MANUAL_COMPRESSION_JOBS_LOCK:
        _manual_compression_cleanup_locked()
        job = _MANUAL_COMPRESSION_JOBS.get(sid)
        if not job:
            return j(handler, {"ok": True, "status": "idle", "session_id": sid})
        payload = _manual_compression_status_payload(job)
        # Stage-344 Opus SHOULD-FIX (#2128): do not pop the job on first
        # read of a `done` payload. The session may be open in multiple
        # tabs, and the first tab's poll would otherwise leave the second
        # tab with `idle` and a "Compression job is no longer available"
        # toast. Let the 10-minute TTL handle eviction so all open tabs
        # see the same terminal payload.
        return j(handler, payload)


def _handle_session_compress(handler, body):
    def _anchor_message_key(m):
        if not isinstance(m, dict):
            return None
        role = str(m.get("role") or "")
        if not role or role == "tool":
            return None
        content = m.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                str(p.get("text") or p.get("content") or "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(content or "")
        norm = " ".join(text.split()).strip()[:160]
        ts = m.get("_ts") or m.get("timestamp")
        attachments = m.get("attachments")
        attach_count = len(attachments) if isinstance(attachments, list) else 0
        if not norm and not attach_count and not ts:
            return None
        return {"role": role, "ts": ts, "text": norm, "attachments": attach_count}

    def _compression_summary_from_messages(messages):
        text = None
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").lower()
            if role != "assistant":
                continue
            if not isinstance(m.get("content"), str):
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            norm = re.sub(r"\s+", " ", content).strip()
            if (
                "context compaction" in norm.lower()
                or "context compression" in norm.lower()
            ):
                return norm
        return None

    def _compact_summary_text(raw_text):
        if not isinstance(raw_text, str):
            return None
        txt = raw_text.strip()
        if not txt:
            return None
        txt = re.sub(r"\s+", " ", txt)
        if len(txt) > 320:
            txt = f"{txt[:314]}…"
        return txt

    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))

    sid = str(body.get("session_id") or "").strip()
    if not sid:
        return bad(handler, "session_id is required")

    # Cap focus_topic to 500 chars — matches the defensive input-size pattern
    # used elsewhere (session title :80, first-exchange snippets :500) and
    # prevents a user from forwarding an unbounded string into the compressor
    # prompt path. No privilege boundary here (user prompting themself), just
    # cheap bound-checking.
    focus_topic = str(body.get("focus_topic") or body.get("topic") or "").strip()[:500] or None

    try:
        s = get_session(sid)
    except KeyError:
        return bad(handler, "Session not found", 404)

    if getattr(s, "active_stream_id", None):
        return bad(handler, "Session is still streaming; wait for the current turn to finish.", 409)

    try:
        from app.domain.streaming import _sanitize_messages_for_api

        messages = _sanitize_messages_for_api(s.messages)
        if len(messages) < 4:
            return bad(handler, "Not enough conversation to compress (need at least 4 messages).")

        def _fallback_estimate_messages_tokens_rough(msgs):
            """Fallback heuristic token estimate when runtime metadata helpers are absent.

            Uses whitespace token-like word counting only. This intentionally
            over/under-estimates BPE token counts (roughly around x3/x4 scale),
            and is only for resilient fallback behavior.
            """
            total = 0
            for m in msgs or []:
                if not isinstance(m, dict):
                    continue
                content = m.get("content", "")
                if isinstance(content, list):
                    content_text = "\n".join(
                        str(p.get("text") or p.get("content") or "")
                        for p in content
                        if isinstance(p, dict)
                    )
                else:
                    content_text = str(content or "")
                total += len(content_text.split())
            return max(1, total)

        def _fallback_summarize_manual_compression(original_messages, compressed_messages, before_tokens, after_tokens, focus_topic=None):
            """Lightweight fallback summary to keep /session/compress usable in tests/runtime."""
            after_tokens = after_tokens if after_tokens is not None else _fallback_estimate_messages_tokens_rough(compressed_messages)
            headline = f"Compressed: {len(original_messages)} \u2192 {len(compressed_messages)} messages"
            summary = {
                "headline": headline,
                "token_line": f"Rough transcript estimate: ~{before_tokens} \u2192 ~{after_tokens} tokens",
                "note": f"Focus: {focus_topic}" if focus_topic else None,
            }
            summary["reference_message"] = (
                f"[CONTEXT COMPACTION \u2014 REFERENCE ONLY] {headline}\n"
                f"{summary['token_line']}\n"
                + (summary["note"] + "\n" if summary.get("note") else "")
                + "Compression completed."
            )
            return summary

        def _estimate_messages_tokens_rough(msgs):
            try:
                from agent.model_metadata import estimate_messages_tokens_rough

                return estimate_messages_tokens_rough(msgs)
            except Exception:
                return _fallback_estimate_messages_tokens_rough(msgs)

        def _summarize_manual_compression(
            original_messages,
            compressed_messages,
            before_tokens,
            after_tokens,
            focus_topic=None,
        ):
            try:
                from agent.manual_compression_feedback import summarize_manual_compression

                return summarize_manual_compression(
                    original_messages,
                    compressed_messages,
                    before_tokens,
                    after_tokens,
                )
            except Exception:
                return _fallback_summarize_manual_compression(
                    original_messages,
                    compressed_messages,
                    before_tokens,
                    after_tokens,
                    focus_topic,
                )

        import app.domain.config as _cfg
        from app.domain.oauth import resolve_runtime_provider_with_anthropic_env_lock
        import hermes_cli.runtime_provider as _runtime_provider
        import run_agent as _run_agent

        resolved_model, resolved_provider, resolved_base_url = _cfg.resolve_model_provider(
            _cfg.model_with_provider_context(s.model, getattr(s, "model_provider", None))
        )

        resolved_api_key = None
        try:
            _rt = resolve_runtime_provider_with_anthropic_env_lock(
                _runtime_provider.resolve_runtime_provider,
                requested=resolved_provider,
            )
            resolved_api_key = _rt.get("api_key")
            if not resolved_provider:
                resolved_provider = _rt.get("provider")
            if not resolved_base_url:
                resolved_base_url = _rt.get("base_url")
        except Exception as _e:
            logger.warning("resolve_runtime_provider failed for compression: %s", _e)

        if isinstance(resolved_provider, str) and resolved_provider.startswith("custom:"):
            _cp_key, _cp_base = _cfg.resolve_custom_provider_connection(resolved_provider)
            if not resolved_api_key and _cp_key:
                resolved_api_key = _cp_key
            if not resolved_base_url and _cp_base:
                resolved_base_url = _cp_base

        if not resolved_api_key:
            return bad(handler, "No provider configured -- cannot compress.")

        # Compute compression *outside* the lock — the LLM round-trip can take
        # many seconds and we must not block cancel_stream or other writers.
        # Lock contract: hold for the in-memory mutation only, never across
        # network I/O.
        original_messages = list(messages)
        original_stream_state = (
            getattr(s, "active_stream_id", None),
            getattr(s, "pending_user_message", None),
            copy.deepcopy(getattr(s, "pending_attachments", None)),
            getattr(s, "pending_started_at", None),
        )
        approx_tokens = _estimate_messages_tokens_rough(original_messages)

        agent = _run_agent.AIAgent(
            model=resolved_model,
            provider=resolved_provider,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            # Identify browser-originated sessions as WebUI so Hermes Agent
            # does not inject CLI-specific terminal/output guidance.
            platform="webui",
            quiet_mode=True,
            enabled_toolsets=_resolve_cli_toolsets(),
            session_id=sid,
        )
        compressed = agent.context_compressor.compress(
            original_messages,
            current_tokens=approx_tokens,
            focus_topic=focus_topic,
        )
        new_tokens = _estimate_messages_tokens_rough(compressed)
        summary = _summarize_manual_compression(
            original_messages,
            compressed,
            approx_tokens,
            new_tokens,
            focus_topic=focus_topic,
        )

        with _cfg._get_session_agent_lock(sid):
            # Re-read messages to detect concurrent edits during the LLM call.
            # If the history changed, the compression result is stale — abort.
            current_stream_state = (
                getattr(s, "active_stream_id", None),
                getattr(s, "pending_user_message", None),
                copy.deepcopy(getattr(s, "pending_attachments", None)),
                getattr(s, "pending_started_at", None),
            )
            if current_stream_state != original_stream_state:
                return bad(handler, "Session stream state changed during compression; please retry.", 409)
            if _sanitize_messages_for_api(s.messages) != original_messages:
                return bad(handler, "Session was modified during compression; please retry.", 409)

            compressed = normalize_compaction_message_roles(compressed)
            s.messages = compressed
            s.context_messages = compressed
            s.tool_calls = []
            s.active_stream_id = None
            s.pending_user_message = None
            s.pending_attachments = []
            s.pending_started_at = None
            visible_after = visible_messages_for_anchor(compressed, auto_compression=False)
            s.compression_anchor_visible_idx = max(0, len(visible_after) - 1) if visible_after else None
            s.compression_anchor_message_key = _anchor_message_key(visible_after[-1]) if visible_after else None
            summary_text = None
            if isinstance(summary, dict):
                summary_text = summary.get("reference_message") or summary.get("token_line") or summary.get("headline")
            s.compression_anchor_summary = _compact_summary_text(
                summary_text or _compression_summary_from_messages(compressed) or ""
            )
            s.save()

        session_payload = redact_session_data(
            s.compact() | {
                "messages": s.messages,
                "tool_calls": s.tool_calls,
                "active_stream_id": s.active_stream_id,
                "pending_user_message": s.pending_user_message,
                "pending_attachments": s.pending_attachments,
                "pending_started_at": s.pending_started_at,
                "compression_anchor_visible_idx": getattr(s, "compression_anchor_visible_idx", None),
                "compression_anchor_message_key": getattr(s, "compression_anchor_message_key", None),
            }
        )
        return j(
            handler,
            {
                "ok": True,
                "session": session_payload,
                "summary": summary,
                "focus_topic": focus_topic,
            },
        )
    except Exception as e:
        logger.warning("Manual session compression failed: %s", e)
        return bad(handler, f"Compression failed: {_sanitize_error(e)}")


def _handle_conversation_rounds(handler, body):
    """Return conversation-round count for a gateway session.

    Request body::

        { "session_id": "...", "since": <unix_ts_or_iso> }

    Response::

        { "ok": true, "rounds": 12, "threshold": 10, "should_show": true }
    """
    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))

    sid = str(body.get("session_id") or "").strip()
    if not sid:
        return bad(handler, "session_id is required")

    since = body.get("since")
    if since is not None:
        try:
            since = float(since)
        except (TypeError, ValueError):
            return bad(handler, "since must be a unix timestamp (number)")

    from app.domain.models import count_conversation_rounds, CONVERSATION_ROUND_THRESHOLD

    rounds = count_conversation_rounds(sid, since=since)
    return j(handler, {
        "ok": True,
        "rounds": rounds,
        "threshold": CONVERSATION_ROUND_THRESHOLD,
        "should_show": rounds >= CONVERSATION_ROUND_THRESHOLD,
    })


def _build_handoff_summary_tool_message(
    sid: str,
    summary: str,
    channel: str | None,
    rounds: int | None = None,
    fallback: bool = False,
) -> dict:
    """Build a compact tool-role transcript marker for persistence."""
    now = time.time()
    return {
        "role": "tool",
        # Keep this intentionally empty so API-history sanitization drops it from
        # model context (it is display-only data).
        "tool_call_id": "",
        "name": "handoff_summary",
        "timestamp": now,
        "_ts": now,
        "content": json.dumps({
            "_handoff_summary_card": True,
            "session_id": sid,
            "summary": str(summary or "").strip(),
            "channel": (str(channel or "").strip() or None),
            "rounds": rounds,
            "fallback": bool(fallback),
            "generated_at": now,
        }, ensure_ascii=False),
    }


def _extract_handoff_summary_payload(message: dict) -> dict | None:
    """Return a normalized handoff-summary payload if *message* is a tool marker."""
    if not isinstance(message, dict):
        return None
    if message.get("role") != "tool" or message.get("name") != "handoff_summary":
        return None

    content = message.get("content")
    if isinstance(content, dict):
        payload = content
    else:
        try:
            payload = json.loads(content or "")
        except Exception:
            return None

    if not isinstance(payload, dict) or not payload.get("_handoff_summary_card"):
        return None
    if payload.get("session_id") is None:
        return None
    return {
        "session_id": str(payload.get("session_id")),
        "summary": str(payload.get("summary", "")),
        "channel": payload.get("channel"),
        "rounds": payload.get("rounds"),
        "fallback": bool(payload.get("fallback")),
        "_handoff_summary_card": True,
    }


def _is_matching_handoff_summary_message(existing: dict, target: dict) -> bool:
    """Return True when two message payloads represent the same handoff summary."""
    existing_payload = _extract_handoff_summary_payload(existing)
    target_payload = _extract_handoff_summary_payload(target)
    if not existing_payload or not target_payload:
        return False
    return (
        existing_payload.get("session_id") == target_payload.get("session_id") and
        existing_payload.get("summary") == target_payload.get("summary") and
        existing_payload.get("channel") == target_payload.get("channel") and
        existing_payload.get("rounds") == target_payload.get("rounds") and
        existing_payload.get("fallback") == target_payload.get("fallback") and
        existing_payload.get("_handoff_summary_card") == target_payload.get("_handoff_summary_card")
    )


def _is_matching_handoff_summary_content(content: object, target_payload: dict | None) -> bool:
    """Return True if DB content JSON matches an expected handoff summary payload."""
    if target_payload is None:
        return False
    try:
        payload = json.loads(content or "")
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("session_id") is None:
        return False
    return (
        payload.get("_handoff_summary_card") is True and
        str(payload.get("session_id")) == str(target_payload.get("session_id")) and
        str(payload.get("summary", "")) == str(target_payload.get("summary", "")) and
        payload.get("channel") == target_payload.get("channel") and
        payload.get("rounds") == target_payload.get("rounds") and
        bool(payload.get("fallback")) == bool(target_payload.get("fallback"))
    )


def _persist_handoff_summary_locally(sid: str, message: dict) -> bool:
    """Persist a handoff summary marker into a local WebUI session file."""
    try:
        from app.domain.models import get_session

        s = get_session(sid)
    except KeyError:
        return False

    try:
        if s.messages and _is_matching_handoff_summary_message(s.messages[-1], message):
            return True
        s.messages.append(message)
        s.save()
        return True
    except Exception as e:
        logger.warning("Failed to persist handoff summary marker in local session %s: %s", sid, e)
        return False


def _persist_handoff_summary_to_state_db(sid: str, message: dict) -> bool:
    """Persist a handoff summary marker into CLI sessions state.db.

    This keeps summary cards available after hard-refresh for imported gateway
    sessions that are not in local session JSON yet.
    """
    import os

    try:
        import sqlite3
    except ImportError:
        return False

    try:
        from app.domain.profiles import get_active_hermes_home

        hermes_home = Path(get_active_hermes_home()).expanduser().resolve()
    except Exception:
        hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser().resolve()

    db_path = hermes_home / "state.db"
    if not db_path.exists():
        return False

    ts = message.get("timestamp", time.time())
    content = message.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    marker_payload = _extract_handoff_summary_payload(message)
    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            try:
                if marker_payload is not None:
                    cur = conn.execute(
                        "SELECT content FROM messages WHERE session_id = ? AND role = 'tool' "
                        "ORDER BY rowid DESC LIMIT 1",
                        (sid,),
                    )
                    row = cur.fetchone()
                    if row is not None and _is_matching_handoff_summary_content(row[0], marker_payload):
                        return True
            except Exception:
                # If tail-read fails, continue with a best-effort write.
                logger.debug("Unable to read tail handoff marker from state.db for %s", sid)

            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) "
                "VALUES (?, 'tool', ?, ?)",
                (sid, content, ts),
            )
            # Keep session row message_count/last-activity aligned with displayed
            # transcript length. session rows are optional in some test DBs, so
            # this update is best-effort.
            conn.execute(
                "UPDATE sessions SET message_count = COALESCE(message_count, 0) + 1 "
                "WHERE id = ?",
                (sid,),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to persist handoff summary marker in state.db for %s: %s", sid, e)
        return False


def _persist_handoff_summary(sid: str, summary: str, channel: str | None, rounds: int | None, fallback: bool = False) -> dict:
    """Persist a handoff summary marker across local/session backends."""
    marker = _build_handoff_summary_tool_message(sid, summary, channel, rounds, fallback)
    is_messaging_session = _is_messaging_session_id(sid)
    if is_messaging_session:
        _persist_handoff_summary_to_state_db(sid, marker)
        _persist_handoff_summary_locally(sid, marker)
        return marker
    persisted_local = _persist_handoff_summary_locally(sid, marker)
    if persisted_local:
        return marker
    return marker if _persist_handoff_summary_to_state_db(sid, marker) else marker


def _handle_handoff_summary(handler, body):
    """Generate an on-demand handoff summary for a gateway session.

    Request body::

        { "session_id": "...", "since": <unix_ts_or_iso> }

    Uses the session's configured model to produce a concise summary of
    recent conversation activity.  Returns the summary text so the caller
    can display it in a tool-card.
    """
    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))

    sid = str(body.get("session_id") or "").strip()
    if not sid:
        return bad(handler, "session_id is required")

    since = body.get("since")
    if since is not None:
        try:
            since = float(since)
        except (TypeError, ValueError):
            return bad(handler, "since must be a unix timestamp (number)")

    from app.domain.models import get_cli_session_messages, count_conversation_rounds, CONVERSATION_ROUND_THRESHOLD

    rounds = count_conversation_rounds(sid, since=since)
    if rounds < CONVERSATION_ROUND_THRESHOLD:
        return bad(handler, "Not enough conversation rounds to generate a summary.", 400)

    # Filter messages by ``since``.
    all_msgs = get_cli_session_messages(sid)
    if since is not None:
        import datetime as _dt
        filtered = []
        for m in all_msgs:
            ts_raw = m.get("timestamp")
            if ts_raw is None:
                continue
            try:
                if isinstance(ts_raw, (int, float)):
                    ts_val = float(ts_raw)
                else:
                    ts_val = _dt.datetime.fromisoformat(
                        str(ts_raw).replace("Z", "+00:00")
                    ).timestamp()
                if ts_val > since:
                    filtered.append(m)
            except Exception:
                pass
        msgs = filtered
    else:
        msgs = all_msgs

    # Cap to last 50 messages.
    msgs = msgs[-50:]

    if len(msgs) < 2:
        return bad(handler, "Not enough messages to summarize.", 400)

    def _extract_handoff_text(raw_content):
        if isinstance(raw_content, list):
            return " ".join(
                str(p.get("text") or p.get("content") or "")
                for p in raw_content
                if isinstance(p, dict)
            ).strip()
        return str(raw_content or "").strip()

    def _contains_chinese(text):
        return any("\u4e00" <= ch <= "\u9fff" for ch in str(text))

    transcript_is_chinese = any(
        _contains_chinese(_extract_handoff_text(m.get("content")))
        for m in msgs
    )
    # Build a lightweight conversation transcript for the LLM.
    lines = []
    for m in msgs:
        role = m.get("role", "")
        content = _extract_handoff_text(m.get("content"))
        content = str(content or "").strip()[:1000]
        if role in ("user", "assistant") and content:
            lines.append(content)
    transcript = "\n".join(lines)

    def _fallback_handoff_summary(items):
        """Return a deterministic summary when LLM summary generation is unavailable."""
        user_points = []
        assistant_points = []

        def _summarize_snippet(raw_text, max_len=78):
            text = " ".join(str(raw_text or "").split()).strip()
            if not text:
                return ""
            if len(text) <= max_len:
                return text
            return text[: max_len - 1].rstrip() + "…"

        for m in items:
            role = m.get("role", "")
            content = _summarize_snippet(_extract_handoff_text(m.get("content")), 82)
            if role in ("user", "assistant") and content:
                if role == "user":
                    user_points.append(content)
                else:
                    assistant_points.append(content)
        if not user_points and not assistant_points:
            return (
                "近期可读文本不足，无法生成更完整的交接摘要，请补充一条消息后重试。"
                if transcript_is_chinese
                else "Not enough readable text to create a useful handoff summary; please send one more message and retry."
            )

        if transcript_is_chinese:
            bullets = []
            if user_points:
                bullets.append(f"- 你刚讨论了：{user_points[-1]}。")
            if assistant_points:
                bullets.append(f"- 助手已回复：{assistant_points[-1]}。")
            if len(user_points) + len(assistant_points) >= 2:
                bullets.append("- 当前对话存在尚未确认的后续动作。")
            else:
                bullets.append("- 当前信息偏少，建议补充关键点后再切换。")
            return "\n".join(bullets)

        bullets = []
        if user_points:
            bullets.append(f"- You asked: {user_points[-1]}.")
        if assistant_points:
            bullets.append(f"- The assistant responded: {assistant_points[-1]}.")
        if len(user_points) + len(assistant_points) >= 2:
            bullets.append("- There is pending context to continue next.")
        else:
            bullets.append("- The conversation is still short; add one more turn before summarizing.")
        return "\n".join(bullets)

    def _summary_output_incomplete(text):
        """Best-effort guard for truncated summaries when LLM signals are unavailable."""
        if not isinstance(text, str):
            text = str(text or "")
        text = text.strip()
        if not text:
            return True
        if text.endswith("...") or text.endswith("…"):
            return True
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return True
        last_line = lines[-1]
        if re.search(r"[。！？；!?.；]$", last_line):
            return False
        if len(last_line) >= 56 and not re.search(r"\b(and|or|so|then|because|if|when|but|so|as)\b$", last_line, re.IGNORECASE):
            return True
        return bool(re.search(r"\b(and|or|but|so|because|if|when)$", last_line, re.IGNORECASE))

    def _agent_summary_incomplete(summary_result):
        if not isinstance(summary_result, dict):
            return True
        reason = (summary_result.get("finish_reason") or "").strip().lower()
        if reason == "length":
            return True
        stop_reason = (summary_result.get("stop_reason") or "").strip().lower()
        if stop_reason in {"max_tokens", "length"}:
            return True
        return _summary_output_incomplete(summary_result.get("text", ""))

    def _resolve_handoff_channel_label():
        channel_label = None
        try:
            from app.domain.models import get_session as _get_session, get_cli_sessions

            session_meta = _get_session(sid)
            channel_label = (
                session_meta.source_label
                or session_meta.raw_source
                or session_meta.source_tag
                or session_meta.session_source
            )
            if not channel_label:
                for candidate in get_cli_sessions():
                    if candidate.get("session_id") == sid:
                        channel_label = (
                            candidate.get("source_label")
                            or candidate.get("raw_source")
                            or candidate.get("source_tag")
                            or candidate.get("source")
                        )
                        break
        except Exception:
            pass
        return channel_label

    def _agent_text_completion(agent, system_prompt, user_text, max_tokens=700):
        """Use the current Hermes Agent transport without mutating conversation history."""
        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        result = {
            "text": "",
            "finish_reason": None,
            "stop_reason": None,
            "incomplete": True,
        }
        disabled_reasoning = {"enabled": False}
        previous_reasoning = getattr(agent, "reasoning_config", None)
        try:
            agent.reasoning_config = disabled_reasoning
            if getattr(agent, "api_mode", "") == "codex_responses":
                codex_kwargs = agent._build_api_kwargs(api_messages)
                codex_kwargs.pop("tools", None)
                codex_kwargs["max_output_tokens"] = max_tokens
                resp = agent._run_codex_stream(codex_kwargs)
                assistant_message, _ = agent._normalize_codex_response(resp)
                result["text"] = str((assistant_message.content or "") if assistant_message else "").strip()
                result["incomplete"] = _summary_output_incomplete(result["text"])
                return result

            if getattr(agent, "api_mode", "") == "anthropic_messages":
                from agent.anthropic_adapter import build_anthropic_kwargs, normalize_anthropic_response

                ant_kwargs = build_anthropic_kwargs(
                    model=agent.model,
                    messages=api_messages,
                    tools=None,
                    max_tokens=max_tokens,
                    reasoning_config=disabled_reasoning,
                    is_oauth=getattr(agent, "_is_anthropic_oauth", False),
                    preserve_dots=agent._anthropic_preserve_dots(),
                    base_url=getattr(agent, "_anthropic_base_url", None),
                )
                resp = agent._anthropic_messages_create(ant_kwargs)
                assistant_message, _ = normalize_anthropic_response(
                    resp,
                    strip_tool_prefix=getattr(agent, "_is_anthropic_oauth", False),
                )
                result["text"] = str((assistant_message.content or "") if assistant_message else "").strip()
                result["incomplete"] = _summary_output_incomplete(result["text"])
                return result

            api_kwargs = agent._build_api_kwargs(api_messages)
            api_kwargs.pop("tools", None)
            api_kwargs["temperature"] = 0.2
            api_kwargs["timeout"] = 30.0
            if "max_completion_tokens" in api_kwargs:
                api_kwargs["max_completion_tokens"] = max_tokens
            else:
                api_kwargs["max_tokens"] = max_tokens
            resp = agent._ensure_primary_openai_client(reason="handoff_summary").chat.completions.create(
                **api_kwargs,
            )
            choice = (getattr(resp, "choices", None) or [None])[0]
            msg = getattr(choice, "message", None) if choice is not None else None
            result["text"] = str(getattr(msg, "content", "") or "").strip()
            result["finish_reason"] = getattr(choice, "finish_reason", None)
            result["stop_reason"] = getattr(choice, "stop_reason", None)
            result["incomplete"] = _agent_summary_incomplete(result)
            return result
        finally:
            agent.reasoning_config = previous_reasoning

        # Call LLM for summary.
    try:
        import app.domain.config as _cfg
        from app.domain.oauth import resolve_runtime_provider_with_anthropic_env_lock
        import hermes_cli.runtime_provider as _runtime_provider
        import run_agent as _run_agent

        # Try to resolve model from an existing session, fall back to default.
        resolved_model = None
        resolved_provider = None
        resolved_base_url = None
        try:
            from app.domain.models import get_session
            s_obj = get_session(sid)
            resolved_model = getattr(s_obj, "model", None)
        except Exception:
            pass

        resolved_model, resolved_provider, resolved_base_url = _cfg.resolve_model_provider(resolved_model)

        resolved_api_key = None
        try:
            _rt = resolve_runtime_provider_with_anthropic_env_lock(
                _runtime_provider.resolve_runtime_provider,
                requested=resolved_provider,
            )
            resolved_api_key = _rt.get("api_key")
            if not resolved_provider:
                resolved_provider = _rt.get("provider")
            if not resolved_base_url:
                resolved_base_url = _rt.get("base_url")
        except Exception as _e:
            logger.warning("resolve_runtime_provider failed for handoff summary: %s", _e)

        if isinstance(resolved_provider, str) and resolved_provider.startswith("custom:"):
            _cp_key, _cp_base = _cfg.resolve_custom_provider_connection(resolved_provider)
            if not resolved_api_key and _cp_key:
                resolved_api_key = _cp_key
            if not resolved_base_url and _cp_base:
                resolved_base_url = _cp_base

        if not resolved_api_key:
            summary_text = _fallback_handoff_summary(msgs)
            try:
                _persist_handoff_summary(
                    sid,
                    summary_text,
                    _resolve_handoff_channel_label(),
                    rounds,
                    fallback=True,
                )
            except Exception:
                pass
            return j(handler, {
                "ok": True,
                "summary": summary_text,
                "message_count": len(msgs),
                "rounds": rounds,
                "fallback": True,
            })

        agent = _run_agent.AIAgent(
            model=resolved_model,
            provider=resolved_provider,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            platform="webui",
            quiet_mode=True,
            enabled_toolsets=[],
            session_id=sid,
        )

        summary_system_prompt = (
            "You are summarizing an external-channel conversation so a Web UI reader "
            "can quickly catch up after switching contexts.\n\n"
            "Only use the latest messages, and never copy raw transcript lines.\n"
            "Do not output role labels (no “你:” / “assistant:” / “user:” / “assistant”).\n"
            "Use direct 2–5 bullet points in the conversation language.\n"
            "English: speak using “you”.\n"
            "中文: 使用“你”。\n\n"
            "Focus on:\n"
            "- Unfinished tasks or action items\n"
            "- Pending questions that need replies\n"
            "- Key decisions made\n"
            "- Open disagreements or TBD items\n\n"
            "If the conversation is purely casual with no actionable items, "
            "say so in one sentence."
        )
        summary_user_text = f"Conversation transcript:\n{transcript}"

        try:
            first_pass = _agent_text_completion(
                agent,
                summary_system_prompt,
                summary_user_text,
                max_tokens=700,
            )
            summary_text = first_pass.get("text") if isinstance(first_pass, dict) else ""
            if _agent_summary_incomplete(first_pass):
                second_pass = _agent_text_completion(
                    agent,
                    summary_system_prompt,
                    summary_user_text,
                    max_tokens=1400,
                )
                summary_text = second_pass.get("text") if isinstance(second_pass, dict) else ""
                if _agent_summary_incomplete(second_pass):
                    summary_text = _fallback_handoff_summary(msgs)
                    fallback = True
                else:
                    fallback = False
            else:
                fallback = False
        finally:
            try:
                agent.release_clients()
            except Exception:
                pass
        if not summary_text:
            summary_text = _fallback_handoff_summary(msgs)
            fallback = True
        elif _summary_output_incomplete(summary_text):
            if not fallback:
                fallback = True

        channel_label = _resolve_handoff_channel_label()
        _persist_handoff_summary(
            sid,
            summary_text,
            channel_label,
            rounds,
            fallback=fallback,
        )

        return j(handler, {
            "ok": True,
            "summary": summary_text,
            "message_count": len(msgs),
            "rounds": rounds,
            "fallback": fallback,
        })
    except Exception as e:
        logger.warning("Handoff summary generation failed: %s", e)
        summary_text = _fallback_handoff_summary(msgs)
        try:
            _persist_handoff_summary(
                sid,
                summary_text,
                _resolve_handoff_channel_label(),
                rounds,
                fallback=True,
            )
        except Exception:
            pass
        return j(handler, {
            "ok": True,
            "summary": summary_text,
            "message_count": len(msgs),
            "rounds": rounds,
            "fallback": True,
            "warning": f"Summary generation used local fallback: {_sanitize_error(e)}",
        })


def _handle_skill_save(handler, body):
    try:
        require(body, "name", "content")
    except ValueError as e:
        return bad(handler, str(e))
    skill_name = body["name"].strip().lower().replace(" ", "-")
    if not skill_name or "/" in skill_name or ".." in skill_name:
        return bad(handler, "Invalid skill name")
    category = body.get("category", "").strip()
    if category and ("/" in category or ".." in category):
        return bad(handler, "Invalid category")
    skills_dir = _active_skills_dir()
    from app.core.security import get_current_user_from_legacy_handler
    from app.domain.skill_ownership import skill_is_readonly_for_user

    user = get_current_user_from_legacy_handler(handler)
    search_dirs = _active_skill_search_dirs(skills_dir)
    _skill_dir, existing_md = _find_skill_in_dirs(skill_name, search_dirs)
    if existing_md and skill_is_readonly_for_user(skill_name, skills_dir, user):
        return bad(
            handler,
            "Default skills cannot be edited. Create a new skill instead.",
            403,
        )

    if category:
        skill_dir = skills_dir / category / skill_name
    else:
        skill_dir = skills_dir / skill_name
    # Validate resolved path stays within the active profile skills dir.
    try:
        skill_dir.resolve().relative_to(skills_dir.resolve())
    except ValueError:
        return bad(handler, "Invalid skill path")
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(body["content"], encoding="utf-8")
    return j(handler, {"ok": True, "name": skill_name, "path": str(skill_file)})


def _handle_skill_delete(handler, body):
    try:
        require(body, "name")
    except ValueError as e:
        return bad(handler, str(e))
    import shutil

    skill_name = str(body["name"]).strip().lower().replace(" ", "-")
    if not skill_name or "/" in skill_name or ".." in skill_name:
        return bad(handler, "Invalid skill name")
    skills_dir = _active_skills_dir()
    from app.core.security import get_current_user_from_legacy_handler
    from app.domain.skill_ownership import skill_is_readonly_for_user

    user = get_current_user_from_legacy_handler(handler)
    if skill_is_readonly_for_user(skill_name, skills_dir, user):
        return bad(handler, "Default skills cannot be deleted.", 403)

    install_paths = _skill_install_paths_for_name(skill_name, skills_dir)
    if not install_paths:
        return j(handler, {"ok": True, "name": body["name"], "already_deleted": True})

    try:
        _remove_skill_installation(install_paths, skills_dir)
    except OSError as exc:
        logger.warning(
            "Failed to delete skill %s (%s): %s",
            skill_name,
            ", ".join(str(p) for p in install_paths),
            exc,
        )
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) == 13:
            return bad(
                handler,
                "Cannot delete skill files: permission denied on the external install "
                "directory (~/.agents/skills). Restart the WebUI container to repair "
                "ownership, or run: chown -R $(id -u):$(id -g) ~/.agents/skills",
                500,
            )
        return bad(handler, f"Failed to delete skill: {exc}", 500)

    search_dirs = _active_skill_search_dirs(skills_dir)
    remaining_dir, remaining_md = _find_skill_in_dirs(skill_name, search_dirs)
    if remaining_md and remaining_dir:
        return bad(
            handler,
            "Skill files are still present after delete. Remove any remaining install paths manually.",
            500,
        )

    return j(handler, {"ok": True, "name": body["name"]})


def _normalize_names_list(names) -> list[str]:
    """Normalize a config value (None/str/list) into a deduplicated str list."""
    if names is None:
        return []
    if isinstance(names, str):
        names = [names]
    elif not isinstance(names, list):
        names = list(names) if names else []
    return list(dict.fromkeys(str(d).strip() for d in names if str(d).strip()))


def _toggle_name_in_list(names, name: str, enabled: bool) -> list[str]:
    """Add or remove *name* from *names*, returning a new list."""
    names = _normalize_names_list(names)
    if enabled:
        return [d for d in names if d != name]
    if name not in names:
        names.append(name)
    return names


def _handle_skill_toggle(handler, body):
    """Toggle a skill's enabled/disabled state in the active profile's config.yaml.

    Writes through to ``skills.platform_disabled.webui`` when that key exists
    so the toggle takes effect for WebUI sessions (the agent's
    ``get_disabled_skill_names`` checks platform-specific lists first when
    ``HERMES_SESSION_PLATFORM`` is set).
    """
    try:
        require(body, "name", "enabled")
    except ValueError as e:
        return bad(handler, str(e))

    name = body["name"].strip()
    enabled = bool(body["enabled"])

    # Validate the skill exists in the filesystem
    skills_dir = _active_skills_dir()
    search_dirs = _active_skill_search_dirs(skills_dir)
    skill_dir, skill_md = _find_skill_in_dirs(name, search_dirs)
    if not skill_md:
        return bad(handler, f"Skill '{name}' not found", 404)

    config_path = _get_config_path()
    with _cfg_lock:
        cfg = _load_yaml_config_file(config_path)

        # Ensure skills section exists as a dict
        if "skills" not in cfg or not isinstance(cfg["skills"], dict):
            cfg["skills"] = {}
        skills_cfg = cfg["skills"]

        # Always update the global disabled list
        skills_cfg["disabled"] = _toggle_name_in_list(
            skills_cfg.get("disabled"), name, enabled
        )

        # Write-through to platform_disabled.webui if it exists so that the
        # toggle takes effect for WebUI sessions (the agent checks the
        # platform-specific list first when HERMES_SESSION_PLATFORM=webui).
        platform_disabled = skills_cfg.get("platform_disabled")
        if isinstance(platform_disabled, dict) and "webui" in platform_disabled:
            platform_disabled["webui"] = _toggle_name_in_list(
                platform_disabled["webui"], name, enabled
            )

        cfg["skills"] = skills_cfg
        _save_yaml_config_file(config_path, cfg)

    reload_config()  # outside with block — reload_config() acquires the lock itself

    return j(handler, {"ok": True, "name": name, "enabled": enabled})


def _handle_skill_install(handler, body):
    """Install a skill from the skills hub (browse.sh, GitHub, URL, etc.)."""
    try:
        require(body, "identifier")
    except ValueError as e:
        return bad(handler, str(e))

    identifier = str(body.get("identifier", "") or "").strip()
    if not identifier:
        return bad(handler, "identifier is required")
    category = str(body.get("category", "") or "").strip()
    force = bool(body.get("force", False))

    from app.domain.skill_hub_github_fallback import (
        install_repo_via_npx_skills,
        normalize_skills_sh_identifier,
        relocate_stranded_npx_skills,
    )
    from app.domain.skill_hub_search import is_repo_hub_query

    repo_slug = normalize_skills_sh_identifier(identifier)
    relocate_stranded_npx_skills()
    if is_repo_hub_query(repo_slug):
        from app.domain.skill_hub_install_message import summarize_skill_install_message

        result = install_repo_via_npx_skills(repo_slug)
        raw_message = str(result.get("message") or "")
        return j(
            handler,
            {
                "ok": bool(result.get("ok")),
                "identifier": identifier,
                "message": summarize_skill_install_message(
                    raw_message,
                    repo=repo_slug,
                    ok=bool(result.get("ok")),
                )
                or "Repo install finished.",
                "fallback": "npx-skills-repo",
            },
        )

    try:
        import io

        from rich.console import Console

        from hermes_cli.skills_hub import do_install

        buffer = io.StringIO()
        console = Console(file=buffer, width=120, highlight=False)
        do_install(
            identifier,
            category=category,
            force=force,
            console=console,
            skip_confirm=True,
            invalidate_cache=True,
        )
        message = buffer.getvalue().strip()
        lowered = message.lower()
        failed = (
            "could not fetch" in lowered
            or lowered.startswith("error:")
            or "\nerror:" in lowered
        )
        from app.domain.skill_hub_github_fallback import (
            npx_skills_install_args,
        )
        from app.domain.skill_hub_install_message import summarize_skill_install_message

        install_args = npx_skills_install_args(identifier)
        repo_hint, skill_hint = install_args if install_args else ("", "")

        if failed and ("rate limit" in lowered or "could not fetch" in lowered):
            from app.domain.skill_hub_github_fallback import install_via_npx_skills

            if normalize_skills_sh_identifier(identifier):
                fallback = install_via_npx_skills(identifier)
                if fallback.get("ok"):
                    fallback_message = summarize_skill_install_message(
                        str(fallback.get("message") or ""),
                        repo=str(fallback.get("repo") or repo_hint),
                        skill=str(fallback.get("skill") or skill_hint),
                        ok=True,
                    )
                    return j(
                        handler,
                        {
                            "ok": True,
                            "identifier": identifier,
                            "message": fallback_message or "Skill installed.",
                            "fallback": "npx-skills",
                        },
                    )
        return j(
            handler,
            {
                "ok": not failed,
                "identifier": identifier,
                "message": summarize_skill_install_message(
                    message,
                    repo=repo_hint,
                    skill=skill_hint,
                    ok=not failed,
                )
                or "Skill install finished.",
            },
        )
    except ImportError:
        return bad(handler, "skills hub unavailable", 503)
    except Exception as e:
        logger.warning("skill install failed for %s: %s", identifier, e, exc_info=True)
        return bad(handler, _sanitize_error(e), 500)


def _handle_memory_write(handler, body):
    from app.core.security import (
        AgentSoulAccessError,
        ensure_agent_soul_access,
        get_current_user_from_legacy_handler,
    )

    try:
        require(body, "section", "content")
    except ValueError as e:
        return bad(handler, str(e))
    section = body["section"]
    if section == "soul":
        try:
            ensure_agent_soul_access(get_current_user_from_legacy_handler(handler))
        except AgentSoulAccessError as exc:
            return bad(handler, str(exc), 403)
    try:
        from app.domain.profiles import get_active_hermes_home

        home = get_active_hermes_home()
        mem_dir = home / "memories"
    except ImportError:
        home = Path.home() / ".hermes"
        mem_dir = home / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    if section == "memory":
        target = mem_dir / "MEMORY.md"
    elif section == "user":
        target = mem_dir / "USER.md"
    elif section == "soul":
        target = home / "SOUL.md"
    else:
        return bad(handler, 'section must be "memory", "user", or "soul"')
    target.write_text(body["content"], encoding="utf-8")
    return j(handler, {"ok": True, "section": section, "path": str(target)})


def _normalize_message_for_import_refresh(message: object) -> object:
    """Normalize message payloads for import refresh prefix checks.

    The strict dict comparison previously failed when existing messages held
    integer timestamps while refreshed messages held floating-point timestamps.
    Strip timing keys before comparison so we can safely treat semantic
    prefixes as equivalent.
    """
    if not isinstance(message, dict):
        return message
    normalized = dict(message)
    normalized.pop("timestamp", None)
    normalized.pop("_ts", None)
    return normalized


def _message_has_cli_tool_metadata(message: object) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("role") == "assistant" and message.get("tool_calls"):
        return True
    if message.get("role") == "tool" and (message.get("tool_call_id") or message.get("tool_name") or message.get("name")):
        return True
    return False


def _strip_cli_tool_metadata_for_refresh(message: object) -> object:
    if not isinstance(message, dict):
        return _normalize_message_for_import_refresh(message)
    normalized = _normalize_message_for_import_refresh(message)
    if not isinstance(normalized, dict):
        return normalized
    for key in ("tool_calls", "tool_call_id", "tool_name", "name"):
        normalized.pop(key, None)
    return normalized


def _is_cli_tool_metadata_enrichment(existing_messages: list, fresh_messages: list) -> bool:
    """Return True when fresh messages only add CLI tool metadata.

    Older imports from get_cli_session_messages() persisted assistant/tool rows
    without tool_calls, tool_call_id, or tool_name. After #1772 the refreshed
    transcript can have the same length but richer metadata, so re-imports must
    rebuild the stored sidecar even without a new row.
    """
    if not isinstance(existing_messages, list) or not isinstance(fresh_messages, list):
        return False
    if len(existing_messages) != len(fresh_messages):
        return False
    if any(_message_has_cli_tool_metadata(m) for m in existing_messages):
        return False
    if not any(_message_has_cli_tool_metadata(m) for m in fresh_messages):
        return False
    for idx, existing_message in enumerate(existing_messages):
        if _strip_cli_tool_metadata_for_refresh(existing_message) != _strip_cli_tool_metadata_for_refresh(fresh_messages[idx]):
            return False
    return True


def _is_messages_refresh_prefix_match(existing_messages: list, fresh_messages: list) -> bool:
    """Return True when existing_messages is a prefix of fresh_messages by value.

    This is a semantic comparison intended for import refresh, not deep
    structural equality. It intentionally ignores timing fields that may differ
    in type/precision between storage layers.
    """
    if not isinstance(existing_messages, list) or not isinstance(fresh_messages, list):
        return False
    if len(existing_messages) > len(fresh_messages):
        return False
    for idx, existing_message in enumerate(existing_messages):
        fresh_message = fresh_messages[idx]
        if _normalize_message_for_import_refresh(existing_message) != _normalize_message_for_import_refresh(fresh_message):
            return False
    return True


def _handle_session_import_cli(handler, body):
    """Import a single CLI session into the WebUI store."""
    try:
        require(body, "session_id")
    except ValueError as e:
        return bad(handler, str(e))

    sid = str(body["session_id"])

    # Check if already imported — refresh messages from CLI store if new ones arrived
    existing = Session.load(sid)
    if existing:
        fresh_msgs = get_cli_session_messages(sid)
        changed = False
        cli_meta = None
        for cs in list(get_cli_sessions()):
            if cs["session_id"] == sid:
                cli_meta = cs
                break
        if fresh_msgs and len(fresh_msgs) > len(existing.messages):
            # Prefix-equality guard: only extend if existing messages are a prefix of
            # the fresh CLI messages. Prevents silently dropping WebUI-added messages
            # on hybrid sessions (user sent messages via WebUI while CLI continued).
            if _is_messages_refresh_prefix_match(existing.messages, fresh_msgs):
                existing.messages = fresh_msgs
                changed = True
        elif fresh_msgs and _is_cli_tool_metadata_enrichment(existing.messages, fresh_msgs):
            # Same row count, richer payload: rebuild sidecars imported before
            # CLI tool metadata was preserved (#1772).
            existing.messages = fresh_msgs
            changed = True
        if cli_meta:
            updates = {
                "is_cli_session": True,
                "source_tag": existing.source_tag or cli_meta.get("source_tag"),
                "raw_source": existing.raw_source or cli_meta.get("raw_source") or cli_meta.get("source_tag"),
                "session_source": existing.session_source or cli_meta.get("session_source"),
                "source_label": existing.source_label or cli_meta.get("source_label"),
                "parent_session_id": existing.parent_session_id or cli_meta.get("parent_session_id"),
            }
            for attr, value in updates.items():
                if getattr(existing, attr, None) != value:
                    setattr(existing, attr, value)
                    changed = True
        if changed:
            existing.save(touch_updated_at=False)
            publish_session_list_changed("session_import_cli")
        return j(
            handler,
            {
                "session": existing.compact()
                | {
                    "messages": existing.messages,
                    "is_cli_session": True,
                    "read_only": bool((cli_meta or {}).get("read_only")),
                },
                "imported": False,
            },
        )

    # Fetch messages from CLI store
    msgs = get_cli_session_messages(sid)
    if not msgs:
        return bad(handler, "Session not found in CLI store", 404)

    # Get profile, model, timestamps, and title from CLI session metadata
    profile = None
    created_at = None
    updated_at = None
    cli_title = None
    cli_source_tag = None
    model = "unknown"
    cli_raw_source = None
    cli_session_source = None
    cli_source_label = None
    cli_user_id = None
    cli_chat_id = None
    cli_chat_type = None
    cli_thread_id = None
    cli_session_key = None
    cli_platform = None
    cli_parent_session_id = None
    cli_read_only = False
    for cs in get_cli_sessions():
        if cs["session_id"] == sid:
            profile = cs.get("profile")
            model = cs.get("model", "unknown")
            created_at = cs.get("created_at")
            updated_at = cs.get("updated_at")
            cli_title = cs.get("title")
            cli_source_tag = cs.get("source_tag")
            cli_raw_source = cs.get("raw_source")
            cli_session_source = cs.get("session_source")
            cli_source_label = cs.get("source_label")
            cli_user_id = cs.get("user_id")
            cli_chat_id = cs.get("chat_id")
            cli_chat_type = cs.get("chat_type")
            cli_thread_id = cs.get("thread_id")
            cli_session_key = cs.get("session_key")
            cli_platform = cs.get("platform")
            cli_parent_session_id = cs.get("parent_session_id")
            cli_read_only = bool(cs.get("read_only"))
            break

    # Use the CLI session title if available (e.g., cron job name), otherwise derive from messages
    title = cli_title or title_from(msgs, "CLI Session")

    # Auto-assign cron sessions to the dedicated "Cron Jobs" project (#1079)
    cron_project_id = None
    if is_cron_session(sid, cli_source_tag):
        cron_project_id = ensure_cron_project()

    if cli_read_only:
        session_payload = {
            "session_id": sid,
            "title": title,
            "workspace": str(get_last_workspace()),
            "model": model,
            "message_count": len(msgs),
            "created_at": created_at,
            "updated_at": updated_at,
            "last_message_at": updated_at or created_at,
            "pinned": False,
            "archived": False,
            "project_id": None,
            "profile": profile,
            "is_cli_session": True,
            "source_tag": cli_source_tag,
            "raw_source": cli_raw_source or cli_source_tag,
            "session_source": cli_session_source,
            "source_label": cli_source_label,
            "parent_session_id": cli_parent_session_id,
            "read_only": True,
            "messages": msgs,
            "tool_calls": [],
        }
        return j(handler, {"session": session_payload, "imported": False})

    s = import_cli_session(
        sid,
        title,
        msgs,
        model,
        profile=profile,
        created_at=created_at,
        updated_at=updated_at,
        parent_session_id=cli_parent_session_id,
    )
    if cron_project_id:
        s.project_id = cron_project_id
    s.is_cli_session = True
    s.source_tag = cli_source_tag
    s.raw_source = cli_raw_source or cli_source_tag
    s.session_source = cli_session_source
    s.source_label = cli_source_label
    s.user_id = cli_user_id
    s.chat_id = cli_chat_id
    s.chat_type = cli_chat_type
    s.thread_id = cli_thread_id
    s.session_key = cli_session_key
    s.platform = cli_platform
    s._cli_origin = sid
    s.save(touch_updated_at=False)
    publish_session_list_changed("session_import_cli")
    return j(
        handler,
        {
            "session": s.compact()
            | {
                "messages": msgs,
                "is_cli_session": True,
            },
            "imported": True,
        },
    )


def _handle_session_import(handler, body):
    """Import a session from a JSON export. Creates a new session with a new ID."""
    if not body or not isinstance(body, dict):
        return bad(handler, "Request body must be a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list):
        return bad(handler, 'JSON must contain a "messages" array')
    title = body.get("title", "Imported session")
    try:
        workspace = str(resolve_trusted_workspace(body.get("workspace", str(DEFAULT_WORKSPACE))))
    except (TypeError, ValueError) as e:
        return bad(handler, str(e))
    model = body.get("model", DEFAULT_MODEL)
    s = Session(
        title=title,
        workspace=workspace,
        model=model,
        messages=messages,
        tool_calls=body.get("tool_calls", []),
    )
    s.pinned = body.get("pinned", False)
    with LOCK:
        SESSIONS[s.session_id] = s
        SESSIONS.move_to_end(s.session_id)
        while len(SESSIONS) > SESSIONS_MAX:
            SESSIONS.popitem(last=False)
    s.save()
    publish_session_list_changed("session_import")
    return j(handler, {"ok": True, "session": s.compact() | {"messages": s.messages}})


# ── MCP Server helpers ──
from app.domain.config import get_config, _save_yaml_config_file, _get_config_path, reload_config, _load_yaml_config_file


def _resolve_mcp_profile_name(raw: str) -> str:
    """Validate a profile name for profile-scoped MCP config access."""
    from app.domain.profiles import _home_for_profile_name, _is_root_profile, _validate_profile_name

    name = (raw or '').strip()
    if not name:
        raise ValueError("profile is required")
    if _is_root_profile(name):
        home = _home_for_profile_name(name)
    else:
        _validate_profile_name(name)
        home = _home_for_profile_name(name)
    if not home.is_dir():
        raise ValueError(f"Profile '{name}' not found")
    return name


def _mcp_profile_from_request(parsed=None, body=None) -> str:
    """Return optional profile query/body value (empty string = active profile)."""
    raw = ""
    if parsed is not None:
        qs = parse_qs(parsed.query or "")
        raw = str(qs.get("profile", [""])[0] or "").strip()
    if not raw and body:
        raw = str(body.get("profile") or "").strip()
    return raw


def _mcp_config_bundle(profile_query: str = ""):
    """Load config.yaml for MCP operations (active profile or explicit profile)."""
    from app.domain.profiles import _home_for_profile_name, get_active_profile_name

    if profile_query:
        profile_name = _resolve_mcp_profile_name(profile_query)
        home = _home_for_profile_name(profile_name)
        path = home / "config.yaml"
        cfg = _load_yaml_config_file(path)
        if not isinstance(cfg, dict):
            cfg = {}
        return cfg, path, profile_name
    profile_name = get_active_profile_name()
    return get_config(), _get_config_path(), profile_name


def _persist_mcp_config(cfg: dict, path: Path, profile_name: str) -> None:
    _save_yaml_config_file(path, cfg)
    from app.domain.profiles import get_active_profile_name

    if profile_name == get_active_profile_name():
        reload_config()

def _mask_secrets(obj):
    """Mask sensitive values in env vars and headers."""
    if not isinstance(obj, dict):
        return obj
    sensitive = ("auth", "token", "key", "secret", "password", "credential")
    masked = {}
    for k, v in obj.items():
        if isinstance(v, str) and any(s in k.lower() for s in sensitive):
            masked[k] = "••••••"
        elif isinstance(v, dict):
            masked[k] = _mask_secrets(v)
        else:
            masked[k] = v
    return masked


_MCP_NON_SECRET_HEADERS = frozenset({
    "accept",
    "content-type",
    "user-agent",
    "mcp-protocol-version",
})


def _mask_http_headers(headers):
    """Mask HTTP header values except known non-secret transport headers."""
    if not isinstance(headers, dict):
        return headers
    masked = {}
    for k, v in headers.items():
        if not isinstance(k, str):
            continue
        if k.lower() in _MCP_NON_SECRET_HEADERS:
            masked[k] = v
        elif isinstance(v, str) and v.strip():
            masked[k] = "••••••"
        else:
            masked[k] = v
    return masked


def _mcp_auth_summary(cfg):
    """Return safe auth metadata for MCP server inventory rows."""
    if not isinstance(cfg, dict):
        return {"auth_configured": False, "auth_type": "none"}

    auth = (cfg.get("auth") or "").lower().strip()
    if auth == "oauth":
        return {"auth_configured": True, "auth_type": "oauth", "auth": "oauth"}

    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    if not headers:
        return {"auth_configured": False, "auth_type": "none"}

    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.lower() == "authorization":
            if value.lower().startswith("bearer "):
                return {
                    "auth_configured": True,
                    "auth_type": "bearer",
                    "auth_header_name": key,
                }
            if value.strip():
                return {
                    "auth_configured": True,
                    "auth_type": "custom",
                    "auth_header_name": key,
                }

    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.lower() in _MCP_NON_SECRET_HEADERS:
            continue
        if value.strip():
            return {
                "auth_configured": True,
                "auth_type": "api_key",
                "auth_header_name": key,
            }

    return {"auth_configured": False, "auth_type": "none"}


def _parse_mcp_enabled(value) -> bool:
    """Parse Hermes MCP ``enabled`` values without raising on bad config."""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return True


def _mcp_runtime_status_by_name() -> dict[str, dict]:
    """Return already-known MCP runtime status without starting servers.

    ``tools.mcp_tool.get_mcp_status()`` only reads the existing MCP registry and
    configuration; it does not probe or spawn MCP subprocesses. If Hermes Agent
    is unavailable, fall back to an empty map so the API remains safe.
    """
    try:
        from tools.mcp_tool import get_mcp_status
        statuses = get_mcp_status()
    except Exception:
        return {}
    if not isinstance(statuses, list):
        return {}
    return {
        str(entry.get("name")): entry
        for entry in statuses
        if isinstance(entry, dict) and entry.get("name")
    }


_MCP_PROFILE_CONNECT_ERRORS: dict[str, dict[str, str]] = {}


def _mcp_obvious_connect_error(name: str, cfg, connected: bool) -> str | None:
    """Return an immediate connect error (e.g. missing executable)."""
    if connected or not isinstance(cfg, dict):
        return None
    if not _parse_mcp_enabled(cfg.get("enabled", True)):
        return None
    command = cfg.get("command")
    if not command or cfg.get("url"):
        return None
    executable = str(command).strip()
    if not executable or shutil.which(executable):
        return None
    hint = (
        f"missing executable '{executable}' "
        "(install it or set command to an absolute path)"
    )
    if os.path.basename(executable) in {"npx", "npm", "node"}:
        hint += "; ensure Node.js is installed and PATH includes its bin directory"
    return hint


def _mcp_connect_errors_for_profile(
    profile_name: str,
    servers_cfg: dict,
    runtime_map: dict[str, dict],
    *,
    after_discover: bool = False,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not isinstance(servers_cfg, dict):
        return errors
    for name, scfg in servers_cfg.items():
        runtime = runtime_map.get(str(name), {})
        connected = bool(runtime.get("connected")) if isinstance(runtime, dict) else False
        err = _mcp_obvious_connect_error(str(name), scfg, connected)
        if not err and after_discover and isinstance(scfg, dict):
            if _parse_mcp_enabled(scfg.get("enabled", True)) and not connected:
                command = scfg.get("command")
                url = scfg.get("url")
                if command:
                    err = f"Could not connect to MCP server '{name}' (command={command})"
                elif url:
                    err = f"Could not connect to MCP server '{name}' at {str(url).strip()}"
                else:
                    err = f"Could not connect to MCP server '{name}'"
        if err:
            errors[str(name)] = err
    if after_discover:
        if errors:
            _MCP_PROFILE_CONNECT_ERRORS[profile_name] = errors
        else:
            _MCP_PROFILE_CONNECT_ERRORS.pop(profile_name, None)
    return errors


def _mcp_servers_from_default_profile() -> set[str]:
    """Return MCP server names defined on the default/root profile."""
    from app.domain.profiles import _default_profile_home, _load_config_yaml

    source_cfg = _load_config_yaml(_default_profile_home() / "config.yaml")
    source_servers = source_cfg.get("mcp_servers", {})
    if not isinstance(source_servers, dict):
        return set()
    return {str(name).strip() for name in source_servers if str(name).strip()}


def _mcp_server_is_synced_from_default(name: str, profile_name: str) -> bool:
    """True when *name* is inherited from the default profile sync."""
    from app.domain.profiles import _is_root_profile

    if _is_root_profile(profile_name):
        return False
    token = str(name or "").strip()
    if not token:
        return False
    return token in _mcp_servers_from_default_profile()


def _mcp_reject_synced_server_mutation(name: str, profile_name: str):
    """Raise ValueError when a default-synced MCP server must stay read-only."""
    if _mcp_server_is_synced_from_default(name, profile_name):
        raise ValueError(
            f"MCP server '{name}' is synced from the default profile and cannot be modified"
        )


def _server_summary(name, cfg, runtime_status=None, connect_error=None, *, profile_name: str = ""):
    """Return a safe summary of an MCP server config."""
    runtime_status = runtime_status if isinstance(runtime_status, dict) else {}
    out = {"name": name}
    if not isinstance(cfg, dict):
        out.update({
            "transport": "invalid",
            "timeout": 120,
            "connect_timeout": 60,
            "enabled": False,
            "active": False,
            "status": "invalid_config",
            "tool_count": None,
        })
        return out

    enabled = _parse_mcp_enabled(cfg.get("enabled", True))
    connected = bool(runtime_status.get("connected")) if enabled else False
    if "url" in cfg:
        out["transport"] = "http"
        if "headers" in cfg:
            out["headers"] = _mask_http_headers(cfg["headers"])
        out.update(_mcp_auth_summary(cfg))
        out["url"] = cfg["url"]
    elif "command" in cfg:
        out["transport"] = "stdio"
        out["command"] = cfg.get("command", "")
        out["args"] = cfg.get("args", [])
        if "env" in cfg:
            out["env"] = _mask_secrets(cfg["env"])
    else:
        out["transport"] = "invalid"
        enabled = False
        connected = False

    out["timeout"] = cfg.get("timeout", 120)
    out["connect_timeout"] = cfg.get("connect_timeout", 60)
    out["enabled"] = enabled
    out["active"] = connected
    if out["transport"] == "invalid":
        out["status"] = "invalid_config"
    elif not enabled:
        out["status"] = "disabled"
    elif connected:
        out["status"] = "active"
    else:
        out["status"] = "configured"
    if connect_error:
        out["connect_error"] = _mcp_safe_display_text(str(connect_error), limit=240)
        if enabled and not connected:
            out["status"] = "error"
            out["tool_count"] = None
    else:
        out["tool_count"] = runtime_status.get("tools") if runtime_status else None
    if profile_name and _mcp_server_is_synced_from_default(str(name), profile_name):
        out["read_only"] = True
        out["synced_from_default"] = True
    return out


def _mcp_safe_display_text(value, *, limit: int) -> str:
    """Return redacted, bounded MCP text safe for WebUI inventory rows."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    value = _redact_text(value).strip()
    value = re.sub(r"Authorization:\s*Bearer\s+\S+", "[REDACTED CREDENTIAL]", value, flags=re.I)
    if len(value) > limit:
        value = value[: max(0, limit - 1)].rstrip() + "…"
    return value


def _mcp_schema_type(schema) -> str:
    """Return a compact, non-sensitive display type for a JSON schema node."""
    if not isinstance(schema, dict):
        return "unknown"
    typ = schema.get("type")
    if isinstance(typ, list):
        typ = "/".join(str(t) for t in typ if t)
    if isinstance(typ, str) and typ:
        return typ
    for composite in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(composite), list) and schema[composite]:
            return composite
    if "enum" in schema:
        return "enum"
    return "unknown"


def _mcp_schema_summary(schema, *, limit: int = 12) -> list[dict]:
    """Summarize an MCP input schema without exposing raw defaults/examples.

    The WebUI only needs searchable/displayable argument hints. Returning raw
    JSON Schema can overexpose server-provided defaults, examples, enums, or
    vendor extensions, so this strips each parameter down to name/type/required
    and a redacted description.
    """
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = schema.get("required")
    required_names = set(required) if isinstance(required, list) else set()
    out = []
    for name, prop in properties.items():
        if len(out) >= limit:
            break
        if not isinstance(name, str):
            continue
        prop = prop if isinstance(prop, dict) else {}
        desc = prop.get("description", "")
        if not isinstance(desc, str):
            desc = ""
        desc = _mcp_safe_display_text(desc, limit=180)
        out.append({
            "name": name,
            "type": _mcp_schema_type(prop),
            "required": name in required_names,
            "description": desc,
        })
    return out


def _mcp_tool_schema_from_payload(tool):
    if not isinstance(tool, dict):
        return {}
    for key in ("parameters", "inputSchema", "input_schema", "schema"):
        value = tool.get(key)
        if isinstance(value, dict):
            if key == "schema" and isinstance(value.get("parameters"), dict):
                return value["parameters"]
            return value
    return {}


def _mcp_tool_summary(name, tool, server_summary):
    """Return a safe global inventory row for one MCP tool."""
    server_summary = server_summary if isinstance(server_summary, dict) else {}
    if isinstance(tool, str):
        tool = {"name": tool}
    elif not isinstance(tool, dict):
        tool = {}
    tool_name = str(tool.get("name") or name or "")
    description = tool.get("description") or ""
    if not isinstance(description, str):
        description = str(description)
    description = _mcp_safe_display_text(description, limit=360)
    return {
        "name": tool_name,
        "server": str(server_summary.get("name") or ""),
        "description": description,
        "active": bool(server_summary.get("active")),
        "enabled": bool(server_summary.get("enabled")),
        "status": server_summary.get("status") or "unknown",
        "schema_summary": _mcp_schema_summary(_mcp_tool_schema_from_payload(tool)),
    }


def _mcp_tools_from_runtime_status(runtime_by_name, server_summaries):
    """Read detailed MCP tool payloads from runtime status when available."""
    tools = []
    if not isinstance(runtime_by_name, dict):
        return tools
    for server_name, runtime in runtime_by_name.items():
        if not isinstance(runtime, dict):
            continue
        raw_tools = runtime.get("tools")
        if not isinstance(raw_tools, list):
            raw_tools = runtime.get("tool_schemas")
        if not isinstance(raw_tools, list):
            continue
        server_summary = server_summaries.get(str(server_name), {"name": str(server_name)})
        for index, tool in enumerate(raw_tools):
            fallback_name = f"{server_name}:{index}"
            summary = _mcp_tool_summary(fallback_name, tool, server_summary)
            if summary["name"]:
                tools.append(summary)
    return tools


def _mcp_tools_from_registry(server_summaries):
    """Read already-registered MCP tool schemas without probing MCP servers."""
    try:
        from tools.registry import registry
    except Exception:
        return []
    tools = []
    try:
        names = registry.get_all_tool_names()
    except Exception:
        return []
    for tool_name in names:
        try:
            toolset = registry.get_toolset_for_tool(tool_name)
        except Exception:
            continue
        if not isinstance(toolset, str) or not toolset.startswith("mcp-"):
            continue
        server_name = toolset[len("mcp-"):]
        schema = registry.get_schema(tool_name) or {}
        server_summary = server_summaries.get(server_name, {
            "name": server_name,
            "enabled": True,
            "active": False,
            "status": "configured",
        })
        tools.append(_mcp_tool_summary(tool_name, schema, server_summary))
    return tools


def _handle_mcp_tools_list(handler):
    """List known MCP tools from already-available runtime inventory only."""
    cfg = get_config()
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    runtime = _mcp_runtime_status_by_name()
    server_summaries = {
        str(name): _server_summary(str(name), scfg, runtime.get(str(name)))
        for name, scfg in servers.items()
    }
    tools = _mcp_tools_from_runtime_status(runtime, server_summaries)
    source = "mcp_runtime_status"
    if not tools:
        tools = _mcp_tools_from_registry(server_summaries)
        source = "tool_registry" if tools else "none"
    tools.sort(key=lambda row: (row.get("server", ""), row.get("name", "")))
    unavailable_servers = [
        summary["name"] for summary in server_summaries.values()
        if summary.get("enabled") and not summary.get("active")
    ]
    return j(handler, {
        "tools": tools,
        "total": len(tools),
        "source": source,
        "inventory_scope": "already_known_runtime_only",
        "unavailable_servers": unavailable_servers,
    })


def _webui_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _external_notes_sources_enabled(config_data: dict | None = None) -> bool:
    """Return whether the third-party notes drawer is explicitly enabled.

    The Memory panel is a primary surface, so this power-user drawer stays
    default-off unless a deployment opts in through config or environment.
    """
    env_value = os.getenv("HERMES_WEBUI_EXTERNAL_NOTES_SOURCES", "")
    if env_value:
        return _webui_truthy(env_value)
    cfg = config_data if isinstance(config_data, dict) else get_config()
    if not isinstance(cfg, dict):
        return False
    return _webui_truthy(
        cfg.get("webui_external_notes_sources")
        or cfg.get("external_notes_sources")
        or cfg.get("notes_sources_drawer")
    )


_NOTES_SOURCE_SERVER_HINTS = {
    "joplin", "obsidian", "notion", "llm-wiki", "llmwiki", "wiki",
    "notes", "note", "knowledge", "kb", "readwise", "logseq",
}
_NOTES_SOURCE_TOOL_HINTS = {
    "note", "notes", "notebook", "page", "pages", "wiki", "knowledge",
    "search_notes", "get_note", "list_notes", "read_note",
}
_NOTES_SOURCE_CONFIGURED_TOOL_HINTS = {
    "joplin": [
        {"name": "search_notes", "description": "Search Joplin notes by keyword."},
        {"name": "list_notes", "description": "List notes from a Joplin notebook."},
        {"name": "get_note", "description": "Read a specific Joplin note by ID."},
    ],
    "obsidian": [
        {"name": "search_notes", "description": "Search Obsidian notes by keyword."},
        {"name": "read_note", "description": "Read a specific Obsidian note or file."},
    ],
    "notion": [
        {"name": "search_pages", "description": "Search Notion pages or databases."},
        {"name": "get_page", "description": "Read a specific Notion page."},
    ],
    "llm-wiki": [
        {"name": "query_knowledge_base", "description": "Query the LLM Wiki knowledge base."},
        {"name": "read_page", "description": "Read a specific wiki page."},
    ],
    "llmwiki": [
        {"name": "query_knowledge_base", "description": "Query the LLM Wiki knowledge base."},
        {"name": "read_page", "description": "Read a specific wiki page."},
    ],
}


def _note_source_label(name: str) -> str:
    labels = {
        "joplin": "Joplin",
        "obsidian": "Obsidian",
        "notion": "Notion",
        "llm-wiki": "LLM Wiki",
        "llmwiki": "LLM Wiki",
        "readwise": "Readwise",
        "logseq": "Logseq",
    }
    lowered = str(name or "").strip().lower()
    return labels.get(lowered, str(name or "").replace("_", " ").replace("-", " ").title())


def _looks_like_notes_source(server_name: str, tool_rows: list[dict]) -> bool:
    server_l = str(server_name or "").lower()
    if any(hint in server_l for hint in _NOTES_SOURCE_SERVER_HINTS):
        return True
    for tool in tool_rows:
        haystack = " ".join([
            str(tool.get("name") or ""),
            str(tool.get("description") or ""),
        ]).lower()
        if any(hint in haystack for hint in _NOTES_SOURCE_TOOL_HINTS):
            return True
    return False


def _configured_note_tool_hints(server_name: str) -> list[dict]:
    """Return safe expected note-tool hints for configured known sources."""
    server_l = str(server_name or "").strip().lower()
    hints = _NOTES_SOURCE_CONFIGURED_TOOL_HINTS.get(server_l)
    if hints is None:
        if any(hint in server_l for hint in ("wiki", "knowledge", "kb")):
            hints = [
                {"name": "search", "description": "Search this configured knowledge source."},
                {"name": "read", "description": "Read an item from this configured knowledge source."},
            ]
        elif any(hint in server_l for hint in ("note", "notes")):
            hints = [
                {"name": "search_notes", "description": "Search this configured notes source."},
                {"name": "read_note", "description": "Read a note from this configured notes source."},
            ]
        else:
            hints = []
    return [
        {
            "name": _mcp_safe_display_text(row.get("name") or "", limit=96),
            "description": _mcp_safe_display_text(row.get("description") or "", limit=180),
            "inferred": True,
        }
        for row in hints
        if isinstance(row, dict)
    ]


def _notes_sources_from_mcp_inventory(server_summaries: dict, tools: list[dict]) -> list[dict]:
    """Build a safe notes/knowledge-source inventory from MCP servers/tools.

    Some WebUI deployments can read ``mcp_servers`` from config before their
    local runtime/tool registry has hydrated MCP tool metadata.  Still show
    configured note/knowledge servers (for example Joplin) in that case so the
    drawer reflects connection/configuration state instead of appearing empty.
    """
    by_server: dict[str, list[dict]] = {}
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        server = str(tool.get("server") or "").strip()
        if not server:
            continue
        by_server.setdefault(server, []).append(tool)

    if isinstance(server_summaries, dict):
        for server, summary in server_summaries.items():
            server_name = str(server or "").strip()
            if not server_name or server_name in by_server:
                continue
            if _looks_like_notes_source(server_name, []):
                by_server.setdefault(server_name, [])

    sources = []
    for server, tool_rows in by_server.items():
        if not _looks_like_notes_source(server, tool_rows):
            continue
        summary = server_summaries.get(server, {"name": server}) if isinstance(server_summaries, dict) else {"name": server}
        safe_tools = []
        tool_source = "runtime"
        for tool in tool_rows[:8]:
            desc = _mcp_safe_display_text(tool.get("description") or "", limit=180)
            desc = re.sub(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", "[REDACTED]", desc)
            safe_tools.append({
                "name": _mcp_safe_display_text(tool.get("name") or "", limit=96),
                "description": desc,
            })
        if not safe_tools:
            safe_tools = _configured_note_tool_hints(server)
            if safe_tools:
                tool_source = "configured_hint"
        sources.append({
            "name": server,
            "label": _note_source_label(server),
            "enabled": bool(summary.get("enabled", True)),
            "active": bool(summary.get("active")),
            "status": summary.get("status") or "unknown",
            "tool_count": len(safe_tools),
            "tool_source": tool_source,
            "tools": safe_tools,
        })
    sources.sort(key=lambda row: (not row.get("active"), row.get("label", "")))
    return sources


def _handle_notes_sources_list(handler):
    """List note/knowledge MCP sources for the WebUI Notes drawer."""
    cfg = get_config()
    if not _external_notes_sources_enabled(cfg):
        return j(handler, {
            "enabled": False,
            "sources": [],
            "source": "disabled",
            "inventory_scope": "disabled_by_default",
            "attach_supported": False,
            "automatic_recall_unchanged": True,
            "recent_ai_notes": [],
        })
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    runtime = _mcp_runtime_status_by_name()
    server_summaries = {
        str(name): _server_summary(str(name), scfg, runtime.get(str(name)))
        for name, scfg in servers.items()
    }
    tools = _mcp_tools_from_runtime_status(runtime, server_summaries)
    source = "mcp_runtime_status"
    if not tools:
        tools = _mcp_tools_from_registry(server_summaries)
        source = "tool_registry" if tools else "none"
    return j(handler, {
        "enabled": True,
        "sources": _notes_sources_from_mcp_inventory(server_summaries, tools),
        "source": source,
        "inventory_scope": "already_known_runtime_only",
        "attach_supported": False,
        "automatic_recall_unchanged": True,
        "recent_ai_notes": _joplin_recent_ai_notes(limit=6),
    })


def _notes_configured_server(source: str) -> dict:
    cfg = get_config()
    servers = cfg.get("mcp_servers", {}) if isinstance(cfg, dict) else {}
    if not isinstance(servers, dict):
        return {}
    source_l = str(source or "").strip().lower()
    for name, server_cfg in servers.items():
        if str(name or "").strip().lower() == source_l and isinstance(server_cfg, dict):
            return server_cfg
    return {}


def _joplin_connection_from_config() -> tuple[str, str]:
    cfg = _notes_configured_server("joplin")
    env = cfg.get("env", {}) if isinstance(cfg, dict) else {}
    if not isinstance(env, dict):
        env = {}
    url = str(env.get("JOPLIN_URL") or os.environ.get("JOPLIN_URL") or "http://127.0.0.1:41184").rstrip("/")
    token = str(env.get("JOPLIN_TOKEN") or os.environ.get("JOPLIN_TOKEN") or "")
    return url, token


def _joplin_api_get(path: str, params: dict | None = None) -> dict:
    """Call the local Joplin Web Clipper API without logging credentials."""
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    base_url, token = _joplin_connection_from_config()
    if not token:
        raise ValueError("Joplin token is not configured")
    safe_path = "/" + str(path or "").lstrip("/")
    query = dict(params or {})
    url = f"{base_url}{safe_path}?{urlencode(query)}"
    request = Request(url, headers={"Authorization": f"token {token}"})
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise ValueError(f"Joplin API returned HTTP {exc.code}") from None
    except URLError as exc:
        raise ValueError("Joplin API is not reachable") from None
    try:
        data = json.loads(raw)
    except Exception:
        raise ValueError("Joplin API returned invalid JSON") from None
    return data if isinstance(data, dict) else {}


def _note_snippet(body: str, query: str = "", *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    if not text:
        return ""
    q = str(query or "").strip().lower()
    if q:
        idx = text.lower().find(q)
        if idx > 40:
            text = "…" + text[max(0, idx - 60):]
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _joplin_search_notes(query: str, *, limit: int = 20) -> list[dict]:
    query = str(query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 20), 50))
    data = _joplin_api_get("/search", {
        "query": query,
        "type": "note",
        "fields": "id,title,body,parent_id,updated_time",
        "limit": limit,
    })
    rows = data.get("items") if isinstance(data, dict) else []
    results = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        note_id = _mcp_safe_display_text(row.get("id") or "", limit=64)
        if not note_id:
            continue
        title = _mcp_safe_display_text(row.get("title") or "Untitled", limit=180)
        body = str(row.get("body") or "")
        results.append({
            "id": note_id,
            "title": title,
            "snippet": _mcp_safe_display_text(_note_snippet(body, query), limit=260),
            "parent_id": _mcp_safe_display_text(row.get("parent_id") or "", limit=64),
            "updated_time": row.get("updated_time"),
            "source": "joplin",
        })
    return results


def _joplin_get_note(note_id: str) -> dict:
    note_id = str(note_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", note_id):
        raise ValueError("Invalid Joplin note id")
    data = _joplin_api_get(f"/notes/{note_id}", {
        "fields": "id,title,body,parent_id,updated_time,created_time",
    })
    if not data.get("id"):
        raise ValueError("Joplin note not found")
    body = str(data.get("body") or "")
    if len(body) > 50_000:
        body = body[:50_000].rstrip() + "\n\n[Preview truncated at 50,000 characters]"
    return {
        "id": _mcp_safe_display_text(data.get("id") or "", limit=64),
        "title": _mcp_safe_display_text(data.get("title") or "Untitled", limit=180),
        "body": _redact_text(body),
        "parent_id": _mcp_safe_display_text(data.get("parent_id") or "", limit=64),
        "updated_time": data.get("updated_time"),
        "created_time": data.get("created_time"),
        "source": "joplin",
    }


_JOPLIN_AI_RECALL_NOTE_PRIORITY = [
    ("CURRENT_CONTEXT_ID", "Current Context"),
    ("OPEN_ISSUES_ID", "Open Issues"),
    ("AGENT_MEMORY_ID", "Agent Memory"),
    ("CONVENTIONS_ID", "Conventions / Preferences"),
    ("INFRA_ID", "Infrastructure"),
    ("SERVICES_ID", "Services"),
]


def _joplin_prefill_script_path() -> Path | None:
    cfg = get_config()
    path_value = cfg.get("prefill_messages_script") if isinstance(cfg, dict) else None
    if not path_value:
        return None
    try:
        return Path(str(path_value)).expanduser()
    except Exception:
        return None


def _joplin_recall_note_refs(script_path: Path | None = None) -> list[dict]:
    """Find stable Joplin note IDs referenced by the configured recall script.

    This keeps the WebUI generic: it does not hard-code a user's note IDs, but
    can still surface the notes that the configured AI prefill/recall script is
    known to read for automatic context.
    """
    script_path = script_path or _joplin_prefill_script_path()
    if not script_path or not script_path.exists() or not script_path.is_file():
        return []
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    constants = {
        match.group(1): match.group(2)
        for match in re.finditer(r'(?m)^\s*([A-Z0-9_]+_ID)\s*=\s*["\']([A-Fa-f0-9]{16,64})["\']', text)
    }
    refs = []
    seen = set()
    for const_name, label in _JOPLIN_AI_RECALL_NOTE_PRIORITY:
        note_id = constants.get(const_name)
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        refs.append({
            "id": note_id,
            "label": label,
            "constant": const_name,
            "used_by": "ai_prefill",
            "used_reason": "automatic_recall",
        })
    return refs


def _joplin_recent_ai_notes(*, limit: int = 6) -> list[dict]:
    """Return safe Joplin notes that the configured AI recall path recently uses."""
    try:
        limit = max(1, min(int(limit or 6), 20))
    except Exception:
        limit = 6
    notes = []
    for ref in _joplin_recall_note_refs()[:limit]:
        try:
            data = _joplin_api_get(f"/notes/{ref['id']}", {
                "fields": "id,title,parent_id,updated_time,user_updated_time,created_time",
            })
        except Exception:
            continue
        note_id = _mcp_safe_display_text(data.get("id") or ref.get("id") or "", limit=64)
        if not note_id:
            continue
        notes.append({
            "id": note_id,
            "title": _mcp_safe_display_text(data.get("title") or ref.get("label") or "Untitled", limit=180),
            "label": _mcp_safe_display_text(ref.get("label") or "", limit=120),
            "parent_id": _mcp_safe_display_text(data.get("parent_id") or "", limit=64),
            "updated_time": data.get("user_updated_time") or data.get("updated_time"),
            "created_time": data.get("created_time"),
            "source": "joplin",
            "used_by": ref.get("used_by") or "ai_prefill",
            "used_reason": ref.get("used_reason") or "automatic_recall",
        })
    return notes


def _handle_notes_search(handler, parsed):
    if not _external_notes_sources_enabled():
        return j(handler, {"source": "disabled", "results": [], "error": "External notes sources are disabled."}, status=404)
    query = parse_qs(parsed.query or "")
    source = str(query.get("source", ["joplin"])[0] or "joplin").strip().lower()
    q = str(query.get("q", [""])[0] or "").strip()
    try:
        limit = int(query.get("limit", ["20"])[0] or 20)
    except Exception:
        limit = 20
    if source != "joplin":
        return j(handler, {"source": source, "results": [], "error": "Search is currently implemented for Joplin sources only."}, status=400)
    try:
        return j(handler, {"source": "joplin", "query": q, "results": _joplin_search_notes(q, limit=limit)})
    except ValueError as exc:
        return j(handler, {"source": "joplin", "query": q, "results": [], "error": str(exc)}, status=502)


def _handle_notes_item(handler, parsed):
    if not _external_notes_sources_enabled():
        return j(handler, {"source": "disabled", "error": "External notes sources are disabled."}, status=404)
    query = parse_qs(parsed.query or "")
    source = str(query.get("source", ["joplin"])[0] or "joplin").strip().lower()
    note_id = str(query.get("id", [""])[0] or "").strip()
    if source != "joplin":
        return j(handler, {"source": source, "error": "Preview is currently implemented for Joplin sources only."}, status=400)
    try:
        return j(handler, {"source": "joplin", "note": _joplin_get_note(note_id)})
    except ValueError as exc:
        return j(handler, {"source": "joplin", "error": str(exc)}, status=502)


def _mcp_servers_needing_discovery(
    servers_cfg: dict,
    runtime_map: dict[str, dict],
) -> list[str]:
    """Return enabled server names that still need a connect/discover attempt."""
    needing: list[str] = []
    if not isinstance(servers_cfg, dict):
        return needing
    for name, scfg in servers_cfg.items():
        if not isinstance(scfg, dict):
            continue
        if not _parse_mcp_enabled(scfg.get("enabled", True)):
            continue
        runtime = runtime_map.get(str(name), {})
        connected = bool(runtime.get("connected")) if isinstance(runtime, dict) else False
        if connected:
            continue
        if _mcp_obvious_connect_error(str(name), scfg, connected):
            continue
        needing.append(str(name))
    return needing


def _run_mcp_discovery(profile_query: str = "") -> dict:
    """Connect to configured MCP servers for a profile without starting a chat."""
    from app.domain.profiles import _home_for_profile_name, get_active_profile_name
    from app.domain.streaming import _ENV_LOCK

    if profile_query:
        profile_name = _resolve_mcp_profile_name(profile_query)
    else:
        profile_name = get_active_profile_name()
    profile_home = _home_for_profile_name(profile_name)

    try:
        from tools.mcp_tool import get_mcp_status
        from app.domain.mcp_runtime import (
            discover_profile_mcp_tools,
            profile_mcp_home_changed,
        )
    except ImportError:
        return {
            "ok": False,
            "profile": profile_name,
            "error": "MCP SDK not available",
            "servers": [],
            "tool_count": 0,
            "connected_count": 0,
        }

    discover_error = None
    statuses: list = []
    profile_home_str = str(profile_home)
    prev_home = os.environ.get("HERMES_HOME")
    # Hold _ENV_LOCK only for os.environ mutation — MCP connect/discovery can
    # take 60–120s per server; holding the lock would serialize all API traffic.
    with _ENV_LOCK:
        os.environ["HERMES_HOME"] = profile_home_str
    try:
        try:
            if profile_mcp_home_changed(profile_home_str):
                discover_profile_mcp_tools(profile_home_str)
                try:
                    statuses = get_mcp_status()
                except Exception:
                    logger.debug(
                        "get_mcp_status failed after MCP profile switch",
                        exc_info=True,
                    )
                    statuses = []
            else:
                try:
                    statuses = get_mcp_status()
                except Exception:
                    logger.debug("get_mcp_status failed before MCP discovery", exc_info=True)
                    statuses = []
                runtime_pre = {
                    str(entry.get("name")): entry
                    for entry in statuses
                    if isinstance(entry, dict) and entry.get("name")
                }
                try:
                    cfg_pre, _, _ = _mcp_config_bundle(profile_query or profile_name)
                except ValueError:
                    cfg_pre = {}
                servers_pre = cfg_pre.get("mcp_servers", {})
                if not isinstance(servers_pre, dict):
                    servers_pre = {}
                if _mcp_servers_needing_discovery(servers_pre, runtime_pre):
                    discover_profile_mcp_tools(profile_home_str)
                    try:
                        statuses = get_mcp_status()
                    except Exception:
                        logger.debug("get_mcp_status failed after MCP discovery", exc_info=True)
                        statuses = []
        except Exception as exc:
            logger.exception("MCP discovery failed for profile %s", profile_name)
            discover_error = str(exc)
    finally:
        with _ENV_LOCK:
            if prev_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = prev_home

    try:
        cfg, _path, profile_name = _mcp_config_bundle(profile_query or profile_name)
    except ValueError as exc:
        return {
            "ok": False,
            "profile": profile_name,
            "error": str(exc),
            "servers": [],
            "tool_count": 0,
            "connected_count": 0,
        }

    runtime = {
        str(entry.get("name")): entry
        for entry in statuses
        if isinstance(entry, dict) and entry.get("name")
    }
    servers_cfg = cfg.get("mcp_servers", {})
    if not isinstance(servers_cfg, dict):
        servers_cfg = {}
    connect_errors = _mcp_connect_errors_for_profile(
        profile_name, servers_cfg, runtime, after_discover=True,
    )
    servers = [
        _server_summary(name, scfg, runtime.get(str(name)), connect_errors.get(str(name)))
        for name, scfg in servers_cfg.items()
    ]
    total_tools = sum(int(s.get("tool_count") or 0) for s in servers)
    connected_count = sum(1 for s in servers if s.get("active"))

    return {
        "ok": discover_error is None,
        "profile": profile_name,
        "servers": servers,
        "tool_count": total_tools,
        "connected_count": connected_count,
        "errors": connect_errors,
        "error": discover_error,
        "toggle_supported": True,
        "reload_required": False,
    }


def _handle_mcp_discover(handler, parsed=None, body=None):
    """POST /api/mcp/discover — connect configured MCP servers for a profile."""
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
    except ValueError:
        profile_query = ""
    if body and not profile_query:
        profile_query = str(body.get("profile") or "").strip()
    try:
        if profile_query:
            _resolve_mcp_profile_name(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    result = _run_mcp_discovery(profile_query)
    status = 200 if result.get("ok") else 502
    return j(handler, result, status=status)


def _handle_mcp_server_test(handler, name, parsed=None, body=None):
    """POST /api/mcp/servers/{name}/test — probe one MCP server and list its tools."""
    from urllib.parse import unquote

    name = unquote(name)
    if not name:
        return bad(handler, "name is required")
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
        cfg, _path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    if name not in servers:
        return bad(handler, f"MCP server '{name}' not found", 404)

    result = _run_mcp_discovery(profile_query)
    server_summary = None
    for entry in result.get("servers", []):
        if isinstance(entry, dict) and entry.get("name") == name:
            server_summary = entry
            break
    if server_summary is None:
        runtime = _mcp_runtime_status_by_name()
        connect_errors = result.get("errors") if isinstance(result.get("errors"), dict) else {}
        server_summary = _server_summary(
            name,
            servers[name],
            runtime.get(str(name)),
            connect_errors.get(str(name)),
            profile_name=profile_name,
        )

    runtime = _mcp_runtime_status_by_name()
    server_summaries = {str(name): server_summary}
    tools = _mcp_tools_from_runtime_status(runtime, server_summaries)
    if not tools:
        tools = [
            tool
            for tool in _mcp_tools_from_registry(server_summaries)
            if str(tool.get("server") or "") in {"", str(name)}
        ]
    tools = [tool for tool in tools if str(tool.get("server") or name) == str(name)]
    tools.sort(key=lambda row: row.get("name", ""))

    connect_errors = result.get("errors") if isinstance(result.get("errors"), dict) else {}
    server_error = connect_errors.get(str(name)) or result.get("error")
    connected = bool(server_summary.get("active"))
    ok = connected and result.get("ok") is not False and not server_error

    return j(handler, {
        "ok": ok,
        "profile": profile_name,
        "server": server_summary,
        "tools": tools,
        "tool_count": len(tools),
        "error": server_error,
    }, status=200 if ok else 502)


def _handle_mcp_servers_list(handler, parsed=None):
    """List configured MCP servers with safe, read-only runtime visibility."""
    try:
        profile_query = _mcp_profile_from_request(parsed)
        cfg, _path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    runtime = _mcp_runtime_status_by_name()
    connect_errors = dict(_MCP_PROFILE_CONNECT_ERRORS.get(profile_name, {}))
    for name, scfg in servers.items():
        obvious = _mcp_obvious_connect_error(
            str(name), scfg, bool(runtime.get(str(name), {}).get("connected")),
        )
        if obvious:
            connect_errors[str(name)] = obvious
    result = [
        _server_summary(
            name,
            scfg,
            runtime.get(str(name)),
            connect_errors.get(str(name)),
            profile_name=profile_name,
        )
        for name, scfg in servers.items()
    ]
    return j(handler, {
        "servers": result,
        "toggle_supported": True,
        "reload_required": True,
        "profile": profile_name,
        "errors": connect_errors,
    })


def _handle_mcp_server_delete(handler, name, parsed=None, body=None):
    """Delete an MCP server by name."""
    from urllib.parse import unquote
    name = unquote(name)
    if not name:
        return bad(handler, "name is required")
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
        cfg, path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    if name not in servers:
        return bad(handler, f"MCP server '{name}' not found", 404)
    try:
        _mcp_reject_synced_server_mutation(name, profile_name)
    except ValueError as exc:
        return bad(handler, str(exc), 403)
    del servers[name]
    cfg["mcp_servers"] = servers
    _persist_mcp_config(cfg, path, profile_name)
    return j(handler, {"ok": True, "deleted": name, "profile": profile_name})


def _handle_mcp_server_toggle(handler, name, body, parsed=None):
    """Toggle enabled state for an MCP server (PATCH /api/mcp/servers/{name})."""
    from urllib.parse import unquote
    name = unquote(name)
    if not name:
        return bad(handler, "name is required")
    if "enabled" not in body:
        return bad(handler, "enabled field is required")
    enabled = bool(body["enabled"])
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
        cfg, path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    if name not in servers:
        return bad(handler, f"MCP server '{name}' not found", 404)
    try:
        _mcp_reject_synced_server_mutation(name, profile_name)
    except ValueError as exc:
        return bad(handler, str(exc), 403)
    if not isinstance(servers[name], dict):
        return bad(handler, f"MCP server '{name}' has invalid config", 400)
    servers[name]["enabled"] = enabled
    cfg["mcp_servers"] = servers
    _persist_mcp_config(cfg, path, profile_name)
    return j(handler, {"ok": True, "name": name, "enabled": enabled, "profile": profile_name})


_MASKED_PLACEHOLDER = "••••••"


def _strip_masked_values(submitted, existing):
    """Remove masked placeholder values from submitted dict, keeping originals."""
    if not isinstance(submitted, dict) or not isinstance(existing, dict):
        return submitted
    cleaned = {}
    for k, v in submitted.items():
        if isinstance(v, str) and v == _MASKED_PLACEHOLDER:
            if k in existing and isinstance(existing[k], str):
                cleaned[k] = existing[k]  # preserve original real value
                continue
        elif isinstance(v, dict) and k in existing and isinstance(existing[k], dict):
            cleaned[k] = _strip_masked_values(v, existing[k])
        else:
            cleaned[k] = v
    return cleaned


def _build_mcp_server_config(body, existing_cfg=None) -> dict:
    """Build a validated MCP server config dict from an API body or nested config."""
    existing_cfg = existing_cfg if isinstance(existing_cfg, dict) else {}
    explicit_headers = "headers" in body
    explicit_auth = "auth" in body
    if isinstance(body.get("config"), dict):
        server_cfg = dict(body["config"])
    else:
        server_cfg = {}
        if body.get("url"):
            server_cfg["url"] = str(body["url"]).strip()
        elif body.get("command"):
            server_cfg["command"] = str(body["command"]).strip()
            if body.get("args") is not None:
                args = body["args"]
                server_cfg["args"] = args if isinstance(args, list) else [args]
            if body.get("env"):
                server_cfg["env"] = body["env"]
        if explicit_headers:
            headers = body.get("headers")
            if isinstance(headers, dict):
                if headers:
                    server_cfg["headers"] = _strip_masked_values(
                        headers, existing_cfg.get("headers", {})
                    )
                else:
                    server_cfg["headers"] = {}
        if explicit_auth:
            auth_val = str(body.get("auth") or "").strip().lower()
            if auth_val:
                server_cfg["auth"] = auth_val
            else:
                server_cfg["_clear_auth"] = True
        if body.get("timeout") is not None:
            try:
                server_cfg["timeout"] = int(body["timeout"])
            except (ValueError, TypeError):
                pass
        if "enabled" in body:
            server_cfg["enabled"] = bool(body["enabled"])

    server_cfg.pop("profile", None)
    server_cfg.pop("name", None)

    if not server_cfg.get("url") and not server_cfg.get("command"):
        if not (existing_cfg.get("url") or existing_cfg.get("command")):
            raise ValueError("url or command is required")

    if server_cfg.get("headers"):
        server_cfg["headers"] = _strip_masked_values(
            server_cfg["headers"], existing_cfg.get("headers", {})
        )
    if server_cfg.get("env"):
        server_cfg["env"] = _strip_masked_values(
            server_cfg["env"], existing_cfg.get("env", {})
        )

    if existing_cfg:
        for key in ("headers", "env", "args", "auth", "oauth", "connect_timeout", "command", "url"):
            if key in server_cfg or key not in existing_cfg:
                continue
            if key == "headers" and explicit_headers:
                continue
            if key == "auth" and explicit_auth:
                continue
            server_cfg[key] = existing_cfg[key]

    if server_cfg.pop("_clear_auth", False) or (explicit_auth and not server_cfg.get("auth")):
        server_cfg.pop("auth", None)
    if explicit_headers and isinstance(body.get("headers"), dict) and not body.get("headers"):
        server_cfg.pop("headers", None)
        server_cfg.pop("auth", None)

    if "enabled" not in server_cfg and "enabled" in existing_cfg:
        server_cfg["enabled"] = existing_cfg["enabled"]
    return server_cfg


def _handle_mcp_servers_import(handler, parsed=None, body=None):
    """Import one or more MCP servers from a JSON object keyed by server name."""
    body = body if isinstance(body, dict) else {}
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
        cfg, path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)

    servers_in = body.get("servers")
    if servers_in is None:
        servers_in = body.get("mcp_servers")
    if not isinstance(servers_in, dict) or not servers_in:
        return bad(handler, "servers object required")

    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}

    imported = []
    for raw_name, scfg in servers_in.items():
        name = str(raw_name or "").strip()
        if not name:
            return bad(handler, "server name cannot be empty")
        if not isinstance(scfg, dict):
            return bad(handler, f"MCP server '{name}' config must be an object")
        try:
            servers[name] = _build_mcp_server_config({"config": scfg}, servers.get(name, {}))
        except ValueError as exc:
            return bad(handler, f"MCP server '{name}': {exc}", 400)
        imported.append(name)

    cfg["mcp_servers"] = servers
    _persist_mcp_config(cfg, path, profile_name)
    return j(handler, {"ok": True, "imported": imported, "profile": profile_name})


def _handle_mcp_server_update(handler, name, body, parsed=None):
    """Add or update an MCP server."""
    from urllib.parse import unquote
    name = unquote(name)
    if not name:
        return bad(handler, "name is required")
    try:
        profile_query = _mcp_profile_from_request(parsed, body)
        cfg, path, profile_name = _mcp_config_bundle(profile_query)
    except ValueError as exc:
        return bad(handler, str(exc), 404)
    servers = cfg.get("mcp_servers", {})
    if not isinstance(servers, dict):
        servers = {}
    existing_cfg = servers.get(name, {})
    if not isinstance(existing_cfg, dict):
        existing_cfg = {}
    if name in servers:
        try:
            _mcp_reject_synced_server_mutation(name, profile_name)
        except ValueError as exc:
            return bad(handler, str(exc), 403)
    try:
        server_cfg = _build_mcp_server_config(body, existing_cfg)
    except ValueError as exc:
        return bad(handler, str(exc), 400)
    servers[name] = server_cfg
    cfg["mcp_servers"] = servers
    _persist_mcp_config(cfg, path, profile_name)
    return j(handler, {"ok": True, "server": _server_summary(name, server_cfg), "profile": profile_name})
