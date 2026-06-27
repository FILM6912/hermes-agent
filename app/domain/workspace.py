"""
Hermes Web UI -- Workspace and file system helpers.

API shim note (FastAPI migration):
  Workspace list/load/save and filesystem helpers live in this module. HTTP
  handlers import these functions directly. A lazy re-export at the bottom still
  exposes ``SettingsRepository`` from ``app.repositories.settings`` for callers
  that have not migrated yet.

Workspace lists and last-used workspace are stored per profile in legacy
mode.  In multi-user mode, regular accounts share one workspace keyed by
account email (under the shared workspace mount) and keep registry state at
``{HERMES_HOME}/users/<account-slug>/webui_state/``.  Agent profiles still
hold model/config under ``profiles/<name>/`` but file workspace is per user.
"""
import contextvars
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import concurrent.futures
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.repositories.settings import SettingsRepository

from app.domain.config import (
    WORKSPACES_FILE as _GLOBAL_WS_FILE,
    LAST_WORKSPACE_FILE as _GLOBAL_LW_FILE,
    DEFAULT_WORKSPACE as _BOOT_DEFAULT_WORKSPACE,
    MAX_FILE_BYTES, IMAGE_EXTS, MD_EXTS
)


# ── Profile-aware path resolution ───────────────────────────────────────────

MAX_WORKSPACES_PER_PROFILE = 1
MAX_NESTED_WORKSPACES_PER_PROFILE = 64
VIRTUAL_WORKSPACE_ROOT = '/workspace'
_DEFAULT_PROFILE_WORKSPACE_REL = './workspace'
_DEFAULT_PROFILE_WORKSPACE_NAME = 'Home'

_request_user_access: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "hermes_request_user_access",
    default=None,
)


def set_request_user_access(access: Any) -> contextvars.Token:
    """Bind multi-user access for sync handlers (copied into anyio threadpool)."""
    return _request_user_access.set(access)


def clear_request_user_access(token: contextvars.Token) -> None:
    _request_user_access.reset(token)


def get_request_user_access() -> Any:
    return _request_user_access.get()


def _account_workspace_slug_for_access(access: Any) -> str | None:
    """Return the shared-workspace segment for a multi-user account."""
    if access is None or not getattr(access, "multi_user_enabled", False):
        return None
    user_id = getattr(access, "user_id", None) or getattr(access, "username", None)
    if not user_id:
        return None
    from app.domain.users import profile_name_from_email

    return profile_name_from_email(str(user_id))


def _bound_profile_for_workspace_access(access: Any) -> str:
    """Return the Hermes profile name used to resolve this account's workspace tree.

    Multi-user accounts always map to their email-derived slug so a stale global
    ``default_workspace``, shared agent profile binding, or mismatched
    ``profile_name`` cannot pin containment to another user's ``workspace/<slug>``
    directory.
    """
    slug = _account_workspace_slug_for_access(access)
    if getattr(access, "multi_user_enabled", False) and slug:
        return slug
    if getattr(access, "restricts_profiles", False):
        return slug or str(getattr(access, "profile_name", None) or "").strip() or "default"
    return (
        str(getattr(access, "profile_name", None) or "").strip()
        or slug
        or "default"
    )


def _profile_home_for_workspace_access(
    access: Any | None = None,
    *,
    profile_home: Path | None = None,
) -> Path | None:
    """Resolve the profile home directory for the signed-in account workspace."""
    if profile_home is not None:
        return profile_home.expanduser().resolve()
    if access is None:
        access = get_request_user_access()
    if access is None or not getattr(access, "multi_user_enabled", False):
        return None
    try:
        from app.domain.profiles import get_hermes_home_for_profile

        return get_hermes_home_for_profile(
            _bound_profile_for_workspace_access(access)
        ).expanduser().resolve()
    except Exception:
        return None


def _uses_account_workspace_registry(access: Any) -> bool:
    """True when picker/files should use the bound account registry only."""
    if access is None or not getattr(access, "multi_user_enabled", False):
        return False
    user_id = str(
        getattr(access, "user_id", None) or getattr(access, "username", None) or ""
    ).strip().lower()
    if not user_id:
        return False
    from app.domain.users import LEGACY_ADMIN_USER_ID

    if getattr(access, "is_admin", False) and user_id == LEGACY_ADMIN_USER_ID:
        return False
    return True


def nested_workspaces_enabled() -> bool:
    """Nested sub-workspaces under each profile root are enabled in multi-user mode."""
    try:
        from app.domain.users import is_multi_user_enabled

        return is_multi_user_enabled()
    except ImportError:
        return False


def _account_workspace_isolation_enabled(access: Any = None) -> bool:
    """True when the signed-in account has a per-user workspace containment root."""
    if not nested_workspaces_enabled():
        return False
    if access is None:
        access = get_request_user_access()
    if not getattr(access, "multi_user_enabled", False):
        return False
    return account_workspace_containment_root(access=access) is not None


def is_virtual_workspace_path(path: str | Path | None) -> bool:
    token = str(path or '').strip()
    if not token:
        return False
    if token == VIRTUAL_WORKSPACE_ROOT:
        return True
    prefix = VIRTUAL_WORKSPACE_ROOT + '/'
    return token.startswith(prefix) and '..' not in token.split('/')


def _virtual_relative_segment(path: str) -> str:
    token = str(path or '').strip()
    if token in (VIRTUAL_WORKSPACE_ROOT, f'{VIRTUAL_WORKSPACE_ROOT}/.'):
        return ''
    prefix = VIRTUAL_WORKSPACE_ROOT + '/'
    if not token.startswith(prefix):
        raise ValueError(f"Not a virtual workspace path: {path}")
    rel = token[len(prefix):].strip('/')
    if not rel or rel == '.':
        return ''
    for part in rel.split('/'):
        if not part or part in {'.', '..'}:
            raise ValueError(f"Invalid virtual workspace segment: {path}")
    return rel


def _strip_redundant_account_slug_from_virtual_rel(rel: str) -> str:
    """Drop a leading account slug when the disk root already includes it.

    Models often emit ``/workspace/admin/file.csv`` while the active account
    root is already ``.../workspace/admin``; without this strip the rewrite
    lands in ``.../workspace/admin/admin/file.csv``.
    """
    token = str(rel or "").strip().strip("/")
    if not token:
        return ""
    slug = _account_workspace_slug_for_access(get_request_user_access())
    if not slug:
        return token
    if token == slug:
        return ""
    prefix = f"{slug}/"
    if token.startswith(prefix):
        return token[len(prefix) :]
    return token


def _virtual_workspace_disk_root_for_mapping(
    profile_home: Path | None = None,
    *,
    access: Any = None,
) -> Path:
    """On-disk directory backing the virtual ``/workspace`` picker root.

    Registry/API resolution must not read process-global ``TERMINAL_CWD`` — a
    concurrent agent run can temporarily pin ``/app`` (Docker workdir) while the
    UI polls ``GET /list?workspace=/workspace``, which would map virtual paths
    outside the account workspace and flash a containment error in Generated Files.
    Agent shell rewriting keeps using :func:`_virtual_workspace_disk_root` with
    explicit per-run ``terminal_cwd`` / ``active_virtual`` parameters instead.
    """
    if profile_home is None:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
        except ImportError:
            profile_home = Path.home()
    profile_home = profile_home.expanduser().resolve()
    if access is None:
        access = get_request_user_access()

    return profile_workspace_dir(profile_home, access=access).resolve()


def virtual_path_to_disk(
    path: str | Path,
    profile_home: Path | None = None,
    *,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> Path:
    """Map ``/workspace`` or ``/workspace/project1`` to the profile canonical directory."""
    if profile_home is None:
        profile_home = _profile_home_for_workspace_access()
        if profile_home is None:
            try:
                from app.domain.profiles import get_active_hermes_home

                profile_home = get_active_hermes_home()
            except ImportError:
                profile_home = Path.home()
    profile_home = profile_home.expanduser().resolve()
    cwd_token = str(terminal_cwd or "").strip()
    virt_token = str(active_workspace_virtual or "").strip()
    if cwd_token or virt_token:
        pinned_root = _virtual_workspace_disk_root(
            terminal_cwd=cwd_token or None,
            active_virtual=virt_token or None,
        )
        if pinned_root is not None:
            root = pinned_root.resolve()
        else:
            root = _virtual_workspace_disk_root_for_mapping(profile_home)
    else:
        root = _virtual_workspace_disk_root_for_mapping(profile_home)
    rel = _virtual_relative_segment(str(path))
    rel = _strip_redundant_account_slug_from_virtual_rel(rel)
    if not rel:
        return root
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Virtual workspace escapes profile root: {path}") from exc
    return target


def disk_path_to_virtual(
    disk: Path,
    profile_home: Path | None = None,
    *,
    access: Any = None,
) -> str | None:
    """Return a virtual ``/workspace/...`` path when *disk* lies under the profile root."""
    if access is None:
        access = get_request_user_access()
    if profile_home is None:
        profile_home = _profile_home_for_workspace_access(access)
        if profile_home is None:
            try:
                from app.domain.profiles import get_active_hermes_home

                profile_home = get_active_hermes_home()
            except ImportError:
                profile_home = Path.home()
    try:
        root = profile_workspace_dir(profile_home, access=access).resolve()
        resolved = Path(disk).expanduser().resolve()
        rel = resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if _account_workspace_isolation_enabled(access):
        containment = account_workspace_containment_root(access=access)
        if containment is not None:
            try:
                resolved.relative_to(containment.resolve())
            except ValueError:
                return None
    rel_token = rel.as_posix()
    if not rel_token or rel_token == '.':
        return VIRTUAL_WORKSPACE_ROOT
    return f"{VIRTUAL_WORKSPACE_ROOT}/{rel_token}"


def _foreign_workspace_suffix_after_slug(
    candidate: Path,
    account_slug: str,
) -> tuple[str, ...] | None:
    """Return path parts after ``workspace/<foreign>`` when foreign != *account_slug*."""
    try:
        parts = candidate.expanduser().resolve().parts
    except OSError:
        return None
    for i, part in enumerate(parts):
        if part == "workspace" and i + 1 < len(parts):
            foreign = parts[i + 1]
            if foreign != account_slug:
                return tuple(parts[i + 2 :])
    return None


def _coerce_to_account_workspace(
    candidate: Path,
    *,
    access: Any = None,
    raw: str | Path | None = None,
) -> Path:
    """Remap foreign shared-layout workspace paths to the signed-in account root."""
    if not nested_workspaces_enabled():
        return candidate
    if access is None:
        access = get_request_user_access()
    if not _account_workspace_isolation_enabled(access):
        return candidate
    containment = account_workspace_containment_root(access=access)
    if containment is None:
        return candidate
    boundary = containment.resolve()
    try:
        candidate.expanduser().resolve().relative_to(boundary)
        return candidate
    except ValueError:
        pass
    token = str(raw if raw is not None else candidate).strip()
    if is_virtual_workspace_path(token):
        return boundary
    account_slug = _account_workspace_slug_for_access(access)
    if account_slug:
        suffix = _foreign_workspace_suffix_after_slug(candidate, account_slug)
        if suffix is not None:
            target = boundary.joinpath(*suffix) if suffix else boundary
            return target.resolve()
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return candidate
    try:
        shared = _shared_workspace_root(hermes_home).resolve()
        candidate.expanduser().resolve().relative_to(shared)
        return boundary
    except ValueError:
        return candidate


def normalize_client_default_workspace(settings: dict, access: Any) -> None:
    """Map stored disk default_workspace to the account virtual picker path when needed."""
    raw = settings.get("default_workspace")
    if not isinstance(raw, str) or not raw.strip():
        return
    if not nested_workspaces_enabled():
        return
    profile_home = _profile_home_for_workspace_access(access)
    if profile_home is None:
        return
    mapped = disk_path_to_virtual(raw, profile_home, access=access)
    if mapped:
        try:
            mapped_disk = virtual_path_to_disk(mapped, profile_home)
            containment = account_workspace_containment_root(access=access)
            if (
                containment is not None
                and not path_within_account_workspace(mapped_disk, root=containment)
            ):
                settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT
                return
        except (OSError, ValueError):
            settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT
            return
        settings["default_workspace"] = mapped
        return
    try:
        stored = Path(raw).expanduser().resolve()
        profile_ws = profile_workspace_dir(profile_home, access=access).resolve()
        if stored == profile_ws:
            settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT
            return
        try:
            stored.relative_to(profile_ws)
            settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT
            return
        except ValueError:
            pass
        try:
            profile_ws.relative_to(stored)
            settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT
            return
        except ValueError:
            pass
    except (OSError, ValueError):
        pass
    settings["default_workspace"] = VIRTUAL_WORKSPACE_ROOT


_VIRTUAL_SHELL_PATH_RE = re.compile(
    r"(?<![\w.])\/workspace(?:/[^\s'\";|&<>()]*)?"
)


def _virtual_workspace_disk_root(
    *,
    terminal_cwd: str | Path | None = None,
    active_virtual: str | None = None,
) -> Path | None:
    """Derive the on-disk ``/workspace`` root from the active session cwd."""
    cwd_token = str(terminal_cwd or os.environ.get("TERMINAL_CWD") or "").strip()
    virtual_token = str(
        active_virtual or os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL") or ""
    ).strip()
    if not cwd_token or not is_virtual_workspace_path(virtual_token):
        return None
    try:
        cwd_path = Path(cwd_token).expanduser().resolve()
    except OSError:
        return None
    rel = virtual_token[len(VIRTUAL_WORKSPACE_ROOT):].strip("/")
    depth = len([part for part in rel.split("/") if part]) if rel else 0
    root = cwd_path
    for _ in range(depth):
        root = root.parent
    return root


def _collapse_doubled_hermes_home_prefix(text: str) -> str:
    """Collapse ``{HERMES_HOME}/{HERMES_HOME}/...`` typos models often emit."""
    try:
        hermes_home = _default_hermes_home()
    except Exception:
        hermes_home = None
    if hermes_home is None:
        raw = os.environ.get("HERMES_HOME", "").strip()
        if raw:
            hermes_home = Path(raw).expanduser()
    if not hermes_home:
        return text
    home = str(hermes_home.resolve())
    doubled = f"{home}/{home.lstrip('/')}"
    while doubled in text:
        text = text.replace(doubled, home)
    return text


def _rewrite_misresolved_workspace_paths(
    text: str,
    *,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Fix absolute workspace paths that skip the account folder segment."""
    cwd_token = str(terminal_cwd or os.environ.get("TERMINAL_CWD") or "").strip()
    if not cwd_token:
        return text
    try:
        cwd_path = Path(cwd_token).expanduser().resolve()
        hermes_home = _default_hermes_home()
        if hermes_home is None:
            return text
        shared_root = _shared_workspace_root(hermes_home).resolve()
        rel = cwd_path.relative_to(shared_root)
    except (OSError, ValueError):
        return text
    if len(rel.parts) < 2:
        return text
    wrong_prefix = str((shared_root / rel.parts[-1]).resolve())
    correct_prefix = str(cwd_path)
    if wrong_prefix == correct_prefix or wrong_prefix not in text:
        return text
    return text.replace(wrong_prefix, correct_prefix)


def _is_expanded_account_workspace_absolute(path: str) -> bool:
    """True when *path* is already an on-disk ``.../workspace/...`` absolute path."""
    token = str(path or "").strip()
    if not token.startswith("/") or is_virtual_workspace_path(token):
        return False
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return False
    try:
        shared = str(_shared_workspace_root(hermes_home).resolve())
    except OSError:
        return False
    return shared in token


def rewrite_virtual_paths_in_shell_command(
    command: str,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Map UI virtual ``/workspace/...`` segments to on-disk profile paths.

    Nested multi-user mode exposes ``/workspace/test`` in the picker, but shell
    tools run on the real filesystem (``~/.hermes/workspace/<account>/test``).
    Models often emit ``cd /workspace/...`` anyway; rewrite before execution.
    """
    if not nested_workspaces_enabled():
        return command
    text = str(command or "")
    if not text:
        return text

    text = _collapse_doubled_hermes_home_prefix(text)

    if "/workspace" in text:
        virt_root_disk = _virtual_workspace_disk_root(
            terminal_cwd=terminal_cwd,
            active_virtual=active_workspace_virtual,
        )

        def _replace(match: re.Match[str]) -> str:
            token = match.group(0).rstrip("/")
            if token == "/workspace":
                token = VIRTUAL_WORKSPACE_ROOT
            if virt_root_disk is not None:
                rel = token[len(VIRTUAL_WORKSPACE_ROOT):].strip("/")
                if not rel:
                    return str(virt_root_disk.resolve())
                try:
                    return str((virt_root_disk / rel).resolve())
                except OSError:
                    return match.group(0)
            try:
                return str(virtual_path_to_disk(token, profile_home).resolve())
            except (OSError, ValueError):
                return match.group(0)

        text = _VIRTUAL_SHELL_PATH_RE.sub(_replace, text)

    text = _rewrite_misresolved_workspace_paths(
        text,
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
    )
    text = _collapse_doubled_hermes_home_prefix(text)
    assert_account_workspace_text_paths(text, tool_name="shell")
    return text


def rewrite_virtual_path_in_file_arg(
    path: str,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Map a single file-tool path from UI virtual form to on-disk workspace paths."""
    if not nested_workspaces_enabled():
        return str(path or "")
    token = str(path or "").strip()
    if not token:
        return token

    token = _collapse_doubled_hermes_home_prefix(token)

    if is_virtual_workspace_path(token):
        try:
            return str(
                virtual_path_to_disk(
                    token,
                    profile_home,
                    terminal_cwd=terminal_cwd,
                    active_workspace_virtual=active_workspace_virtual,
                ).resolve()
            )
        except (OSError, ValueError):
            return token

    if _is_expanded_account_workspace_absolute(token):
        return _rewrite_misresolved_workspace_paths(
            token,
            terminal_cwd=terminal_cwd,
            active_workspace_virtual=active_workspace_virtual,
        )

    if "/workspace" in token:
        return rewrite_virtual_paths_in_shell_command(
            token,
            profile_home=profile_home,
            terminal_cwd=terminal_cwd,
            active_workspace_virtual=active_workspace_virtual,
        )

    return _rewrite_misresolved_workspace_paths(
        token,
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
    )


_CONTAINMENT_ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|[\s'\"=(\[])(/(?:[^\s'\";|&<>()]*)?)"
)

_TOOL_DISPLAY_PATH_KEYS = frozenset({
    'command',
    'cmd',
    'script',
    'code',
    'input',
    'shell',
    'path',
    'file',
    'filepath',
    'file_path',
    'image_url',
    'target',
    'dest',
    'destination',
})


def _display_path_replacements(
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> list[tuple[str, str]]:
    """Build on-disk -> virtual ``/workspace/...`` pairs (longest disk paths first)."""
    if not nested_workspaces_enabled():
        return []

    pairs: list[tuple[str, str]] = []

    cwd_token = str(terminal_cwd or os.environ.get('TERMINAL_CWD') or '').strip()
    virtual_token = str(
        active_workspace_virtual
        or os.environ.get('HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL')
        or ''
    ).strip()
    if cwd_token and is_virtual_workspace_path(virtual_token):
        try:
            cwd_resolved = str(Path(cwd_token).expanduser().resolve())
            virt = virtual_token.rstrip('/') or VIRTUAL_WORKSPACE_ROOT
            pairs.append((cwd_resolved, virt))
        except OSError:
            pass

    account_root = account_workspace_containment_root(
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
        profile_home=profile_home,
    )
    if account_root is not None:
        try:
            pairs.append((str(account_root.resolve()), VIRTUAL_WORKSPACE_ROOT))
        except OSError:
            pass

    if profile_home is None:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
        except ImportError:
            profile_home = None
    if profile_home is not None:
        try:
            pairs.append((
                str(profile_workspace_dir(profile_home).resolve()),
                VIRTUAL_WORKSPACE_ROOT,
            ))
        except OSError:
            pass

    seen_disk: set[str] = set()
    unique: list[tuple[str, str]] = []
    for disk, virt in sorted(pairs, key=lambda item: len(item[0]), reverse=True):
        if disk in seen_disk:
            continue
        seen_disk.add(disk)
        unique.append((disk, virt))
    return unique


def display_virtual_paths_in_shell_command(
    command: str,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Map on-disk workspace paths to UI virtual ``/workspace/...`` for display."""
    if not nested_workspaces_enabled():
        return str(command or '')
    text = str(command or '')
    if not text:
        return text

    for disk, virt in _display_path_replacements(
        profile_home=profile_home,
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
    ):
        if disk and disk in text:
            text = text.replace(disk, virt)

    def _replace_token(match: re.Match[str]) -> str:
        token = match.group(1)
        if not token or is_virtual_workspace_path(token):
            return match.group(0)
        try:
            resolved = Path(token).expanduser().resolve()
            mapped = disk_path_to_virtual(resolved, profile_home)
            if mapped:
                return match.group(0).replace(token, mapped, 1)
        except OSError:
            pass
        return match.group(0)

    return _CONTAINMENT_ABSOLUTE_PATH_RE.sub(_replace_token, text)


def display_virtual_paths_in_tool_args(
    args: dict | None,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> dict:
    """Rewrite path-like tool args to virtual workspace paths for UI display."""
    if not isinstance(args, dict):
        return {}
    out: dict = {}
    for key, value in args.items():
        if isinstance(value, str) and str(key).lower() in _TOOL_DISPLAY_PATH_KEYS:
            out[key] = display_virtual_paths_in_text(
                value,
                profile_home=profile_home,
                terminal_cwd=terminal_cwd,
                active_workspace_virtual=active_workspace_virtual,
            )
        else:
            out[key] = value
    return out


def display_virtual_paths_in_text(
    text: str,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Map on-disk workspace paths to virtual ``/workspace/...`` in arbitrary text."""
    return display_virtual_paths_in_shell_command(
        text,
        profile_home=profile_home,
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
    )


def agent_facing_workspace_path(
    workspace: str | Path,
    *,
    profile_home: Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Return the single workspace path models should see (virtual in nested mode)."""
    token = str(workspace or "").strip()
    if not token:
        return token
    if is_virtual_workspace_path(token):
        return token.rstrip("/") or VIRTUAL_WORKSPACE_ROOT
    if nested_workspaces_enabled():
        if profile_home is None:
            try:
                from app.domain.profiles import get_active_hermes_home

                profile_home = get_active_hermes_home()
            except ImportError:
                profile_home = None
        try:
            resolved = Path(token).expanduser().resolve()
        except OSError:
            resolved = None
        if profile_home is not None and resolved is not None:
            try:
                mapped = disk_path_to_virtual(resolved, profile_home)
            except OSError:
                mapped = None
            if mapped:
                return mapped
        virt_base = str(
            active_workspace_virtual
            or os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL")
            or VIRTUAL_WORKSPACE_ROOT
        ).strip()
        contain_root = account_workspace_containment_root(
            workspace_disk=token,
            terminal_cwd=os.environ.get("TERMINAL_CWD"),
            active_workspace_virtual=virt_base,
            profile_home=profile_home,
        )
        if (
            resolved is not None
            and contain_root is not None
            and is_virtual_workspace_path(virt_base)
        ):
            try:
                rel = resolved.relative_to(contain_root.resolve())
                rel_token = rel.as_posix()
                if not rel_token or rel_token == ".":
                    return VIRTUAL_WORKSPACE_ROOT
                return f"{VIRTUAL_WORKSPACE_ROOT}/{rel_token}"
            except ValueError:
                pass
        if is_virtual_workspace_path(virt_base):
            return virt_base.rstrip("/") or VIRTUAL_WORKSPACE_ROOT
    try:
        return str(Path(token).expanduser().resolve())
    except OSError:
        return token


def _resolve_account_workspace_root(
    access: Any,
    *,
    profile_home: Path | None = None,
) -> Path | None:
    """Return the canonical on-disk workspace root for a signed-in account."""
    if access is None or not getattr(access, "multi_user_enabled", False):
        return None
    user_id = str(
        getattr(access, "user_id", None) or getattr(access, "username", None) or ""
    ).strip().lower()
    from app.domain.users import LEGACY_ADMIN_USER_ID

    if not user_id or user_id == LEGACY_ADMIN_USER_ID:
        return None
    if profile_home is None:
        profile_home = _profile_home_for_workspace_access(access)
    if profile_home is None or not _account_workspace_slug_for_access(access):
        return None
    try:
        return profile_workspace_dir(profile_home, access=access).resolve()
    except OSError:
        return None


def _workspace_pin_within_account_root(pin: Path, account_root: Path) -> bool:
    """True when *pin* equals or lies inside the signed-in account workspace root."""
    try:
        resolved_pin = pin.expanduser().resolve()
        boundary = account_root.expanduser().resolve()
    except OSError:
        return False
    if resolved_pin == boundary:
        return True
    try:
        resolved_pin.relative_to(boundary)
        return True
    except ValueError:
        return False


def account_workspace_containment_root(
    *,
    workspace_disk: str | Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
    profile_home: Path | None = None,
    access: Any = None,
) -> Path | None:
    """Return the on-disk root directory for the signed-in account workspace tree."""
    if not nested_workspaces_enabled():
        return None

    if access is None:
        access = get_request_user_access()

    # Session/profile-scoped resolution must not inherit a stale process-global
    # pin left by another account's concurrent stream (multi-user WebUI).
    if profile_home is not None:
        try:
            return profile_workspace_dir(profile_home, access=access).resolve()
        except OSError:
            pass

    account_root = _resolve_account_workspace_root(access, profile_home=profile_home)

    pinned = str(os.environ.get("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT") or "").strip()
    if pinned:
        try:
            pinned_path = Path(pinned).expanduser().resolve()
            if account_root is None or _workspace_pin_within_account_root(
                pinned_path,
                account_root,
            ):
                return pinned_path
        except OSError:
            pass

    virt_root = _virtual_workspace_disk_root(
        terminal_cwd=terminal_cwd or workspace_disk,
        active_virtual=active_workspace_virtual,
    )
    if virt_root is not None:
        try:
            resolved_virt = virt_root.resolve()
            if account_root is None or _workspace_pin_within_account_root(
                resolved_virt,
                account_root,
            ):
                return resolved_virt
        except OSError:
            pass

    if account_root is not None:
        return account_root

    if access is None or not getattr(access, "multi_user_enabled", False):
        return None

    user_id = str(
        getattr(access, "user_id", None) or getattr(access, "username", None) or ""
    ).strip().lower()
    from app.domain.users import LEGACY_ADMIN_USER_ID

    if user_id == LEGACY_ADMIN_USER_ID:
        return None

    hermes_home = _default_hermes_home()
    if profile_home is None:
        profile_home = _profile_home_for_workspace_access(access)

    if getattr(access, "is_admin", False) and hermes_home is not None and user_id:
        try:
            owned = _admin_owned_shared_workspace_dirs(hermes_home, user_id)
        except (OSError, ValueError):
            owned = set()
        if owned:
            return sorted(owned, key=lambda item: len(str(item)))[0].resolve()

    if profile_home is not None:
        try:
            return profile_workspace_dir(profile_home, access=access).resolve()
        except OSError:
            pass
    return None


def path_within_account_workspace(
    path: str | Path,
    *,
    root: Path | None = None,
) -> bool:
    """Return True when *path* resolves inside the active account workspace root."""
    if not nested_workspaces_enabled():
        return True
    containment_root = root or account_workspace_containment_root()
    if containment_root is None:
        return True
    try:
        resolved = Path(path).expanduser().resolve()
        real = Path(os.path.realpath(str(resolved)))
    except OSError:
        return False
    boundary = containment_root.resolve()
    for candidate in (resolved, real):
        try:
            candidate.relative_to(boundary)
            return True
        except ValueError:
            continue
    return False


def _infrastructure_path_roots_outside_workspace() -> list[Path]:
    """Runtime locations agents may reference in shell/code without touching user data."""
    roots: list[Path] = []
    try:
        from app.domain.config import resolve_webui_virtual_env

        venv_root = resolve_webui_virtual_env()
        if venv_root:
            roots.append(Path(venv_root).expanduser().resolve())
    except Exception:
        pass

    for candidate in (
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
        Path.home() / ".local",
    ):
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.exists():
            roots.append(resolved)
    return roots


def _hermes_runtime_path_roots_outside_workspace() -> list[Path]:
    """Hermes install/config/state dirs agents may reference for diagnostics."""
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(candidate: str | Path | None) -> None:
        if candidate is None:
            return
        raw = str(candidate).strip()
        if not raw:
            return
        try:
            resolved = Path(raw).expanduser().resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    _add(_default_hermes_home())
    for env_name in ("HERMES_BASE_HOME", "HERMES_HOME", "HERMES_WEBUI_STATE_DIR"):
        _add(os.getenv(env_name, "").strip())
    try:
        from app.domain.profiles import get_active_hermes_home

        _add(get_active_hermes_home())
    except Exception:
        pass
    try:
        from app.domain.config import STATE_DIR

        _add(STATE_DIR)
    except Exception:
        pass
    return roots


def _approved_path_roots_outside_account_workspace() -> list[Path]:
    """Merge infrastructure and Hermes runtime roots for containment exceptions."""
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in (
        *_infrastructure_path_roots_outside_workspace(),
        *_hermes_runtime_path_roots_outside_workspace(),
    ):
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        roots.append(candidate)
    return roots


def _path_allowed_outside_account_workspace(path: str | Path) -> bool:
    """True when *path* is an approved runtime/install prefix, not arbitrary host data."""
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    for root in _approved_path_roots_outside_account_workspace():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def assert_account_workspace_path(
    path: str | Path,
    *,
    tool_name: str = "tool",
    root: Path | None = None,
) -> None:
    """Raise ``ValueError`` when *path* escapes the account workspace root."""
    if path_within_account_workspace(path, root=root):
        return
    if _path_allowed_outside_account_workspace(path):
        return
    boundary = root or account_workspace_containment_root()
    boundary_text = str(boundary) if boundary is not None else "the active account workspace"
    raise ValueError(
        f"Blocked: {tool_name} path {path!r} is outside {boundary_text}. "
        "Use paths under the active workspace only."
    )


def _span_inside_quoted_string(text: str, start: int, end: int) -> bool:
    """Return True when ``text[start:end]`` lies inside a quoted string literal."""
    if start < 0 or end <= start:
        return False
    in_single = False
    in_double = False
    in_triple_single = False
    in_triple_double = False
    i = 0
    n = len(text)
    while i < start:
        if in_single or in_double or in_triple_single or in_triple_double:
            if text[i] == "\\" and i + 1 < n:
                i += 2
                continue
            if in_triple_single and text[i:i + 3] == "'''":
                in_triple_single = False
                i += 3
                continue
            if in_triple_double and text[i:i + 3] == '"""':
                in_triple_double = False
                i += 3
                continue
            if in_single and text[i] == "'":
                in_single = False
            elif in_double and text[i] == '"':
                in_double = False
            i += 1
            continue
        if text[i:i + 3] == "'''":
            in_triple_single = True
            i += 3
            continue
        if text[i:i + 3] == '"""':
            in_triple_double = True
            i += 3
            continue
        if text[i] == "'":
            in_single = True
        elif text[i] == '"':
            in_double = True
        i += 1
    return in_single or in_double or in_triple_single or in_triple_double


def assert_account_workspace_text_paths(
    text: str,
    *,
    tool_name: str = "tool",
    root: Path | None = None,
) -> None:
    """Reject shell/code text that references absolute paths outside the workspace."""
    if not nested_workspaces_enabled():
        return
    boundary = root or account_workspace_containment_root()
    if boundary is None:
        return
    source = str(text or "")
    for match in _CONTAINMENT_ABSOLUTE_PATH_RE.finditer(source):
        token = match.group(1).rstrip("/") or "/"
        if token == "/":
            if _span_inside_quoted_string(source, match.start(1), match.end(1)):
                continue
            raise ValueError(
                f"Blocked: {tool_name} attempted to use filesystem root '/'. "
                f"Stay inside {boundary}."
            )
        if path_within_account_workspace(token, root=boundary):
            continue
        if _path_allowed_outside_account_workspace(token):
            continue
        raise ValueError(
            f"Blocked: {tool_name} path {token!r} is outside {boundary}. "
            "Use paths under the active workspace only."
        )


def rewrite_agent_visible_workspace_tags(
    text: str,
    *,
    profile_home: Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Rewrite ``[Workspace::v1: ...]`` disk paths to virtual ``/workspace/...``."""
    if not nested_workspaces_enabled():
        return str(text or "")
    value = str(text or "")
    if not value or "Workspace::v1:" not in value:
        return value

    tag_re = re.compile(r"(\[Workspace::v1:\s)((?:\\.|[^\]\\])+)(\])")

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(2).replace("\\\\", "\\").replace("\\]", "]")
        visible = agent_facing_workspace_path(
            raw,
            profile_home=profile_home,
            active_workspace_virtual=active_workspace_virtual,
        )
        escaped = visible.replace("\\", "\\\\").replace("]", "\\]")
        return f"{match.group(1)}{escaped}{match.group(3)}"

    return tag_re.sub(_replace, value)


def rewrite_agent_visible_message_content(
    content: str,
    *,
    profile_home: Path | None = None,
    terminal_cwd: str | Path | None = None,
    active_workspace_virtual: str | None = None,
) -> str:
    """Normalize model-facing message text to virtual workspace paths only."""
    text = rewrite_agent_visible_workspace_tags(
        str(content or ""),
        profile_home=profile_home,
        active_workspace_virtual=active_workspace_virtual,
    )
    return display_virtual_paths_in_text(
        text,
        profile_home=profile_home,
        terminal_cwd=terminal_cwd,
        active_workspace_virtual=active_workspace_virtual,
    )


_SCRIPT_SRC_RE = re.compile(
    r"<script\b([^>]*\bsrc\s*=\s*[\"'])([^\"']+)([\"'][^>]*)>",
    re.IGNORECASE,
)


def _workspace_relative_asset_path(
    src: str,
    *,
    workspace_root: Path,
    html_disk_path: Path,
) -> str | None:
    """Map a script src to a workspace-relative path for safe_resolve."""
    token = str(src or "").strip()
    if not token:
        return None
    if token.startswith(("http://", "https://", "//", "data:", "blob:")):
        return None
    if "/file/" in token:
        # Browser resolved relative URL against /api/v1/file/view → /api/v1/file/foo.js
        tail = token.split("/file/")[-1].split("?")[0].split("#")[0].strip("/")
        return tail or None
    if token.startswith("/api/") or token.startswith("/api/v1/"):
        return None
    if token.startswith("/"):
        return None
    try:
        html_dir = html_disk_path.resolve().parent
        root = workspace_root.resolve()
        rel_html_dir = html_dir.relative_to(root)
    except ValueError:
        rel_html_dir = Path(".")
    rel = (rel_html_dir / token).as_posix()
    return rel.lstrip("./")


def _inline_workspace_relative_scripts(
    html: str,
    *,
    workspace_root: Path,
    html_disk_path: Path,
) -> str:
    """Inline sibling ``<script src=\"relative.js\">`` tags from the workspace disk."""
    from app.domain.helpers import safe_resolve

    def _replace(match: re.Match[str]) -> str:
        src = match.group(2).strip()
        rel = _workspace_relative_asset_path(
            src,
            workspace_root=workspace_root,
            html_disk_path=html_disk_path,
        )
        if not rel:
            return match.group(0)
        try:
            target = safe_resolve(workspace_root, rel)
            if not target.is_file():
                return match.group(0)
            content = target.read_text(encoding="utf-8")
        except (OSError, ValueError, UnicodeDecodeError):
            return match.group(0)
        escaped = content.replace("</script>", "<\\/script>")
        return f"<script>\n/* workspace:{rel} */\n{escaped}\n</script>"

    return _SCRIPT_SRC_RE.sub(_replace, html)


def build_workspace_api_agent_guidance(virtual: str) -> list[str]:
    """Tell agents how to load workspace files from HTML dashboards and tools."""
    virt = (virtual or VIRTUAL_WORKSPACE_ROOT).rstrip("/") or VIRTUAL_WORKSPACE_ROOT
    return [
        "Workspace HTTP API (same-origin; auth handled by the WebUI shell):",
        f"- List files: GET /api/v1/list?workspace={virt}&path=.",
        f"- Read text/JSON: GET /api/v1/file?workspace={virt}&path=<relative-path>",
        f"- Read CSV/binary: GET /api/v1/file/raw?workspace={virt}&path=<relative-path>",
        f"- Open HTML dashboard: GET /api/v1/file/view?workspace={virt}&path=<file.html>",
        "Use paths relative to the workspace root in path= (example: report.csv, "
        "data/summary.json — not /workspace/report.csv).",
        "Composer uploads: ``.uploads/<filename>`` under the account's main workspace "
        f"(list with workspace={VIRTUAL_WORKSPACE_ROOT}&path=.uploads).",
        "For HTML dashboards saved in the workspace, the WebUI injects hermesLoadText() "
        "and hermesLoadJson() helpers (postMessage bridge — works in preview iframe and "
        "Open in browser tabs). Example:",
        "  const csv = await hermesLoadText('report.csv');",
        "  const data = await hermesLoadJson('data/summary.json');",
        "Prefer hermesLoadText/hermesLoadJson in HTML instead of embedding large CSV/JSON "
        "inline or hardcoding host disk paths.",
        "For split HTML+JS dashboards, use relative ``<script src=\"app.js\">`` (same "
        "folder as the HTML file). Do NOT use ``/api/v1/file/app.js`` or "
        "``fetch('/api/v1/file/...')`` — those URLs are wrong and return 401 in "
        "sandboxed preview; the WebUI inlines relative scripts automatically.",
    ]


_WORKSPACE_HTML_BRIDGE_SCRIPT = """<script>
(function () {
  var WS = __HERMES_WS_JSON__;
  window.HERMES_WORKSPACE = WS;
  function bridgeFetch(path) {
    return new Promise(function (resolve, reject) {
      var id = "hf_" + Math.random().toString(36).slice(2);
      var target = window.opener || window.parent;
      if (!target || target === window) {
        reject(new Error("hermesFetch requires the Hermes WebUI preview shell"));
        return;
      }
      function onMsg(ev) {
        var d = ev.data;
        if (!d || d.type !== "hermes-workspace-fetch-response" || d.id !== id) return;
        window.removeEventListener("message", onMsg);
        if (d.ok) {
          resolve({
            text: function () { return Promise.resolve(String(d.body || "")); },
            json: function () { return Promise.resolve(JSON.parse(String(d.body || "null"))); },
          });
        } else {
          reject(new Error(d.error || "workspace fetch failed"));
        }
      }
      window.addEventListener("message", onMsg);
      target.postMessage(
        { type: "hermes-workspace-fetch", id: id, workspace: WS, path: String(path || "") },
        "*"
      );
    });
  }
  window.hermesFetch = bridgeFetch;
  window.hermesLoadText = function (path) {
    return bridgeFetch(path).then(function (r) { return r.text(); });
  };
  window.hermesLoadJson = function (path) {
    return bridgeFetch(path).then(function (r) { return r.json(); });
  };
  function resolveWorkspaceRelPath(src) {
    if (!src) return null;
    if (/^(https?:|\\/\\/|data:|blob:)/i.test(src)) return null;
    if (src.indexOf("/file/") >= 0) {
      var tail = src.split("/file/").pop().split("?")[0].split("#")[0];
      return tail || null;
    }
    if (src.charAt(0) === "/") return null;
    return src;
  }
  function loadRelativeScripts() {
    var nodes = document.querySelectorAll("script[src]");
    Array.prototype.forEach.call(nodes, function (node) {
      var path = resolveWorkspaceRelPath(node.getAttribute("src") || "");
      if (!path) return;
      node.removeAttribute("src");
      hermesLoadText(path).then(function (code) {
        node.textContent = code;
      }).catch(function (err) {
        console.error("hermes workspace script load failed", path, err);
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadRelativeScripts);
  } else {
    loadRelativeScripts();
  }
})();
</script>"""


_WORKSPACE_HTML_SANDBOX_POLYFILL_SCRIPT = """<script>
(function () {
  function memStore() {
    var m = {};
    return {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
      setItem: function (k, v) { m[String(k)] = String(v); },
      removeItem: function (k) { delete m[String(k)]; },
      clear: function () { m = {}; },
      key: function (i) { var keys = Object.keys(m); return keys[i] || null; },
      get length() { return Object.keys(m).length; },
    };
  }
  function patchStorage(name) {
    try {
      var s = window[name];
      var probe = "__hermes_preview_probe__";
      s.setItem(probe, "1");
      s.removeItem(probe);
    } catch (e) {
      try {
        Object.defineProperty(window, name, { value: memStore(), configurable: true });
      } catch (e2) {
        window[name] = memStore();
      }
    }
  }
  patchStorage("localStorage");
  patchStorage("sessionStorage");
})();
</script>"""


def inject_workspace_html_preview_enhancements(
    raw: bytes,
    *,
    workspace_virtual: str | None = None,
    workspace_disk_root: Path | None = None,
    html_disk_path: Path | None = None,
) -> bytes:
    """Inject preview helpers into workspace HTML (base target + optional fetch bridge)."""
    base = '<base target="_blank">'
    bridge = ""
    text = raw.decode("utf-8", errors="replace")
    if workspace_disk_root is not None and html_disk_path is not None:
        text = _inline_workspace_relative_scripts(
            text,
            workspace_root=workspace_disk_root,
            html_disk_path=html_disk_path,
        )
    if workspace_virtual:
        import json

        bridge = _WORKSPACE_HTML_BRIDGE_SCRIPT.replace(
            "__HERMES_WS_JSON__",
            json.dumps(str(workspace_virtual)),
        )
    inject = base + _WORKSPACE_HTML_SANDBOX_POLYFILL_SCRIPT + bridge
    if re.search(r"<head(?:\s[^>]*)?>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"(<head\b[^>]*>)",
            r"\1" + inject,
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    elif re.search(r"<!doctype[^>]*>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"(<!doctype[^>]*>)",
            r"\1<head>" + inject + "</head>",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        text = "<head>" + inject + "</head>" + text
    return text.encode("utf-8")


def build_virtual_workspace_path(name: str, parent: str | None = None) -> str:
    """Build ``/workspace/<segments>`` from a display name and optional parent virtual path."""
    segment = (name or '').strip().strip('/')
    if not segment or '/' in segment or segment in {'.', '..'}:
        raise ValueError("workspace name is required and must be a single path segment")
    parent_token = str(parent or VIRTUAL_WORKSPACE_ROOT).strip() or VIRTUAL_WORKSPACE_ROOT
    if not is_virtual_workspace_path(parent_token):
        raise ValueError(f"parent must be a virtual workspace path under {VIRTUAL_WORKSPACE_ROOT}")
    if parent_token == VIRTUAL_WORKSPACE_ROOT:
        return f"{VIRTUAL_WORKSPACE_ROOT}/{segment}"
    return f"{parent_token.rstrip('/')}/{segment}"


def build_workspace_agent_system_message(
    workspace_disk: str | Path,
    *,
    profile_home: Path | None = None,
) -> str:
    """Describe the active workspace for agent file/terminal tools.

    Nested multi-user workspaces expose virtual ``/workspace/...`` paths in the
    UI registry, but shell commands run with ``TERMINAL_CWD`` already set to
    the resolved on-disk directory. Models often emit ``mkdir -p /workspace/...``
    even though that is not a reliable shell alias on the server filesystem.
    """
    token = str(workspace_disk or "").strip()
    try:
        disk_resolved = Path(token).expanduser().resolve()
    except OSError:
        disk_resolved = Path(token).expanduser()
    disk_text = str(disk_resolved)

    if nested_workspaces_enabled():
        virtual = agent_facing_workspace_path(
            disk_resolved,
            profile_home=profile_home,
        )
        lines = [
            f"Active workspace: {virtual}",
            "Every user message is prefixed with [Workspace::v1: ...] showing the same "
            "workspace at send time. That tag overrides any prior workspace mention "
            "in memory or history.",
            "Use this workspace path everywhere — file tools, terminal, and "
            "execute_code. Examples: "
            f"{virtual}/report.csv, report.csv, or ./report.csv.",
            "Chat composer uploads are stored under ``.uploads/<filename>`` in "
            "the account's main workspace (example: ``.uploads/report.xlsx`` or "
            f"{VIRTUAL_WORKSPACE_ROOT}/.uploads/report.xlsx) — shared across nested "
            "sub-workspaces. Read them with file tools or execute_code — do not use "
            "the legacy webui attachment inbox path.",
            "Never use host paths (/home/..., /app, /tmp, /etc) or filesystem root /.",
            "TERMINAL_CWD is already set to this workspace; do not cd to / or "
            "other host directories.",
            "Virtual ``/workspace/...`` paths in tool arguments are rewritten to "
            "the active on-disk workspace automatically.",
            "In execute_code Python, ``pd.read_csv('/workspace/report.csv')`` and "
            "similar ``/workspace/...`` strings are rewritten before run — keep "
            "using ``/workspace/...``; do not fall back to host paths or tell the "
            "user that ``/workspace/`` is invalid. Relative ``report.csv`` also "
            "works because TERMINAL_CWD is the workspace.",
            "If containment errors mention filesystem root ``/`` (not "
            "``/workspace/...``), the cause is usually a quoted ``\"/\"`` in "
            "``split(\"/\")``/``join`` — refactor or use relative paths; "
            "``/workspace/file.csv`` is not the problem.",
            "Do not emit ``MEDIA:`` tokens in user-facing replies. The React "
            "chat UI does not render them; use the ``present_files`` tool (or "
            "describe the filename in plain text) when sharing generated files.",
            "``terminal`` and ``execute_code`` share the same virtualenv "
            "(VIRTUAL_ENV + PATH). Install Python packages with "
            "``python -m pip install <pkg>`` (no absolute ``/app/venv/...`` "
            "paths) so both tools can import them.",
        ]
        lines.extend(build_workspace_api_agent_guidance(virtual))
    else:
        lines = [
            f"Active workspace directory (TERMINAL_CWD): {disk_text}",
            "Every user message is prefixed with [Workspace::v1: ...] showing the same "
            "absolute directory at send time. That tag overrides any prior workspace "
            "mention in memory or history.",
            "Always use the most recent [Workspace::v1: ...] tag as the default "
            "working directory for write_file, read_file, search_files, "
            "terminal, and patch.",
            "Never fall back to a hardcoded path when this tag is present.",
            "Chat composer uploads are stored under ``.uploads/<filename>`` in "
            "TERMINAL_CWD (example: ``.uploads/report.xlsx``). Read them with "
            "file tools or execute_code — never use ``~/.hermes/webui/attachments`` "
            "or other host paths outside the workspace.",
        ]

    return "\n".join(lines)


def _workspaces_file_for_profile_home(profile_home: Path, *, access: Any = None) -> Path:
    return _resolve_state_dir_for_profile_home(profile_home, access=access) / "workspaces.json"


def _nested_root_display_name(
    profile_home: Path,
    *,
    access: Any = None,
    display_name: str | None = None,
) -> str:
    """Return the picker label for the virtual ``/workspace`` root entry."""
    if display_name:
        return display_name
    if access is None:
        access = get_request_user_access()
    slug = _account_workspace_slug_for_access(access)
    if slug:
        return slug
    profile_name = _named_profile_name(profile_home)
    if profile_name:
        return profile_name
    bound = str(getattr(access, 'profile_name', None) or '').strip()
    if bound and bound != 'default':
        return bound
    return profile_workspace_display_name()


def _ensure_nested_root_entry(
    workspaces: list,
    *,
    profile_home: Path,
    display_name: str | None = None,
    access: Any = None,
) -> list:
    """Ensure the virtual root entry exists and normalize legacy absolute paths."""
    if access is None:
        access = get_request_user_access()
    root_name = _nested_root_display_name(
        profile_home,
        access=access,
        display_name=display_name,
    )
    root_entry = {'path': VIRTUAL_WORKSPACE_ROOT, 'name': root_name}
    normalized: list[dict] = []
    seen_root = False
    canonical = profile_workspace_dir(profile_home, access=access).resolve()

    for item in workspaces or []:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get('path') or '').strip()
        entry_name = str(item.get('name') or '').strip() or root_name
        virtual_path = raw_path
        if is_virtual_workspace_path(raw_path):
            virtual_path = raw_path
        else:
            mapped = None
            try:
                resolved = resolve_profile_workspace(
                    raw_path,
                    profile_home,
                    access=access,
                )
                mapped = disk_path_to_virtual(resolved, profile_home)
                if mapped:
                    virtual_path = mapped
                elif resolved.is_dir():
                    normalized.append(
                        {
                            'path': str(resolved.resolve()),
                            'name': entry_name,
                        }
                    )
                    continue
            except Exception:
                mapped = None
            if not mapped:
                continue
        if virtual_path == VIRTUAL_WORKSPACE_ROOT:
            root_entry['name'] = root_name
            seen_root = True
            continue
        try:
            disk = virtual_path_to_disk(virtual_path, profile_home)
            disk.relative_to(canonical)
        except (OSError, ValueError):
            continue
        normalized.append({'path': virtual_path, 'name': entry_name})

    if not seen_root:
        pass
    result = [root_entry, *normalized]
    # De-dupe by virtual path while preserving order.
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in result:
        key = item['path']
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def load_workspaces_for_profile(profile_home: Path, *, access: Any = None) -> list:
    """Load workspace registry entries for a specific profile home (side-effect free)."""
    profile_home = profile_home.expanduser().resolve()
    try:
        ws_file = _workspaces_file_for_profile_home(profile_home, access=access)
        if ws_file.exists():
            try:
                raw = json.loads(ws_file.read_text(encoding="utf-8"))
            except Exception:
                raw = []
        else:
            raw = []
    except OSError:
        logger.debug(
            "Cannot read workspaces registry for profile home %s",
            profile_home,
            exc_info=True,
        )
        raw = []
    if nested_workspaces_enabled():
        return _ensure_nested_root_entry(raw if isinstance(raw, list) else [], profile_home=profile_home)
    cleaned = _clean_workspace_list(raw if isinstance(raw, list) else [])
    return _normalize_to_single_profile_workspace(cleaned)


def save_workspaces_for_profile(profile_home: Path, workspaces: list, *, access: Any = None) -> None:
    profile_home = profile_home.expanduser().resolve()
    state_dir = _state_dir_for_profile_home(profile_home, access=access)
    ws_file = state_dir / "workspaces.json"
    if nested_workspaces_enabled():
        payload = _ensure_nested_root_entry(workspaces, profile_home=profile_home)
    else:
        payload = workspaces
    ws_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def add_nested_workspace(
    *,
    name: str,
    parent: str | None = None,
    profile_home: Path | None = None,
    create: bool = True,
) -> dict:
    """Register a nested workspace under the profile root and optionally create its directory."""
    if profile_home is None:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
        except ImportError:
            profile_home = Path.home()
    profile_home = profile_home.expanduser().resolve()
    if not nested_workspaces_enabled():
        raise ValueError("Nested workspaces are only available in multi-user mode")
    virtual_path = build_virtual_workspace_path(name, parent)
    disk = virtual_path_to_disk(virtual_path, profile_home)
    if create:
        disk.mkdir(parents=True, exist_ok=True)
    access_error = _workspace_access_error(disk)
    if access_error:
        raise ValueError(access_error)
    workspaces = load_workspaces_for_profile(profile_home)
    if any(item.get('path') == virtual_path for item in workspaces):
        raise ValueError("Workspace already in list")
    nested_count = sum(1 for item in workspaces if item.get('path') != VIRTUAL_WORKSPACE_ROOT)
    if nested_count >= MAX_NESTED_WORKSPACES_PER_PROFILE:
        raise ValueError(
            f"Maximum nested workspaces per profile is {MAX_NESTED_WORKSPACES_PER_PROFILE}"
        )
    entry = {'path': virtual_path, 'name': (name or '').strip() or disk.name}
    workspaces.append(entry)
    save_workspaces_for_profile(profile_home, workspaces)
    return entry


def remove_nested_workspace(
    virtual_path: str,
    *,
    profile_home: Path | None = None,
) -> list:
    """Remove a nested workspace registry entry (never removes the virtual root)."""
    token = str(virtual_path or '').strip()
    if token in ('', VIRTUAL_WORKSPACE_ROOT):
        raise ValueError("The profile workspace root cannot be removed")
    if not is_virtual_workspace_path(token):
        raise ValueError("Only virtual workspace paths can be removed in nested mode")
    if profile_home is None:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
        except ImportError:
            profile_home = Path.home()
    profile_home = profile_home.expanduser().resolve()
    workspaces = load_workspaces_for_profile(profile_home)
    kept = [item for item in workspaces if item.get('path') != token]
    if len(kept) == len(workspaces):
        raise ValueError("Workspace not found")
    save_workspaces_for_profile(profile_home, kept)
    return kept


def format_workspace_api_entry(
    item: dict,
    *,
    profile_home: Path,
    include_disk_path: bool = False,
) -> dict:
    """Shape a workspace row for API responses (virtual paths for nested mode)."""
    path = str(item.get('path') or '').strip()
    name = str(item.get('name') or '').strip()
    out: dict = {'path': path, 'name': name or path}
    parent = item.get('parent')
    if isinstance(parent, str) and parent.strip():
        out['parent'] = parent.strip()
    depth = 0
    if is_virtual_workspace_path(path) and path != VIRTUAL_WORKSPACE_ROOT:
        depth = len(_virtual_relative_segment(path).split('/'))
    out['depth'] = depth
    if nested_workspaces_enabled() and is_virtual_workspace_path(path):
        try:
            out['disk_path'] = str(virtual_path_to_disk(path, profile_home).resolve())
        except (OSError, ValueError):
            pass
    return out


def profile_workspace_rel() -> str:
    """Return the configured profile workspace path (relative or absolute).

    Resolution order:
      1. HERMES_WEBUI_PROFILE_WORKSPACE
      2. HERMES_WEBUI_DEFAULT_WORKSPACE
      3. ./workspace
    """
    for key in ('HERMES_WEBUI_PROFILE_WORKSPACE', 'HERMES_WEBUI_DEFAULT_WORKSPACE'):
        value = os.getenv(key, '').strip()
        if value:
            return value
    return _DEFAULT_PROFILE_WORKSPACE_REL


def profile_workspace_display_name() -> str:
    """Return the default display name for a profile workspace entry."""
    return os.getenv('HERMES_WEBUI_WORKSPACE_NAME', _DEFAULT_PROFILE_WORKSPACE_NAME).strip() or _DEFAULT_PROFILE_WORKSPACE_NAME



def _profile_workspace_aliases() -> set[str]:
    rel = profile_workspace_rel()
    aliases = {'', rel, 'workspace', './workspace', _DEFAULT_PROFILE_WORKSPACE_REL}
    if rel.startswith('./'):
        aliases.add(rel[2:])
    elif not Path(rel).expanduser().is_absolute():
        aliases.add(f'./{rel}')
    return aliases


def _default_hermes_home() -> Path | None:
    try:
        from app.domain.profiles import _DEFAULT_HERMES_HOME
        return _DEFAULT_HERMES_HOME.expanduser().resolve()
    except ImportError:
        raw = os.getenv('HERMES_HOME', '').strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return None


def _named_profile_name(profile_home: Path) -> str | None:
    """Return the profile segment for ``{hermes_home}/profiles/<name>`` homes."""
    profile_home = profile_home.expanduser().resolve()
    hermes_home = _default_hermes_home()
    if hermes_home is None or profile_home == hermes_home:
        return None
    try:
        rel = profile_home.relative_to(hermes_home)
    except ValueError:
        return None
    if len(rel.parts) == 2 and rel.parts[0] == 'profiles':
        return rel.parts[1]
    return None


def _shared_workspace_root(hermes_home: Path) -> Path:
    """Return the shared workspace root under Hermes home (e.g. ``~/.hermes/workspace``)."""
    rel = profile_workspace_rel()
    candidate = Path(rel).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if rel.startswith('./'):
        return (hermes_home / rel[2:]).resolve()
    return (hermes_home / rel).resolve()


def _maybe_remap_legacy_profile_workspace(path: Path, profile_home: Path) -> Path:
    """Map old ``profiles/<name>/workspace`` paths to the shared mount subdir."""
    profile_name = _named_profile_name(profile_home)
    hermes_home = _default_hermes_home()
    if not profile_name or not hermes_home:
        return path
    try:
        legacy = (profile_home / 'workspace').resolve()
        if path.resolve() == legacy:
            return (_shared_workspace_root(hermes_home) / profile_name).resolve()
    except OSError:
        pass
    return path


def _maybe_remap_shared_root_default_subdir(candidate: Path) -> Path:
    """Remap ``{shared_root}/default`` to ``{shared_root}`` when the subdir is absent.

    The root/default profile's canonical workspace is the shared mount root
    (``~/.hermes/workspace`` in Docker), not ``.../workspace/default``. Stale
    sessions, ``last_workspace.txt``, or virtual ``/workspace/default`` paths
    sometimes reference the ``default`` suffix even though the host directory is
    bind-mounted directly onto the shared root. When the subdir is missing but
    the mount root exists, treat the request as the root workspace instead of
    failing with ``Path does not exist``.

    A real on-disk nested folder named ``default``, or a registered nested
    workspace entry that resolves to this path, is left unchanged.
    """
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return candidate
    try:
        shared_root = _shared_workspace_root(hermes_home).resolve()
        resolved = candidate.expanduser().resolve()
        default_subdir = (shared_root / "default").resolve()
    except OSError:
        return candidate
    if resolved != default_subdir:
        return candidate
    if default_subdir.is_dir():
        return candidate
    if not shared_root.is_dir():
        return candidate
    try:
        root_canonical = profile_workspace_dir(hermes_home).resolve()
    except OSError:
        return candidate
    if root_canonical != shared_root:
        return candidate
    if nested_workspaces_enabled():
        try:
            workspaces = load_workspaces_for_profile(hermes_home)
        except Exception:
            workspaces = []
        for item in workspaces:
            raw = str(item.get("path") or "").strip()
            if not raw:
                continue
            if raw in ("/workspace/default", str(default_subdir)):
                return candidate
            try:
                if is_virtual_workspace_path(raw):
                    disk = virtual_path_to_disk(raw, hermes_home).resolve()
                    if disk == default_subdir:
                        return candidate
            except (OSError, ValueError):
                continue
    return shared_root


def _uses_shared_workspace_layout(rel: str) -> bool:
    token = rel.strip()
    return token in ('', 'workspace', './workspace', _DEFAULT_PROFILE_WORKSPACE_REL)


def _resolve_canonical_profile_workspace(
    profile_home: Path,
    *,
    access: Any = None,
) -> Path:
    if access is None:
        access = get_request_user_access()
    account_slug = _account_workspace_slug_for_access(access)
    rel = profile_workspace_rel()
    candidate = Path(rel).expanduser()
    if candidate.is_absolute():
        base = candidate.resolve()
        if account_slug:
            try:
                from app.domain.users import is_multi_user_enabled

                if is_multi_user_enabled():
                    return (base / account_slug).resolve()
            except ImportError:
                return (base / account_slug).resolve()
        return base

    hermes_home = _default_hermes_home()
    profile_name = account_slug or _named_profile_name(profile_home)
    if hermes_home is not None and _uses_shared_workspace_layout(rel):
        if profile_name:
            # Named profiles share the bind-mounted workspace root:
            # HERMES_WORKSPACE -> {hermes_home}/workspace/{profile_name}
            return (_shared_workspace_root(hermes_home) / profile_name).resolve()
        return _shared_workspace_root(hermes_home).resolve()

    if rel.startswith('./'):
        return (profile_home / rel[2:]).resolve()
    return (profile_home / rel).resolve()


def resolve_profile_workspace(
    raw: str | Path | None,
    profile_home: Path | None = None,
    *,
    access: Any = None,
) -> Path:
    """Resolve a workspace path against *profile_home* when relative."""
    if access is None:
        access = get_request_user_access()
    if profile_home is None:
        profile_home = _profile_home_for_workspace_access(access)
        if profile_home is None:
            try:
                from app.domain.profiles import get_active_hermes_home
                profile_home = get_active_hermes_home()
            except ImportError:
                profile_home = Path.home()
    profile_home = profile_home.expanduser().resolve()
    token = str(raw or '').strip()
    if is_virtual_workspace_path(token):
        return virtual_path_to_disk(token, profile_home)
    if token in _profile_workspace_aliases():
        return _resolve_canonical_profile_workspace(profile_home, access=access)
    candidate = Path(token).expanduser()
    if candidate.is_absolute():
        return _maybe_remap_legacy_profile_workspace(candidate, profile_home).resolve()
    return (profile_home / candidate).resolve()


def profile_workspace_dir(profile_home: Path, *, access: Any = None) -> Path:
    """Return the resolved workspace directory for a profile."""
    if access is None:
        access = get_request_user_access()
    return _resolve_canonical_profile_workspace(profile_home, access=access)


def _workspace_deletion_allowed(path: Path, profile_home: Path) -> bool:
    """Return True when *path* is a profile-owned workspace directory."""
    try:
        resolved = path.resolve()
        profile_home = profile_home.resolve()
    except OSError:
        return False

    hermes_home = _default_hermes_home()
    if hermes_home is not None and profile_home == hermes_home:
        try:
            if resolved == _shared_workspace_root(hermes_home).resolve():
                return False
        except OSError:
            pass

    try:
        resolved.relative_to(profile_home)
        return True
    except ValueError:
        pass

    try:
        if resolved == profile_workspace_dir(profile_home).resolve():
            return True
    except OSError:
        pass

    return False


def clear_profile_workspaces_registry(profile_home: Path) -> None:
    """Remove per-profile workspaces.json and last_workspace.txt when tearing down."""
    profile_home = profile_home.expanduser().resolve()
    state_dir = profile_home / "webui_state"
    for filename in ("workspaces.json", "last_workspace.txt"):
        path = state_dir / filename
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove %s", path, exc_info=True)


def delete_profile_workspace(profile_home: Path) -> list[str]:
    """Best-effort removal of workspace directories owned by *profile_home*."""
    profile_home = profile_home.expanduser().resolve()
    deleted: list[str] = []
    candidates: list[Path] = []

    try:
        candidates.append(profile_workspace_dir(profile_home))
    except OSError:
        logger.debug("Could not resolve profile workspace dir", exc_info=True)

    legacy = profile_home / 'workspace'
    if legacy not in candidates:
        candidates.append(legacy)

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)

        if not path.is_dir():
            continue
        if not _workspace_deletion_allowed(path, profile_home):
            logger.warning(
                "Skipping profile workspace deletion outside allowed roots: %s",
                path,
            )
            continue

        shutil.rmtree(path)
        deleted.append(str(path.resolve()))

    return deleted


def _resolve_state_dir_for_profile_home(profile_home: Path, *, access: Any = None) -> Path:
    """Return the webui state directory path without creating directories."""
    profile_home = profile_home.expanduser().resolve()
    if access is None:
        access = get_request_user_access()
    account_slug = _account_workspace_slug_for_access(access)
    hermes_home = _default_hermes_home()
    if account_slug and hermes_home is not None:
        return hermes_home / "users" / account_slug / "webui_state"
    try:
        from app.domain.profiles import _DEFAULT_HERMES_HOME
        if profile_home == _DEFAULT_HERMES_HOME.resolve():
            return _GLOBAL_WS_FILE.parent
    except ImportError:
        logger.debug("Failed to import profiles for state-dir resolution")
    return profile_home / "webui_state"


def _state_dir_for_profile_home(profile_home: Path, *, access: Any = None) -> Path:
    """Return the webui state directory for a given profile home path."""
    state_dir = _resolve_state_dir_for_profile_home(profile_home, access=access)
    ensure_directory_writable(state_dir)
    return state_dir


def ensure_profile_workspace(
    profile_home: Path,
    *,
    name: str | None = None,
    access: Any = None,
) -> dict:
    """Create and persist the single workspace entry for *profile_home*."""
    profile_home = profile_home.expanduser().resolve()
    if access is None:
        access = get_request_user_access()
    ws_dir = profile_workspace_dir(profile_home, access=access)
    ensure_directory_writable(ws_dir)
    rel_path = profile_workspace_rel()
    display_name = _nested_root_display_name(
        profile_home,
        access=access,
        display_name=name,
    )
    if nested_workspaces_enabled():
        entry = {'path': VIRTUAL_WORKSPACE_ROOT, 'name': display_name}
    else:
        entry = {'path': rel_path, 'name': display_name}
    state_dir = _state_dir_for_profile_home(profile_home, access=access)
    ws_file = state_dir / 'workspaces.json'
    ws_file.parent.mkdir(parents=True, exist_ok=True)
    ws_file.write_text(
        json.dumps([entry], ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    lw_file = state_dir / 'last_workspace.txt'
    lw_file.write_text(rel_path, encoding='utf-8')
    return entry


def _normalize_to_single_profile_workspace(prior: list | None = None) -> list:
    """Ensure the active profile exposes exactly one auto workspace."""
    try:
        from app.domain.profiles import get_active_hermes_home
        profile_home = get_active_hermes_home()
    except ImportError:
        profile_home = Path.home()

    ws_dir = profile_workspace_dir(profile_home)
    ws_dir.mkdir(parents=True, exist_ok=True)
    rel_path = profile_workspace_rel()
    display_name = profile_workspace_display_name()
    if prior:
        for item in prior:
            item_path = item.get('path')
            if not item_path:
                continue
            try:
                same_path = resolve_profile_workspace(item_path, profile_home) == ws_dir.resolve()
            except (OSError, RuntimeError):
                same_path = item_path == rel_path
            if same_path and item.get('name'):
                display_name = item['name']
                break
    entry = {'path': rel_path, 'name': display_name}
    if prior and len(prior) == 1:
        only = prior[0]
        only_path = only.get('path')
        try:
            paths_match = (
                only_path
                and resolve_profile_workspace(only_path, profile_home) == ws_dir.resolve()
            )
        except (OSError, RuntimeError):
            paths_match = only_path == rel_path
        if paths_match and only.get('name') == display_name:
            return [entry]
    ensure_profile_workspace(profile_home, name=display_name)
    return [entry]


def _profile_state_dir() -> Path:
    """Return the webui_state directory for the active profile.

    For the default profile, returns the global STATE_DIR (respects
    HERMES_WEBUI_STATE_DIR env var for test isolation).
    For named profiles, returns {profile_home}/webui_state/.
    Multi-user regular accounts use {HERMES_HOME}/users/<slug>/webui_state/.
    """
    access = get_request_user_access()
    account_slug = _account_workspace_slug_for_access(access)
    hermes_home = _default_hermes_home()
    if account_slug and hermes_home is not None:
        d = hermes_home / "users" / account_slug / "webui_state"
        d.mkdir(parents=True, exist_ok=True)
        return d
    try:
        from app.domain.profiles import get_active_profile_name, get_active_hermes_home
        name = get_active_profile_name()
        if name and name != 'default':
            d = get_active_hermes_home() / 'webui_state'
            d.mkdir(parents=True, exist_ok=True)
            return d
    except ImportError:
        logger.debug("Failed to import profiles module, using global state dir")
    return _GLOBAL_WS_FILE.parent


def _workspaces_file() -> Path:
    """Return the workspaces.json path for the active profile."""
    return _profile_state_dir() / 'workspaces.json'


def _last_workspace_file() -> Path:
    """Return the last_workspace.txt path for the active profile."""
    return _profile_state_dir() / 'last_workspace.txt'


def _profile_default_workspace() -> str:
    """Read the profile's default workspace from its config.yaml.

    Checks keys in priority order:
      1. 'workspace'         — explicit webui workspace key
      2. 'default_workspace' — alternate explicit key
      3. 'terminal.cwd'      — hermes-agent terminal working dir (most common)

    Falls back to the live DEFAULT_WORKSPACE from app.domain.config.
    """
    try:
        from app.domain.config import get_config
        cfg = get_config()
        # Explicit webui workspace keys first
        for key in ('workspace', 'default_workspace'):
            ws = cfg.get(key)
            if ws:
                p = resolve_profile_workspace(ws)
                if p.is_dir():
                    return str(p)
        # Fall through to terminal.cwd — the agent's configured working directory
        terminal_cfg = cfg.get('terminal', {})
        if isinstance(terminal_cfg, dict):
            cwd = terminal_cfg.get('cwd', '')
            if cwd and str(cwd) not in ('.', ''):
                p = resolve_profile_workspace(cwd)
                if p.is_dir():
                    return str(p)
    except (ImportError, Exception):
        logger.debug("Failed to load profile default workspace config")
    try:
        from app.domain.config import DEFAULT_WORKSPACE as _LIVE_DEFAULT_WORKSPACE

        return str(Path(_LIVE_DEFAULT_WORKSPACE).expanduser().resolve())
    except Exception:
        return str(Path(_BOOT_DEFAULT_WORKSPACE).expanduser().resolve())


# ── Public API ──────────────────────────────────────────────────────────────

def _clean_workspace_list(workspaces: list) -> list:
    """Sanitize a workspace list:
    - Preserve saved paths even when they are currently missing or inaccessible;
      picker state must not be destroyed by a transient stat/permission failure.
    - Remove entries whose paths live inside another profile's directory
      (e.g. ~/.hermes/profiles/X/... should not appear on a different profile).
    - Rename any entry whose name is literally 'default' to 'Home' (avoids
      confusion with the 'default' profile name).
    Returns the cleaned list (may be empty).
    """
    hermes_profiles = (Path.home() / '.hermes' / 'profiles').resolve()
    result = []
    for w in workspaces:
        path = w.get('path', '')
        name = w.get('name', '')
        if not path:
            continue
        try:
            p = resolve_profile_workspace(path)
        except Exception:
            p = _safe_resolve(Path(path).expanduser())
        if nested_workspaces_enabled() and is_virtual_workspace_path(path):
            display_path = path
        else:
            try:
                from app.domain.profiles import get_active_hermes_home
                canonical = profile_workspace_dir(get_active_hermes_home())
                mapped = disk_path_to_virtual(p.resolve(), get_active_hermes_home())
                if nested_workspaces_enabled() and mapped:
                    display_path = mapped
                else:
                    display_path = (
                        profile_workspace_rel()
                        if p.resolve() == canonical.resolve()
                        else str(p)
                    )
            except Exception:
                display_path = str(p)
        # Skip paths inside a DIFFERENT profile's directory (cross-profile leak).
        # Allow paths inside the CURRENT profile's own directory (e.g. test workspaces
        # created under ~/.hermes/profiles/webui/webui-mvp-test/).
        try:
            p.relative_to(hermes_profiles)
            # p is under ~/.hermes/profiles/ — only skip if it's under a DIFFERENT profile
            try:
                from app.domain.profiles import get_active_hermes_home
                own_profile_dir = get_active_hermes_home().resolve()
                p.relative_to(own_profile_dir)
                # p is under our own profile dir — keep it
            except (ValueError, Exception):
                continue  # under profiles/ but not our own — cross-profile leak, skip
        except ValueError:
            pass  # not under profiles/ at all — keep it
        # Rename confusing 'default' label to 'Home'
        if name.lower() == 'default':
            name = 'Home'
        result.append({'path': display_path, 'name': name})
    return result


def _workspace_access_error(candidate: Path, *, missing_label: str = "Path does not exist") -> str | None:
    """Return a user-facing validation error for an unusable workspace path.

    ``Path.exists()`` can collapse permission/stat failures into a generic falsey
    result on some Python/OS combinations, which produced misleading "does not
    exist" messages for macOS/TCC-denied directories.  Probe with ``stat()`` so
    missing paths, non-directories, and permission-denied paths can be reported
    separately.
    """
    try:
        st = candidate.stat()
    except FileNotFoundError:
        return f"{missing_label}: {candidate}"
    except PermissionError as exc:
        return (
            f"Cannot access path: {candidate}. The server process could not inspect "
            f"this directory ({exc}). On macOS, grant Full Disk Access or Files and "
            f"Folders permission to the Hermes/WebUI app or server process, then try again."
        )
    except OSError as exc:
        return f"Cannot access path: {candidate}. The server process could not inspect this path ({exc})."
    if not stat.S_ISDIR(st.st_mode):
        return f"Path is not a directory: {candidate}"
    return None


def _migrate_global_workspaces() -> list:
    """Read the legacy global workspaces.json, clean it, and return the result.

    This is the migration path for users upgrading from a pre-profile version:
    their global file may contain cross-profile entries, test artifacts, and
    stale paths accumulated over time.  We clean it in-place and rewrite it.
    """
    if not _GLOBAL_WS_FILE.exists():
        return []
    try:
        raw = json.loads(_GLOBAL_WS_FILE.read_text(encoding='utf-8'))
        cleaned = _clean_workspace_list(raw)
        if len(cleaned) != len(raw):
            # Rewrite the cleaned version so future reads are already clean
            _GLOBAL_WS_FILE.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        return cleaned
    except Exception:
        return []


def load_workspaces() -> list:
    try:
        from app.domain.profiles import get_active_hermes_home

        profile_home = get_active_hermes_home()
    except ImportError:
        profile_home = Path.home()
    if nested_workspaces_enabled():
        workspaces = load_workspaces_for_profile(profile_home)
        try:
            ws_file = _workspaces_file()
            if ws_file.exists():
                raw = json.loads(ws_file.read_text(encoding='utf-8'))
                if raw != workspaces:
                    save_workspaces(workspaces)
        except Exception:
            logger.debug("Failed to persist normalized nested workspace list")
        return workspaces
    ws_file = _workspaces_file()
    if ws_file.exists():
        try:
            raw = json.loads(ws_file.read_text(encoding='utf-8'))
            cleaned = _clean_workspace_list(raw)
            normalized = _normalize_to_single_profile_workspace(cleaned)
            if normalized != raw:
                # Persist normalized list so on-disk state matches the single-profile contract
                try:
                    ws_file.write_text(
                        json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8'
                    )
                except Exception:
                    logger.debug("Failed to persist normalized workspace list")
            return normalized
        except Exception:
            logger.debug("Failed to load workspaces from %s", ws_file)
    # No profile-local file yet.
    # For the DEFAULT profile: migrate from the legacy global file (one-time cleanup).
    # For NAMED profiles: always start clean with just their own workspace.
    try:
        from app.domain.profiles import get_active_profile_name
        is_default = get_active_profile_name() in ('default', None)
    except ImportError:
        is_default = True
    if is_default:
        migrated = _migrate_global_workspaces()
        if migrated:
            return _normalize_to_single_profile_workspace(migrated)
    return _normalize_to_single_profile_workspace(None)


def save_workspaces(workspaces: list) -> None:
    try:
        from app.domain.profiles import get_active_hermes_home

        profile_home = get_active_hermes_home()
    except ImportError:
        profile_home = Path.home()
    if nested_workspaces_enabled():
        save_workspaces_for_profile(profile_home, workspaces)
        return
    ws_file = _workspaces_file()
    ws_file.parent.mkdir(parents=True, exist_ok=True)
    ws_file.write_text(json.dumps(workspaces, ensure_ascii=False, indent=2), encoding='utf-8')


def get_last_workspace() -> str:
    access = get_request_user_access()

    def _normalize_last_workspace_token(token: str) -> str:
        cleaned = str(token or "").strip()
        if not cleaned:
            return cleaned
        if nested_workspaces_enabled() and is_virtual_workspace_path(cleaned):
            try:
                resolved = resolve_profile_workspace(cleaned)
            except (OSError, ValueError, RuntimeError):
                return VIRTUAL_WORKSPACE_ROOT
            if resolved.is_dir():
                return cleaned
            return VIRTUAL_WORKSPACE_ROOT
        try:
            resolved = resolve_profile_workspace(cleaned)
        except (OSError, ValueError, RuntimeError):
            return cleaned
        if not resolved.is_dir():
            return cleaned
        if nested_workspaces_enabled():
            mapped = disk_path_to_virtual(resolved, access=access)
            if mapped:
                return mapped
            containment = account_workspace_containment_root(access=access)
            if containment is not None:
                coerced = _coerce_to_account_workspace(
                    resolved,
                    access=access,
                    raw=cleaned,
                )
                if coerced.resolve() == containment.resolve():
                    return VIRTUAL_WORKSPACE_ROOT
        return str(resolved)

    lw_file = _last_workspace_file()
    if lw_file.exists():
        try:
            p = lw_file.read_text(encoding='utf-8').strip()
            if p:
                return _normalize_last_workspace_token(p)
        except Exception:
            logger.debug("Failed to read last workspace from %s", lw_file)
    # Fallback: try global file (legacy single-user only — skip for scoped accounts)
    if not _account_workspace_isolation_enabled(access) and _GLOBAL_LW_FILE.exists():
        try:
            p = _GLOBAL_LW_FILE.read_text(encoding='utf-8').strip()
            if p:
                return _normalize_last_workspace_token(p)
        except Exception:
            logger.debug("Failed to read global last workspace")
    default = _profile_default_workspace()
    if _account_workspace_isolation_enabled(access):
        try:
            resolved = resolve_profile_workspace(default)
            containment = account_workspace_containment_root(access=access)
            if containment is not None:
                coerced = _coerce_to_account_workspace(
                    resolved,
                    access=access,
                    raw=default,
                )
                if coerced.resolve() == containment.resolve():
                    return VIRTUAL_WORKSPACE_ROOT
        except (OSError, ValueError, RuntimeError):
            return VIRTUAL_WORKSPACE_ROOT
    return default


def set_last_workspace(path: str) -> None:
    try:
        lw_file = _last_workspace_file()
        lw_file.parent.mkdir(parents=True, exist_ok=True)
        lw_file.write_text(str(path), encoding='utf-8')
    except Exception:
        logger.debug("Failed to set last workspace")


def _safe_resolve(p: Path) -> Path:
    """Path.resolve() that never raises — falls back to the input path on error."""
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p


def _known_profile_homes() -> list[tuple[Path, str | None]]:
    """Enumerate ``(home, profile_name)`` for every known profile.

    The picker needs to list a workspace per profile, so this resolves every
    profile's Hermes home without mutating any process state. Sources, merged
    and de-duplicated by resolved home path:

      * the default/root profile (``~/.hermes`` itself),
      * the canonical enumerator ``list_profiles_api()`` (same source the
        Profiles panel uses), and
      * a filesystem scan of ``~/.hermes/profiles/*`` as a fallback for
        deployments where ``hermes_cli`` is not importable.
    """
    homes: list[tuple[Path, str | None]] = []
    seen: set[str] = set()

    def add(home: Path | None, name: str | None) -> None:
        if home is None:
            return
        try:
            resolved = home.expanduser().resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        homes.append((resolved, name))

    hermes_home = _default_hermes_home()
    if hermes_home is not None:
        add(hermes_home, 'default')

    try:
        from app.domain.profiles import get_hermes_home_for_profile, list_profiles_api
        for entry in list_profiles_api():
            name = entry.get('name')
            try:
                home = get_hermes_home_for_profile(name) if name else None
            except Exception:
                home = None
            add(home, name)
    except Exception:
        logger.debug("Failed to enumerate profiles via list_profiles_api", exc_info=True)

    if hermes_home is not None:
        profiles_root = hermes_home / 'profiles'
        try:
            children = sorted(profiles_root.iterdir())
        except OSError:
            children = []
        for child in children:
            if child.is_dir():
                add(child, child.name)

    return homes


def _user_access_for_account(
    email: str,
    profile_names: list[str] | None = None,
    *,
    primary_profile_name: str | None = None,
) -> tuple[Any, contextvars.Token]:
    """Build request access + context token for account-scoped workspace reads."""
    from app.domain.users import UserAccess, profile_name_from_email

    cleaned = str(email or "").strip().lower()
    slug = profile_name_from_email(cleaned)
    names = [str(n).strip() for n in (profile_names or []) if str(n).strip()]
    if not names:
        names = [slug]
    primary = str(primary_profile_name or "").strip() or names[0]
    if primary not in names:
        names = [primary, *names]
    access = UserAccess(
        multi_user_enabled=True,
        user_id=cleaned,
        username=cleaned,
        role="user",
        profile_name=primary,
        profile_names=tuple(names),
    )
    return access, set_request_user_access(access)


def _admin_workspace_display_path(
    disk: Path,
    profile_home: Path,
    *,
    access: Any = None,
) -> str:
    """Format a workspace path for the admin Users table (virtual when nested)."""
    try:
        resolved = disk.expanduser().resolve()
    except OSError:
        resolved = disk
    if nested_workspaces_enabled():
        try:
            virtual = disk_path_to_virtual(resolved, profile_home)
            if virtual:
                return virtual
        except (OSError, ValueError):
            pass
    hermes_home = _default_hermes_home()
    if hermes_home is not None:
        try:
            return resolved.relative_to(hermes_home.resolve()).as_posix()
        except ValueError:
            pass
    return str(resolved)


def sync_assigned_profile_workspaces_into_account(
    owner_email: str,
    profile_names: list[str],
    *,
    primary_profile_name: str | None = None,
) -> None:
    """Ensure the account registry contains the main virtual workspace root.

    Each user account owns one main workspace directory. Nested sub-workspaces
    are added separately via ``add_nested_workspace``; legacy profile folders
    under the shared mount are not merged into the registry anymore.
    """
    cleaned = str(owner_email or "").strip().lower()
    names = [str(n).strip() for n in (profile_names or []) if str(n).strip()]
    if not cleaned or not names:
        return
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return
    access, token = _user_access_for_account(
        cleaned,
        names,
        primary_profile_name=primary_profile_name,
    )
    try:
        from app.domain.profiles import get_hermes_home_for_profile

        home = get_hermes_home_for_profile(access.profile_name or names[0])
        try:
            workspaces = load_workspaces_for_profile(home, access=access)
        except (OSError, PermissionError):
            logger.debug(
                "Skipping workspace registry sync for %s",
                cleaned,
                exc_info=True,
            )
            return
        preferred_root_name = _nested_root_display_name(home, access=access)
        known = {
            str(item.get("path") or "").strip()
            for item in workspaces
            if isinstance(item, dict)
        }
        changed = False
        if nested_workspaces_enabled() and VIRTUAL_WORKSPACE_ROOT not in known:
            workspaces.insert(
                0,
                {
                    "path": VIRTUAL_WORKSPACE_ROOT,
                    "name": preferred_root_name,
                },
            )
            changed = True
        elif nested_workspaces_enabled():
            for item in workspaces:
                if not isinstance(item, dict):
                    continue
                if str(item.get("path") or "").strip() != VIRTUAL_WORKSPACE_ROOT:
                    continue
                if str(item.get("name") or "").strip() != preferred_root_name:
                    item["name"] = preferred_root_name
                    changed = True
                break
        if changed:
            save_workspaces_for_profile(home, workspaces)
    finally:
        clear_request_user_access(token)


def list_account_workspaces_for_access(
    access: Any,
    *,
    profile_home: Path | None = None,
) -> list[dict[str, str]]:
    """Return all workspace registry rows for a regular user account."""
    account_slug = _account_workspace_slug_for_access(access)
    if not account_slug:
        return []
    from app.domain.profiles import get_hermes_home_for_profile

    primary = getattr(access, "profile_name", None) or account_slug
    if profile_home is None:
        try:
            profile_home = get_hermes_home_for_profile(primary)
        except Exception:
            logger.debug(
                "Failed to resolve profile home for account workspaces",
                exc_info=True,
            )
            return []

    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, display: str) -> None:
        token = str(display or "").strip()
        if not token or token in seen:
            return
        seen.add(token)
        entries.append(
            {
                "name": str(name or "").strip() or token,
                "path": token,
            }
        )

    registry_token = set_request_user_access(access)
    try:
        for item in load_workspaces_for_profile(profile_home):
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path") or "").strip()
            label = str(item.get("name") or "").strip() or raw_path or "Workspace"
            try:
                if nested_workspaces_enabled() and is_virtual_workspace_path(raw_path):
                    display = raw_path
                elif raw_path:
                    resolved = resolve_profile_workspace(
                        raw_path,
                        profile_home,
                        access=access,
                    )
                    display = _admin_workspace_display_path(
                        resolved,
                        profile_home,
                        access=access,
                    )
                else:
                    resolved = profile_workspace_dir(profile_home, access=access)
                    display = _admin_workspace_display_path(
                        resolved,
                        profile_home,
                        access=access,
                    )
            except (OSError, ValueError, RuntimeError):
                display = raw_path or label
            add(label, display)
        if not entries:
            try:
                resolved = profile_workspace_dir(profile_home, access=access)
                display = _admin_workspace_display_path(
                    resolved,
                    profile_home,
                    access=access,
                )
                add(profile_workspace_display_name() or account_slug, display)
            except OSError:
                pass
    finally:
        clear_request_user_access(registry_token)
    return entries


def assigned_profiles_for_user(profile_names: list[str]) -> list[dict[str, str]]:
    """Return assigned profile ids with on-disk home paths for admin UI links."""
    entries: list[dict[str, str]] = []
    for raw in profile_names:
        name = str(raw or "").strip()
        if not name:
            continue
        path = ""
        try:
            from app.domain.profiles import get_hermes_home_for_profile

            path = str(get_hermes_home_for_profile(name))
        except Exception:
            logger.debug("Failed to resolve profile home for %s", name, exc_info=True)
        entries.append({"name": name, "path": path})
    return entries


def discover_assignable_workspaces_for_user(
    email: str,
    role: str,
    profile_names: list[str] | None = None,
    *,
    primary_profile_name: str | None = None,
) -> list[dict[str, str]]:
    """Return workspace paths an admin may attach to a user account."""
    if str(role or "").strip().lower() != "user":
        return []
    cleaned = str(email or "").strip().lower()
    if not cleaned:
        return []
    from app.domain.users import profile_name_from_email

    account_slug = profile_name_from_email(cleaned)
    names = [str(n).strip() for n in (profile_names or []) if str(n).strip()]
    if not names:
        names = [account_slug]
    primary = str(primary_profile_name or "").strip() or names[0]

    sync_assigned_profile_workspaces_into_account(
        cleaned,
        names,
        primary_profile_name=primary,
    )
    access, token = _user_access_for_account(
        cleaned,
        names,
        primary_profile_name=primary,
    )
    options: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, path: str) -> None:
        token = str(path or "").strip()
        if not token or token in seen:
            return
        seen.add(token)
        options.append(
            {
                "name": str(name or "").strip() or token,
                "path": token,
            }
        )

    try:
        for entry in list_account_workspaces_for_access(access):
            add(entry.get("name", ""), entry.get("path", ""))
    finally:
        clear_request_user_access(token)
    return options


def set_account_workspace_paths_for_user(
    email: str,
    workspace_paths: list[str],
    profile_names: list[str] | None = None,
    *,
    primary_profile_name: str | None = None,
) -> None:
    """Persist the account workspace registry from admin-selected paths.

    Each account keeps one main ``/workspace`` root; nested sub-workspaces are
    preserved from the existing registry and cannot be reassigned here.
    """
    cleaned = str(email or "").strip().lower()
    if not cleaned:
        return
    from app.domain.users import profile_name_from_email

    account_slug = profile_name_from_email(cleaned)
    names = [str(n).strip() for n in (profile_names or []) if str(n).strip()]
    if not names:
        names = [account_slug]
    primary = str(primary_profile_name or "").strip() or names[0]
    access, token = _user_access_for_account(
        cleaned,
        names,
        primary_profile_name=primary,
    )
    try:
        from app.domain.profiles import get_hermes_home_for_profile

        home = get_hermes_home_for_profile(primary)
        existing = load_workspaces_for_profile(home)
        nested_entries = [
            item
            for item in existing
            if isinstance(item, dict)
            and nested_workspaces_enabled()
            and is_virtual_workspace_path(str(item.get("path") or "").strip())
            and str(item.get("path") or "").strip() != VIRTUAL_WORKSPACE_ROOT
        ]
        entries: list[dict[str, str]] = []
        if nested_workspaces_enabled():
            entries.append(
                {
                    "path": VIRTUAL_WORKSPACE_ROOT,
                    "name": profile_workspace_display_name(),
                }
            )
        entries.extend(
            {
                "path": str(item.get("path") or "").strip(),
                "name": str(item.get("name") or "").strip()
                or str(item.get("path") or "").strip(),
            }
            for item in nested_entries
            if str(item.get("path") or "").strip()
        )
        if not entries:
            entries = [
                {
                    "path": VIRTUAL_WORKSPACE_ROOT,
                    "name": profile_workspace_display_name(),
                }
            ]
        save_workspaces_for_profile(home, entries)
    finally:
        clear_request_user_access(token)


def _admin_account_workspace_slug(owner_email: str | None) -> str | None:
    cleaned = str(owner_email or "").strip().lower()
    if not cleaned:
        return None
    from app.domain.users import profile_name_from_email

    return profile_name_from_email(cleaned)


def _admin_shared_mount_meta_path(hermes_home: Path, owner_email: str) -> Path:
    slug = _admin_account_workspace_slug(owner_email)
    if not slug:
        raise ValueError("owner email is required")
    return hermes_home / "users" / slug / "webui_state" / "shared_mount.json"


def _read_admin_shared_mount_folder(
    hermes_home: Path,
    owner_email: str,
) -> str | None:
    slug = _admin_account_workspace_slug(owner_email)
    if not slug:
        return None
    meta = hermes_home / "users" / slug / "webui_state" / "shared_mount.json"
    if not meta.is_file():
        return None
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return None
    folder = str(payload.get("folder") or "").strip()
    return folder or None


def _write_admin_shared_mount_folder(
    hermes_home: Path,
    owner_email: str,
    folder: str,
) -> None:
    segment = _validate_shared_workspace_segment(folder)
    meta = _admin_shared_mount_meta_path(hermes_home, owner_email)
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"folder": segment}), encoding="utf-8")


def _admin_shared_workspace_visible(row: dict[str, str], owner_slug: str) -> bool:
    path = str(row.get("path") or "").strip()
    name = str(row.get("name") or "").strip()
    rel = f"workspace/{owner_slug}"
    return name == owner_slug or path == rel or path.endswith(f"/{owner_slug}")


def _admin_owned_shared_workspace_dirs(
    hermes_home: Path,
    owner_email: str,
) -> set[Path]:
    """Resolved disk directories for an admin account's shared workspace folder."""
    slug = _admin_account_workspace_slug(owner_email)
    if not slug:
        return set()
    root = _shared_workspace_root(hermes_home).resolve()
    owned: set[Path] = set()
    folder_name = _read_admin_shared_mount_folder(hermes_home, owner_email) or slug
    mount_dir = (root / folder_name).resolve()
    if mount_dir.is_dir():
        owned.add(mount_dir)
    canonical = (root / slug).resolve()
    if canonical.is_dir():
        owned.add(canonical)
    ws_file = hermes_home / "users" / slug / "webui_state" / "workspaces.json"
    if ws_file.is_file():
        try:
            from app.domain.profiles import get_hermes_home_for_profile

            profile_home = get_hermes_home_for_profile(slug)
            access, token = _user_access_for_account(
                owner_email,
                [slug],
                primary_profile_name=slug,
            )
            try:
                for item in load_workspaces_for_profile(profile_home):
                    path = str(item.get("path") or "").strip()
                    if not path:
                        continue
                    if is_virtual_workspace_path(path):
                        disk = virtual_path_to_disk(path, profile_home)
                        owned.add(disk.resolve())
            finally:
                clear_request_user_access(token)
        except Exception:
            logger.debug(
                "Failed to resolve admin owned workspace dirs for %s",
                owner_email,
                exc_info=True,
            )
    if not owned:
        owned.add(canonical)
    return owned


def list_admin_shared_workspaces(owner_email: str | None = None) -> list[dict[str, str]]:
    """List top-level folders under the shared workspace mount (admin management UI)."""
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return []
    root = _shared_workspace_root(hermes_home)
    if not root.is_dir():
        return []
    rows: list[dict[str, str]] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            rel = child.relative_to(hermes_home.resolve()).as_posix()
        except ValueError:
            rel = str(child)
        rows.append(
            {
                "name": child.name,
                "path": rel,
                "disk_path": str(child.resolve()),
            }
        )
    if nested_workspaces_enabled() and owner_email:
        owned_dirs = _admin_owned_shared_workspace_dirs(
            hermes_home.resolve(),
            owner_email,
        )
        rows = [
            row
            for row in rows
            if Path(str(row.get("disk_path") or "")).resolve() in owned_dirs
        ]
    return rows


def _validate_shared_workspace_segment(segment: str) -> str:
    token = str(segment or "").strip().strip("/")
    if not token or "/" in token or token in {".", ".."}:
        raise ValueError("workspace name is required and must be a single path segment")
    return token


def _resolve_admin_shared_folder_target(path_or_name: str) -> tuple[Path, Path, Path]:
    """Return (hermes_home, shared_root, target_dir) for an admin-managed folder."""
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        raise ValueError("Hermes home is not configured")
    hermes_home = hermes_home.resolve()
    root = _shared_workspace_root(hermes_home).resolve()
    token = str(path_or_name or "").strip()
    if not token:
        raise ValueError("path is required")
    if is_virtual_workspace_path(token):
        disk = virtual_path_to_disk(token, hermes_home)
        target = disk.resolve()
    elif token.startswith("workspace/"):
        target = (hermes_home / token).resolve()
    elif "/" not in token:
        target = (root / token).resolve()
    else:
        candidate = Path(token).expanduser()
        target = candidate.resolve() if candidate.is_absolute() else (hermes_home / token).resolve()
    if not target.is_dir():
        raise ValueError("workspace folder does not exist")
    if target == root:
        raise ValueError("the shared workspace root cannot be modified")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("workspace is outside the shared mount") from exc
    return hermes_home, root, target


def _workspace_registry_path_aliases(
    hermes_home: Path,
    target: Path,
    *,
    old_segment: str | None = None,
    new_segment: str | None = None,
) -> set[str]:
    """Build path tokens that may appear in account workspace registries."""
    aliases: set[str] = set()
    try:
        rel = target.relative_to(hermes_home).as_posix()
        aliases.add(rel)
    except ValueError:
        aliases.add(str(target))
    aliases.add(str(target.resolve()))
    if nested_workspaces_enabled():
        try:
            virtual = disk_path_to_virtual(target, hermes_home)
            if virtual:
                aliases.add(virtual)
        except (OSError, ValueError):
            pass
    segment = old_segment or target.name
    if segment:
        aliases.add(f"workspace/{segment}")
        if nested_workspaces_enabled():
            aliases.add(f"{VIRTUAL_WORKSPACE_ROOT}/{segment}")
    if new_segment:
        aliases.add(f"workspace/{new_segment}")
        if nested_workspaces_enabled():
            aliases.add(f"{VIRTUAL_WORKSPACE_ROOT}/{new_segment}")
    return {token for token in aliases if token}


def _mutate_account_workspace_registries(
    hermes_home: Path,
    *,
    remove_paths: set[str] | None = None,
    replace_paths: dict[str, str] | None = None,
    replace_names: dict[str, str] | None = None,
) -> None:
    """Update or drop workspace rows in every account ``workspaces.json``."""
    users_root = hermes_home / "users"
    if not users_root.is_dir():
        return
    remove_paths = remove_paths or set()
    replace_paths = replace_paths or {}
    replace_names = replace_names or {}
    for user_dir in users_root.iterdir():
        if not user_dir.is_dir():
            continue
        ws_file = user_dir / "webui_state" / "workspaces.json"
        if not ws_file.is_file():
            continue
        try:
            raw = json.loads(ws_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        changed = False
        kept: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            path_token = str(item.get("path") or "").strip()
            if path_token in remove_paths:
                changed = True
                continue
            if path_token in replace_paths:
                item = dict(item)
                item["path"] = replace_paths[path_token]
                if path_token in replace_names:
                    item["name"] = replace_names[path_token]
                changed = True
            kept.append(item)
        if changed:
            ws_file.write_text(
                json.dumps(kept, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def admin_create_shared_workspace_folder(
    name: str,
    owner_email: str | None = None,
) -> dict[str, str]:
    """Create a new directory under the shared workspace root."""
    if nested_workspaces_enabled() and owner_email:
        raise ValueError(
            "Workspace folders are provisioned per account; create sub-workspaces from the composer"
        )
    segment = _validate_shared_workspace_segment(name)
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        raise ValueError("Hermes home is not configured")
    target = (_shared_workspace_root(hermes_home) / segment).resolve()
    root = _shared_workspace_root(hermes_home).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("workspace path escapes shared root") from exc
    access_error = _workspace_access_error(target, missing_label="Cannot create workspace here")
    if access_error:
        raise ValueError(access_error)
    target.mkdir(parents=True, exist_ok=True)
    if owner_email:
        _write_admin_shared_mount_folder(hermes_home, owner_email, segment)
    rel = target.relative_to(hermes_home.resolve()).as_posix()
    return {"name": segment, "path": rel, "disk_path": str(target)}


def _assert_admin_may_manage_shared_folder(
    path_or_name: str,
    owner_email: str | None,
) -> None:
    if not nested_workspaces_enabled() or not owner_email:
        return
    slug = _admin_account_workspace_slug(owner_email)
    if not slug:
        return
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return
    _hermes_home, _root, target = _resolve_admin_shared_folder_target(path_or_name)
    folder_name = _read_admin_shared_mount_folder(hermes_home, owner_email) or slug
    allowed = (_shared_workspace_root(hermes_home) / folder_name).resolve()
    if target != allowed:
        raise ValueError("Admin may only manage their own workspace folder")


def admin_rename_shared_workspace_folder(
    path_or_name: str,
    new_name: str,
    owner_email: str | None = None,
) -> dict[str, str]:
    """Rename a shared-mount workspace folder and fix account registry references."""
    _assert_admin_may_manage_shared_folder(path_or_name, owner_email)
    new_segment = _validate_shared_workspace_segment(new_name)
    hermes_home, root, target = _resolve_admin_shared_folder_target(path_or_name)
    old_segment = target.name
    if old_segment == new_segment:
        rel = target.relative_to(hermes_home).as_posix()
        return {"name": new_segment, "path": rel, "disk_path": str(target)}
    dest = (root / new_segment).resolve()
    if dest.exists():
        raise ValueError(f"workspace folder {new_segment!r} already exists")
    replace_paths: dict[str, str] = {}
    replace_names: dict[str, str] = {}
    for old in _workspace_registry_path_aliases(
        hermes_home,
        target,
        old_segment=old_segment,
    ):
        if old == str(target.resolve()):
            replace_paths[old] = str(dest.resolve())
            replace_names[replace_paths[old]] = new_segment
        elif old.startswith("workspace/"):
            new_token = f"workspace/{new_segment}"
            replace_paths[old] = new_token
            replace_names[new_token] = new_segment
        elif is_virtual_workspace_path(old):
            suffix = _virtual_relative_segment(old) if old != VIRTUAL_WORKSPACE_ROOT else ""
            if suffix == old_segment:
                new_token = build_virtual_workspace_path(new_segment)
                replace_paths[old] = new_token
                replace_names[new_token] = new_segment
        else:
            try:
                new_rel = dest.relative_to(hermes_home).as_posix()
            except ValueError:
                new_rel = str(dest)
            replace_paths[old] = new_rel
            replace_names[new_rel] = new_segment
    try:
        target.rename(dest)
    except OSError as exc:
        raise ValueError(f"Failed to rename workspace folder: {exc}") from exc
    if owner_email:
        _write_admin_shared_mount_folder(hermes_home, owner_email, new_segment)
    _mutate_account_workspace_registries(
        hermes_home,
        replace_paths=replace_paths,
        replace_names=replace_names,
    )
    rel = dest.relative_to(hermes_home).as_posix()
    return {"name": new_segment, "path": rel, "disk_path": str(dest)}


def admin_delete_shared_workspace_folder(
    path_or_name: str,
    owner_email: str | None = None,
) -> None:
    """Delete a shared-mount workspace folder and drop it from account registries."""
    _assert_admin_may_manage_shared_folder(path_or_name, owner_email)
    hermes_home, _root, target = _resolve_admin_shared_folder_target(path_or_name)
    aliases = _workspace_registry_path_aliases(hermes_home, target)
    _mutate_account_workspace_registries(hermes_home, remove_paths=aliases)
    if target.is_dir():
        shutil.rmtree(target)


def account_workspaces_for_user(
    email: str,
    role: str,
    profile_names: list[str] | None = None,
    *,
    primary_profile_name: str | None = None,
) -> list[dict[str, str]]:
    """List file workspaces owned by the user account (shared across assigned profiles)."""
    if str(role or "").strip().lower() != "user":
        return []
    cleaned = str(email or "").strip().lower()
    if not cleaned:
        return []
    from app.domain.users import profile_name_from_email

    account_slug = profile_name_from_email(cleaned)
    names = [str(n).strip() for n in (profile_names or []) if str(n).strip()]
    if not names:
        names = [account_slug]
    primary = str(primary_profile_name or "").strip() or names[0]

    sync_assigned_profile_workspaces_into_account(
        cleaned,
        names,
        primary_profile_name=primary,
    )
    access, token = _user_access_for_account(
        cleaned,
        names,
        primary_profile_name=primary,
    )
    try:
        entries = list_account_workspaces_for_access(access)
        if not entries:
            fallback = account_workspace_display_for_user(cleaned, "user")
            if fallback:
                entries = [
                    {
                        "name": profile_workspace_display_name() or account_slug,
                        "path": fallback,
                    }
                ]
        return entries
    finally:
        clear_request_user_access(token)


def account_workspace_display_for_user(email: str, role: str) -> str | None:
    """Return a display path for the account-bound workspace (admin user list)."""
    if str(role or "").strip().lower() != "user":
        return None
    cleaned = str(email or "").strip().lower()
    if not cleaned:
        return None
    from app.domain.users import UserAccess, profile_name_from_email

    slug = profile_name_from_email(cleaned)
    access = UserAccess(
        multi_user_enabled=True,
        user_id=cleaned,
        username=cleaned,
        role="user",
        profile_name=slug,
        profile_names=(slug,),
    )
    try:
        from app.domain.profiles import get_hermes_home_for_profile

        profile_home = get_hermes_home_for_profile(slug)
        disk = profile_workspace_dir(profile_home, access=access)
        if nested_workspaces_enabled():
            virtual = disk_path_to_virtual(disk, profile_home)
            if virtual:
                return virtual
        hermes_home = _default_hermes_home()
        if hermes_home is not None:
            try:
                return disk.resolve().relative_to(hermes_home.resolve()).as_posix()
            except ValueError:
                pass
        return disk.resolve().as_posix()
    except OSError:
        logger.debug("Failed to resolve workspace display for %s", cleaned, exc_info=True)
        return f"workspace/{slug}"


def delete_user_account_workspace(email: str) -> None:
    """Remove the shared workspace and registry state for a deleted account."""
    from app.domain.users import profile_name_from_email

    slug = profile_name_from_email(email)
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return
    try:
        ws_dir = (_shared_workspace_root(hermes_home) / slug).resolve()
        if ws_dir.is_dir():
            shutil.rmtree(ws_dir)
    except OSError:
        logger.warning("Failed to delete account workspace %s", slug, exc_info=True)
    user_root = (hermes_home / "users" / slug).resolve()
    if user_root.is_dir():
        try:
            shutil.rmtree(user_root)
        except OSError:
            logger.warning("Failed to delete account webui state %s", slug, exc_info=True)


def _profile_workspace_picker_entry(
    profile_home: Path,
    profile_name: str | None,
    *,
    access: Any = None,
) -> dict | None:
    """Build a picker entry for *profile_home*'s canonical workspace.

    Side-effect free: it resolves the canonical workspace path (which works
    even when the directory does not exist yet) and reads the persisted display
    name. Selecting the workspace later recreates a missing canonical directory
    via :func:`resolve_trusted_workspace` / :func:`ensure_profile_workspace_exists`.
    """
    try:
        ws_dir = profile_workspace_dir(profile_home, access=access)
    except OSError:
        return None
    name = profile_name
    try:
        from app.domain.profiles import _workspace_name_for_home
        name = _workspace_name_for_home(profile_home, profile_name or '')
    except Exception:
        logger.debug("Failed to resolve workspace name for %s", profile_home)
    return {'path': str(ws_dir), 'name': name or ws_dir.name}


def list_all_profile_workspaces(access=None) -> list:
    """Return one workspace entry per known profile for the picker.

    The workspace list endpoint historically returned only the *active*
    profile's single auto-managed workspace (one-workspace-per-profile policy),
    which hid every other profile's workspace from the picker. This aggregates
    each known profile's canonical workspace directory — resolved to an
    absolute path — plus the active profile's own saved entry, de-duplicated by
    resolved path, so the picker can list and switch across profiles.

    When *access* uses the account workspace registry (multi-user users and
    admins with a bound account), return every workspace registered for that
    account. Switching among assigned agent profiles does not change the list.

    Legacy implicit admin sessions and single-user installs still aggregate
    every known profile workspace for the picker.
    """
    if access is not None and _uses_account_workspace_registry(access):
        bound = (
            _account_workspace_slug_for_access(access)
            or getattr(access, "profile_name", None)
            or "default"
        )
        try:
            from app.domain.profiles import get_hermes_home_for_profile

            profile_home = get_hermes_home_for_profile(bound)
        except Exception:
            logger.debug(
                "Failed to resolve bound profile home for %s",
                bound,
                exc_info=True,
            )
            return []
        user_id = str(getattr(access, "user_id", None) or "").strip().lower()
        if user_id:
            try:
                sync_assigned_profile_workspaces_into_account(
                    user_id,
                    list(getattr(access, "profile_names", ()) or ()),
                    primary_profile_name=bound,
                )
            except (OSError, PermissionError):
                logger.debug(
                    "Workspace registry sync failed for account %s",
                    user_id,
                    exc_info=True,
                )
        registry_token = set_request_user_access(access)
        try:
            nested = load_workspaces_for_profile(profile_home, access=access)
        except Exception:
            account_slug = _account_workspace_slug_for_access(access)
            logger.debug(
                "Failed to load account workspaces for %s",
                account_slug or bound,
                exc_info=True,
            )
            nested = []
        finally:
            clear_request_user_access(registry_token)
        if nested_workspaces_enabled() and nested:
            return [
                format_workspace_api_entry(item, profile_home=profile_home)
                for item in nested
            ]
        entry = _profile_workspace_picker_entry(
            profile_home,
            _account_workspace_slug_for_access(access) or bound,
            access=access,
        )
        return [entry] if entry else []

    entries: list[dict] = []
    seen: set[str] = set()

    def add(path: str | Path, name: str) -> None:
        try:
            resolved = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            resolved = Path(str(path))
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        entries.append({'path': key, 'name': name or resolved.name})

    # 1. Active profile's own saved workspace(s), resolved to absolute paths so
    #    the picker can highlight/switch them against the resolved session path
    #    instead of the bare ``./workspace`` placeholder.
    try:
        from app.domain.profiles import get_active_hermes_home
        active_home = get_active_hermes_home()
    except Exception:
        active_home = None
    try:
        for item in load_workspaces():
            raw = item.get('path')
            if not raw:
                continue
            try:
                resolved = resolve_profile_workspace(raw, active_home)
            except Exception:
                resolved = _safe_resolve(Path(str(raw)).expanduser())
            add(resolved, item.get('name', ''))
    except Exception:
        logger.debug("Failed to load active profile workspaces for aggregation")

    # 2. Every known profile's canonical workspace directory.
    for profile_home, profile_name in _known_profile_homes():
        entry = _profile_workspace_picker_entry(profile_home, profile_name)
        if entry:
            add(entry['path'], entry['name'])

    return entries


# Per-user temp directories that sit nominally under a "system" prefix but are
# actually user-writable scratch space.  Workspaces registered here (e.g. by
# pytest's ``tmp_path_factory`` on macOS, which uses ``/var/folders/<hash>/T/``)
# must remain accepted even though their parent (``/var``) is blocked.  These
# carve-outs apply to BOTH workspace registration and runtime file ops so a
# symlink target inside the carve-out is also reachable.
_USER_TMP_PREFIXES: tuple[Path, ...] = (
    Path('/var/folders'),         # macOS per-user tmp (literal form)
    Path('/private/var/folders'),  # macOS per-user tmp (resolved form)
    Path('/var/tmp'),               # Linux/macOS system-wide tmp (user-writable)
    Path('/private/var/tmp'),       # macOS resolved form
)


def _workspace_blocked_roots() -> tuple[Path, ...]:
    """System roots that must never be accepted as workspace candidates.

    Returns both the literal path and its symlink-resolved canonical form,
    deduped.  This matters on macOS where ``/etc``, ``/var``, and ``/tmp``
    are symlinks to ``/private/etc`` etc.  Without the resolved forms,
    callers that pass a ``.resolve()``-d candidate (every caller does)
    would compare ``/private/etc`` against literal ``Path('/etc')`` and the
    ``relative_to`` check would miss — letting ``/etc`` through as a
    registered workspace on macOS.

    Carve-outs for legitimate user-tmp paths nominally under these roots
    (e.g. ``/var/folders/.../T/`` on macOS) are handled by
    :func:`_is_blocked_system_path`, not by exclusion from this list.
    """
    _raw = (
        # Linux / macOS
        '/etc',
        '/usr',
        '/var',
        '/bin',
        '/sbin',
        '/boot',
        '/proc',
        '/sys',
        '/dev',
        '/lib',
        '/lib64',
        '/opt/homebrew',
        '/System',
        '/Library',
    )
    _seen: set[Path] = set()
    _out: list[Path] = []
    for _p in _raw:
        for _form in (Path(_p), _safe_resolve(Path(_p))):
            if _form not in _seen:
                _seen.add(_form)
                _out.append(_form)
    return tuple(_out)


def _is_blocked_system_path(candidate: Path) -> bool:
    """Return True if *candidate* falls under a blocked system root.

    Honours :data:`_USER_TMP_PREFIXES` carve-outs so per-user tmp directories
    nominally under ``/var`` (``/var/folders`` on macOS, ``/var/tmp`` on
    Linux/macOS) remain valid workspace candidates and reachable file targets.
    """
    for tmp in _USER_TMP_PREFIXES:
        if _is_within(candidate, tmp):
            return False
    for blocked in _workspace_blocked_roots():
        if _is_within(candidate, blocked):
            return True
    return False


def _workspace_blocked_resolved_subtrees() -> tuple[Path, ...]:
    roots = list(_workspace_blocked_roots()) + [Path('/private/etc')]
    resolved: list[Path] = []
    for root in roots:
        try:
            p = root.expanduser().resolve()
        except Exception:
            p = root
        if p not in resolved:
            resolved.append(p)
    return tuple(resolved)


def _workspace_blocked_exact_roots() -> tuple[Path, ...]:
    roots = [Path('/'), Path('/private/var')]
    for root in _workspace_blocked_roots():
        try:
            roots.append(root.expanduser().resolve())
        except Exception:
            roots.append(root)
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def _is_blocked_workspace_path(candidate: Path, raw_path: str | Path | None = None) -> bool:
    """Return True when candidate points at a known OS/system directory.

    Compare both the original spelling and the resolved path.  This closes the
    macOS /etc -> /private/etc bypass without globally banning temporary pytest
    paths under /private/var/folders.
    """
    raw = None
    if raw_path not in (None, ""):
        try:
            raw = Path(raw_path).expanduser()
        except Exception:
            raw = None

    exact = _workspace_blocked_exact_roots()
    if candidate in exact or (raw is not None and raw in _workspace_blocked_roots()):
        return True

    for tmp in _USER_TMP_PREFIXES:
        if _is_within(candidate, tmp) or (raw is not None and _is_within(raw, tmp)):
            return False

    # Raw paths under literal roots (e.g. /etc/ssh, /var/db) are always blocked.
    if raw is not None:
        for blocked in _workspace_blocked_roots():
            if _is_within(raw, blocked):
                return True

    # Resolved subtree checks catch symlink aliases such as /private/etc.  The
    # macOS temp root /private/var/folders is intentionally allowed for pytest
    # and per-user temporary workspaces; other direct /private/var system data
    # such as /private/var/db and /private/var/log remains blocked.
    allowed_private_var = (Path('/private/var/folders'), Path('/private/var/tmp'))
    for blocked in _workspace_blocked_resolved_subtrees():
        if blocked == Path('/private/var'):
            if candidate == blocked:
                return True
            if any(_is_within(candidate, allowed) for allowed in allowed_private_var):
                continue
            if _is_within(candidate, blocked):
                return True
            continue
        if _is_within(candidate, blocked):
            return True
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _trusted_workspace_roots() -> list[Path]:
    roots: list[Path] = []

    def add(candidate: str | Path | None) -> None:
        if candidate in (None, ""):
            return
        try:
            p = resolve_profile_workspace(candidate)
        except Exception:
            return
        if not p.exists() or not p.is_dir():
            return
        if _is_blocked_workspace_path(p, candidate):
            return
        if p not in roots:
            roots.append(p)

    add(Path.home())
    add(_BOOT_DEFAULT_WORKSPACE)
    for w in load_workspaces():
        add(w.get("path"))
    roots.sort(key=lambda p: len(str(p)))
    return roots


def list_workspace_suggestions(prefix: str = "", limit: int = 12) -> list[str]:
    """Return workspace path suggestions under trusted roots only.

    Suggestions are limited to directories under one of:
      - Path.home()
      - the boot default workspace
      - already-saved workspace roots

    Arbitrary system prefixes return an empty list rather than an error so the
    UI can safely autocomplete while the user types.
    """
    roots = _trusted_workspace_roots()
    if not roots:
        return []

    raw = (prefix or "").strip()
    if not raw:
        return [str(p) for p in roots[:limit]]

    if raw.startswith("~"):
        target = Path(raw).expanduser()
    elif Path(raw).is_absolute():
        target = Path(raw)
    else:
        target = Path.home() / raw

    normalized = str(target)
    normalized_lower = normalized.lower()
    suggestions: list[str] = []

    def add(path: Path) -> None:
        value = str(path)
        if value not in suggestions:
            suggestions.append(value)

    # If the user is typing a partial trusted root like /Users/xuef..., suggest
    # the matching trusted roots without scanning arbitrary system parents.
    for root in roots:
        if str(root).lower().startswith(normalized_lower):
            add(root)

    in_root = [
        root
        for root in roots
        if normalized == str(root) or normalized.startswith(str(root) + os.sep)
    ]
    if not in_root:
        return suggestions[:limit]

    anchor_root = max(in_root, key=lambda p: len(str(p)))
    ends_with_sep = raw.endswith(os.sep) or raw.endswith('/')
    parent = target if ends_with_sep else target.parent
    leaf = '' if ends_with_sep else target.name
    show_hidden = leaf.startswith('.')

    try:
        parent_resolved = parent.expanduser().resolve()
    except Exception:
        return suggestions[:limit]

    if not parent_resolved.exists() or not parent_resolved.is_dir():
        return suggestions[:limit]
    if not _is_within(parent_resolved, anchor_root):
        return suggestions[:limit]

    leaf_lower = leaf.lower()
    try:
        children = sorted(parent_resolved.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return suggestions[:limit]

    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith('.') and not show_hidden:
            continue
        if leaf_lower and not child.name.lower().startswith(leaf_lower):
            continue
        add(child.resolve())
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


def _owning_profile_homes_for_workspace(candidate: Path) -> list[Path]:
    """Return profile homes whose canonical workspace could equal *candidate*.

    The candidate is matched against:

      * the *active* profile (per-request context),
      * the default/root profile, and
      * the named profile inferred from a shared-layout workspace path
        ``{workspace_root}/<name>`` — but only when ``<name>`` is a valid,
        already-existing profile under ``~/.hermes/profiles/``.

    Inferring the named profile from the path is what makes auto-create work
    even when the active-profile context is wrong: in the container the
    per-request profile lives in a ``threading.local`` set by the async security
    middleware, which is not visible inside the sync endpoint's threadpool
    worker, so ``get_active_hermes_home()`` returns the process-global default
    instead of the profile that actually owns the requested workspace.

    A profile must already exist for its home to be returned, so unknown /
    arbitrary path segments never produce an auto-create target. The caller
    still gates creation on an exact match against the profile's canonical
    workspace, so this only ever widens *which* trusted profile workspace can be
    materialized, never *what kind* of path.
    """
    homes: list[Path] = []

    def add(home: Path | None) -> None:
        if home is None:
            return
        try:
            resolved = home.expanduser().resolve()
        except OSError:
            return
        if resolved not in homes:
            homes.append(resolved)

    access = get_request_user_access()
    add(_profile_home_for_workspace_access(access))

    try:
        from app.domain.profiles import get_active_hermes_home
        add(get_active_hermes_home())
    except Exception:
        logger.debug("Failed to resolve active profile home for workspace ensure")

    hermes_home = _default_hermes_home()
    add(hermes_home)

    account_slug = _account_workspace_slug_for_access(access)
    restrict_foreign = bool(
        nested_workspaces_enabled()
        and access is not None
        and getattr(access, "multi_user_enabled", False)
        and account_slug
    )

    if hermes_home is not None:
        try:
            shared_root = _shared_workspace_root(hermes_home).resolve()
            rel = candidate.resolve().relative_to(shared_root)
        except (OSError, ValueError):
            rel = None
        if rel is not None and len(rel.parts) >= 1:
            name = rel.parts[0]
            if restrict_foreign and name != account_slug:
                return homes
            try:
                from app.domain.profiles import _resolve_named_profile_home
                profile_home = _resolve_named_profile_home(name)
            except (ImportError, ValueError, OSError):
                profile_home = None
            if profile_home is not None:
                try:
                    exists = profile_home.is_dir()
                except (PermissionError, OSError):
                    exists = False
                if exists:
                    add(profile_home)

    return homes


def ensure_registered_nested_workspace_exists(candidate: Path) -> bool:
    """Lazily recreate a registered nested workspace directory if missing.

    In multi-user mode, nested sub-workspaces are stored as virtual ``/workspace/...``
    paths in ``workspaces.json``. The directory can go missing even though the
    registry entry (and sessions pointing at it) still reference it — e.g. the
    entry was added with ``create: false``, container/host state was wiped, or
    the bind mount was replaced without the nested folder.

    Only paths that exactly match a persisted nested registry entry for a known
    profile are materialized; arbitrary missing directories are never created.
    """
    if not nested_workspaces_enabled():
        return False
    try:
        target = candidate.resolve()
    except OSError:
        return False
    for profile_home in _owning_profile_homes_for_workspace(candidate):
        try:
            workspaces = load_workspaces_for_profile(profile_home)
        except Exception:
            logger.debug(
                "Failed to load nested workspace registry for %s",
                profile_home,
                exc_info=True,
            )
            continue
        for item in workspaces:
            raw = str(item.get('path') or '').strip()
            if not is_virtual_workspace_path(raw) or raw == VIRTUAL_WORKSPACE_ROOT:
                continue
            try:
                disk = virtual_path_to_disk(raw, profile_home).resolve()
            except (OSError, ValueError):
                continue
            if disk != target:
                continue
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return True
            except OSError:
                logger.debug(
                    "Failed to auto-create registered nested workspace %s", candidate
                )
                return False
    return False


_WORKSPACE_UPLOADS_SUBDIR = ".uploads"


def _runtime_uid_gid() -> tuple[int, int] | None:
    if not hasattr(os, "getuid"):
        return None
    return os.getuid(), os.getgid()


def best_effort_align_path_ownership(path: Path) -> int:
    """Chown *path* and parents up to Hermes home to the runtime user when allowed."""
    uid_gid = _runtime_uid_gid()
    if uid_gid is None:
        return 0
    uid, gid = uid_gid
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return 0

    hermes_home: Path | None = None
    try:
        hermes_home = _default_hermes_home()
        if hermes_home is not None:
            hermes_home = hermes_home.expanduser().resolve()
    except OSError:
        hermes_home = None

    candidates: list[Path] = []
    current = resolved
    while True:
        candidates.append(current)
        if hermes_home is not None and current == hermes_home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    aligned = 0
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            st = candidate.lstat()
        except OSError:
            continue
        if st.st_uid == uid and st.st_gid == gid:
            continue
        try:
            os.chown(candidate, uid, gid, follow_symlinks=False)
            aligned += 1
        except OSError as exc:
            logger.debug("Could not chown %s to %s:%s: %s", candidate, uid, gid, exc)
    return aligned


def ensure_directory_writable(path: Path, *, mode: int = 0o755) -> Path:
    """Ensure *path* exists and is writable by the runtime user."""
    target = path.expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PermissionError(f"Cannot create directory {target}: {exc}") from exc

    best_effort_align_path_ownership(target)
    try:
        current = stat.S_IMODE(target.stat().st_mode)
        if current & stat.S_IWUSR == 0:
            target.chmod(current | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:
        pass

    if not os.access(target, os.W_OK | os.X_OK):
        raise PermissionError(
            f"Directory not writable by runtime user: {target}. "
            "On Docker, restart the container after upgrading, or run as root: "
            f"chown -R $(id -u):$(id -g) {target}"
        )
    return target.resolve()


def best_effort_repair_hermes_home_traversal() -> int:
    """Ensure the Hermes home entry is owned by the runtime user when allowed."""
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return 0
    try:
        home = hermes_home.expanduser().resolve()
    except OSError:
        return 0
    if not home.exists():
        return 0
    return best_effort_align_path_ownership(home)


def best_effort_repair_shared_workspace_ownership() -> int:
    """Align ownership on the shared workspace tree and per-account ``.uploads/`` dirs."""
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return 0
    aligned = best_effort_repair_hermes_home_traversal()
    try:
        shared = _shared_workspace_root(hermes_home).resolve()
    except OSError:
        return 0
    if not shared.is_dir():
        return aligned

    aligned += best_effort_align_path_ownership(shared)
    try:
        children = list(shared.iterdir())
    except OSError:
        return aligned
    for child in children:
        if not child.is_dir():
            continue
        aligned += best_effort_align_path_ownership(child)
        uploads = child / _WORKSPACE_UPLOADS_SUBDIR
        if uploads.exists():
            aligned += best_effort_align_path_ownership(uploads)
    return aligned


def ensure_profile_workspace_exists(candidate: Path) -> bool:
    """Lazily (re)create a profile's auto-managed workspace directory if missing.

    Each profile owns exactly one workspace that is "created automatically under
    the profile directory" (see one-workspace-per-profile policy). Its canonical
    location is system-managed and always trusted. That directory can go missing
    even though the profile and its saved workspace entry still reference it:

      * a profile created under the legacy ``profiles/<name>/workspace`` layout is
        remapped to the shared ``workspace/<name>`` layout, but the shared subdir
        was never materialized during the migration, or
      * stale local/container state deleted the directory.

    When that happens, resolving the profile's own workspace failed with
    ``Path does not exist: .../workspace/<name>`` and broke session creation,
    chat start, and directory listing. Recreate the directory on demand so the
    profile's own trusted workspace resolves cleanly.

    Creation is scoped to a path that exactly matches *some known profile's*
    canonical workspace directory (see :func:`_owning_profile_homes_for_workspace`).
    Arbitrary user-supplied paths are never auto-created — that would loosen the
    path-existence guard for untrusted input.

    Returns ``True`` when the directory exists after the call because it matched
    a profile's canonical workspace (created or already present), ``False``
    otherwise.
    """
    try:
        target = candidate.resolve()
    except OSError:
        return False
    for profile_home in _owning_profile_homes_for_workspace(candidate):
        try:
            canonical = profile_workspace_dir(profile_home).resolve()
        except OSError:
            continue
        if target == canonical:
            try:
                ensure_directory_writable(candidate)
                return True
            except (OSError, PermissionError):
                logger.debug(
                    "Failed to auto-create canonical profile workspace %s", candidate
                )
                return False
    return False


# Backwards-compatible alias retained for the original PR #14 entry point.
def _ensure_canonical_profile_workspace(candidate: Path) -> None:
    ensure_profile_workspace_exists(candidate)


def _ensure_trusted_workspace_materialized(candidate: Path) -> None:
    """Recreate system-managed workspace directories that are missing on disk."""
    ensure_profile_workspace_exists(candidate)
    ensure_registered_nested_workspace_exists(candidate)


def resolve_session_workspace(workspace: str | Path | None) -> Path:
    """Resolve ``session.workspace`` (virtual or disk spelling) to a trusted directory."""
    return resolve_trusted_workspace(workspace)


def _fallback_account_workspace_root_for_profile_home(
    profile_home: Path,
    *,
    profile_name: str | None = None,
) -> Path | None:
    """Infer ``workspace/<account>/`` when request UserAccess is unavailable.

    Agent streaming threads usually inherit ``UserAccess`` via ``contextvars``,
    but background workers and stale virtual ``/workspace`` re-resolution can
    run without it.  Named profiles map to ``profiles/<slug>``; the root/default
    profile falls back to ``HERMES_WEBUI_ADMIN_USER`` when configured.
    """
    if not nested_workspaces_enabled():
        return None
    hermes_home = _default_hermes_home()
    if hermes_home is None:
        return None
    try:
        resolved_home = profile_home.expanduser().resolve()
    except OSError:
        return None

    slug: str | None = None
    named = _named_profile_name(resolved_home)
    if named:
        slug = named
    else:
        token = str(profile_name or "").strip()
        if token and token != "default":
            slug = token

    if slug:
        try:
            candidate = (_shared_workspace_root(hermes_home) / slug).resolve()
        except OSError:
            candidate = None
        if candidate is not None and candidate.is_dir():
            return candidate

    try:
        if resolved_home != hermes_home.resolve():
            return None
        admin_user = os.getenv("HERMES_WEBUI_ADMIN_USER", "").strip()
        if not admin_user:
            return None
        owned = _admin_owned_shared_workspace_dirs(hermes_home, admin_user)
        if owned:
            return sorted(owned, key=lambda item: len(str(item)))[0].resolve()
    except OSError:
        return None
    return None


def resolve_main_user_workspace_root(
    workspace: str | Path | None = None,
    *,
    profile_home: Path | None = None,
    access: Any = None,
    profile_name: str | None = None,
) -> Path:
    """Return the primary on-disk workspace root for the signed-in account.

    Nested sub-workspaces (``/workspace/project/...``) share one ``.uploads/``
    directory under this root — not under each nested folder.
    """
    token = str(workspace or "").strip()
    if not nested_workspaces_enabled():
        return resolve_trusted_workspace(workspace)

    if not token:
        containment = account_workspace_containment_root(
            profile_home=profile_home,
            access=access,
        )
        if containment is not None:
            return containment.resolve()
        if profile_home is None:
            profile_home = _profile_home_for_workspace_access(access)
        if profile_home is None:
            try:
                from app.domain.profiles import get_active_hermes_home

                profile_home = get_active_hermes_home()
            except ImportError:
                profile_home = Path.home()
        root = _virtual_workspace_disk_root_for_mapping(profile_home, access=access)
        if access is None:
            fallback = _fallback_account_workspace_root_for_profile_home(
                profile_home,
                profile_name=profile_name,
            )
            if fallback is not None:
                try:
                    shared = _shared_workspace_root(
                        _default_hermes_home() or profile_home
                    ).resolve()
                    if root.resolve() == shared:
                        return fallback
                except OSError:
                    return fallback
        return root

    if is_virtual_workspace_path(token):
        if profile_home is not None:
            try:
                root = profile_workspace_dir(profile_home, access=access).resolve()
                if access is None:
                    fallback = _fallback_account_workspace_root_for_profile_home(
                        profile_home,
                        profile_name=profile_name,
                    )
                    if fallback is not None:
                        try:
                            shared = _shared_workspace_root(
                                _default_hermes_home() or profile_home
                            ).resolve()
                            if root == shared:
                                root = fallback
                        except OSError:
                            root = fallback
                return root
            except OSError:
                pass
        # Agent runs pin ``HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT`` for per-account
        # containment. ``resolve_trusted_workspace('/workspace')`` still maps the
        # virtual root to the profile default ``~/.hermes/workspace`` and raises
        # outside-account errors for non-default accounts — which silently drops
        # native vision ``image_url`` embedding for ``.uploads/`` attachments.
        containment = account_workspace_containment_root(
            profile_home=profile_home,
            access=access,
        )
        if containment is not None:
            return containment.resolve()

    active = resolve_trusted_workspace(token)
    containment = account_workspace_containment_root(
        workspace_disk=active,
        profile_home=profile_home,
        access=access,
    )
    if containment is not None:
        return containment

    if profile_home is None:
        profile_home = _profile_home_for_workspace_access(access)
    if profile_home is None:
        try:
            from app.domain.profiles import get_active_hermes_home

            profile_home = get_active_hermes_home()
        except ImportError:
            profile_home = Path.home()
    main_root = _virtual_workspace_disk_root_for_mapping(profile_home, access=access)
    try:
        active.resolve().relative_to(main_root.resolve())
        return main_root.resolve()
    except ValueError:
        return active.resolve()


def resolve_trusted_workspace(path: str | Path | None = None) -> Path:
    """Resolve and validate a workspace path.

    A path is trusted if it satisfies at least one of:
      (A) It is under the user's home directory (Path.home()).
          Works cross-platform: ~/... on Linux/macOS, C:\\Users\\... on Windows.
      (B) It is already in the profile's saved workspace list.
          This covers self-hosted deployments where workspaces live outside home
          (e.g. /data/projects, /opt/workspace) — once a workspace is saved by
          an admin, it can be reused without re-validation.

    Additionally enforced regardless of (A)/(B):
      1. The path must exist.
      2. The path must be a directory.
      3. The path must not be a known system root (/etc, /usr, /var, /bin, /sbin,
         /boot, /proc, /sys, /dev, /root on Linux/macOS; Windows system dirs).
         This prevents even admin-saved workspaces from pointing at OS internals.

    None/empty path falls back to the boot-time DEFAULT_WORKSPACE, which is always
    trusted (it was validated at server startup).
    """
    if path in (None, ""):
        return Path(_BOOT_DEFAULT_WORKSPACE).expanduser().resolve()

    candidate = resolve_profile_workspace(path)
    if nested_workspaces_enabled():
        access = get_request_user_access()
        pre_coerce = candidate
        candidate = _coerce_to_account_workspace(
            candidate,
            access=access,
            raw=path,
        )
        if (
            _account_workspace_isolation_enabled(access)
            and candidate != pre_coerce
        ):
            containment = account_workspace_containment_root(access=access)
            if containment is not None:
                try:
                    resolved = candidate.expanduser().resolve()
                except OSError:
                    resolved = None
                if resolved is None or not resolved.is_dir():
                    candidate = containment.resolve()
    candidate = _maybe_remap_shared_root_default_subdir(candidate)

    # Profile-owned workspace directories (canonical root and registered nested
    # sub-workspaces) are system-managed; recreate them when registry/state
    # outlives the on-disk directory (see helper docstrings).
    _ensure_trusted_workspace_materialized(candidate)

    access_error = _workspace_access_error(candidate)
    if access_error:
        raise ValueError(access_error)

    if nested_workspaces_enabled():
        access = get_request_user_access()
        containment_root = account_workspace_containment_root(
            workspace_disk=candidate,
            access=access,
        )
        if containment_root is not None:
            if not path_within_account_workspace(candidate, root=containment_root):
                coerced = _coerce_to_account_workspace(
                    candidate,
                    access=access,
                    raw=path,
                )
                if path_within_account_workspace(coerced, root=containment_root):
                    return coerced.resolve()
                if _account_workspace_isolation_enabled(access):
                    return containment_root.resolve()
                raise ValueError(
                    f"Path is outside this account's workspace ({containment_root}): "
                    f"{candidate}"
                )
            return candidate

    # (A) Trusted if under the user's home directory — cross-platform via Path.home()
    # Must be checked before system roots to allow symlinks like /var/home.
    _home = Path.home().resolve()
    if _home != Path("/"):
        try:
            candidate.relative_to(_home)
            return candidate
        except ValueError:
            pass

    # Block known system roots and their children.
    if _is_blocked_workspace_path(candidate, path):
        raise ValueError(f"Path points to a system directory: {candidate}")

    # (B) Trusted if already in the saved workspace list — covers non-home installs
    try:
        saved = load_workspaces()
        saved_paths: set[Path] = set()
        for w in saved:
            raw = w.get("path")
            if not raw:
                continue
            try:
                saved_paths.add(resolve_profile_workspace(raw))
            except Exception:
                continue
        if candidate in saved_paths:
            return candidate
    except Exception:
        pass

    # (C) Trusted if it is equal to or under the boot-time DEFAULT_WORKSPACE.
    #     In Docker deployments HERMES_WEBUI_DEFAULT_WORKSPACE is often set to a
    #     volume mount outside the user's home (e.g. /data/workspace).  That path
    #     was already validated at server startup, so any sub-path of it is safe
    #     without requiring the user to add it to the workspace list manually.
    try:
        boot_default = Path(_BOOT_DEFAULT_WORKSPACE).expanduser().resolve()
        candidate.relative_to(boot_default)
        return candidate
    except ValueError:
        pass

    raise ValueError(
        f"Path is outside the user home directory, not in the saved workspace "
        f"list, and not under the default workspace: {candidate}. "
        f"Add it via Settings → Workspaces first."
    )




def _strip_surrounding_quotes(path: str) -> str:
    """Strip a single pair of surrounding single or double quotes from a path string.

    macOS Finder's "Copy as Pathname" (Cmd+Option+C) returns paths wrapped in
    single quotes, e.g. ``'/Users/x/Documents/foo'``. Other shells and OS file
    managers do similar things with double quotes. Users routinely paste these
    quoted strings into the Add Space input expecting them to "just work" —
    the only reason they didn't was a missing strip.

    Only paired quotes are stripped (matching opener and closer). One-sided quotes
    are preserved on the slim chance a path legitimately contains a literal quote
    character.
    """
    s = path.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def validate_workspace_to_add(path: str) -> Path:
    """Validate a path for *adding* to the workspace list (less restrictive than resolve_trusted_workspace).

    When a user explicitly adds a new workspace path, we trust their intent — they
    have console or filesystem access to that path and are consciously registering it.
    We only block: non-existent paths, non-directories, and known system roots.

    The stricter ``resolve_trusted_workspace`` is used when *using* an existing workspace
    (file reads/writes) to prevent path traversal after the list is built.

    Surrounding quotes (single or double) are stripped before validation —
    macOS Finder's "Copy as Pathname" wraps paths in single quotes by default,
    and users routinely paste those into the Add Space input.
    """
    path = _strip_surrounding_quotes(path)
    candidate = Path(path).expanduser().resolve()

    access_error = _workspace_access_error(candidate)
    if access_error:
        raise ValueError(access_error)

    # Home directory is always trusted regardless of where it lives on disk
    # (e.g. /var/home/... on systemd-homed Fedora/RHEL).
    _home = Path.home().resolve()
    if _home != Path("/") and _is_within(candidate, _home):
        return candidate

    # Block known system roots and their immediate children.
    if _is_blocked_workspace_path(candidate, path):
        raise ValueError(f"Path points to a system directory: {candidate}")

    return candidate

def safe_resolve_ws(root: Path, requested: str) -> Path:
    """Resolve a relative path inside a workspace root, raising ValueError on traversal.

    Symlinks whose *unresolved* path is within the workspace root are allowed —
    the user placed them there intentionally.  Only raw ``..`` traversal outside
    the root is blocked.
    """
    import os
    unresolved = root / requested
    resolved = unresolved.resolve()
    # Fast path: resolved path is inside root (covers most cases)
    try:
        resolved.relative_to(root.resolve())
        return resolved
    except ValueError:
        pass
    # Symlink path: normalize '..' (without following symlinks) and check
    # os.path.normpath collapses '..' but does NOT follow symlinks.
    norm = Path(os.path.normpath(str(unresolved)))
    try:
        norm.relative_to(root)
    except ValueError:
        raise ValueError(f"Path traversal blocked: {requested}")
    # Symlink points outside workspace root — additionally block system directories.
    # Even if the user placed the symlink intentionally, prevent reads from
    # /etc, /proc, /sys, /dev and other blocked roots (LLM agents can call
    # read_file_content via tool calls, not just human users).
    if _is_blocked_system_path(resolved):
        raise ValueError(f"Path traversal blocked (system dir): {requested}")
    return resolved


def workspace_allowed_for_access(workspace: str, access=None) -> bool:
    """Return True when *workspace* matches a picker row for *access*."""
    target = str(workspace or "").strip()
    if not target:
        return False

    profile_home = None
    if access is not None and _uses_account_workspace_registry(access):
        try:
            from app.domain.profiles import get_hermes_home_for_profile

            bound = _bound_profile_for_workspace_access(access)
            profile_home = get_hermes_home_for_profile(bound)
        except Exception:
            return False

    try:
        if is_virtual_workspace_path(target):
            target_resolved = resolve_profile_workspace(target, profile_home).resolve()
        else:
            target_resolved = Path(target).expanduser().resolve()
        target_real = os.path.realpath(str(target_resolved))
    except (OSError, ValueError, RuntimeError):
        target_real = None
        target_resolved = None

    for row in list_all_profile_workspaces(access=access):
        row_path = str(row.get("path") or "").strip()
        if row_path and row_path == target:
            return True
        disk_path = row.get("disk_path")
        if disk_path:
            try:
                if os.path.realpath(str(disk_path)) == target_real:
                    return True
            except (OSError, ValueError):
                pass
        if not row_path:
            continue
        try:
            if is_virtual_workspace_path(row_path):
                row_resolved = resolve_profile_workspace(row_path, profile_home).resolve()
            else:
                row_resolved = Path(row_path).expanduser().resolve()
            if target_resolved is not None and row_resolved == target_resolved:
                return True
            if target_real is not None and os.path.realpath(str(row_resolved)) == target_real:
                return True
        except (OSError, ValueError, RuntimeError):
            continue

    if access is not None and getattr(access, "restricts_profiles", False):
        try:
            resolved = resolve_trusted_workspace(target)
            containment = account_workspace_containment_root(access=access)
            if containment is not None and path_within_account_workspace(
                resolved,
                root=containment,
            ):
                return True
        except ValueError:
            pass
    return False


def list_dir(workspace: Path, rel: str='.'):
    target = safe_resolve_ws(workspace, rel)
    if not target.is_dir():
        raise FileNotFoundError(f"Not a directory: {rel}")
    ws_resolved = workspace.resolve()
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_symlink(), p.is_file(), p.name.lower())):
        if item.is_symlink():
            # Resolve the symlink target and check if it stays within workspace
            try:
                link_target = item.resolve()
            except OSError:
                continue
            # Cycle detection: skip if symlink points back to current dir,
            # workspace root, or any ancestor of current dir.
            # This must run REGARDLESS of whether target is inside workspace.
            if (link_target == target.resolve() or link_target == target
                    or link_target == ws_resolved):
                continue
            try:
                target.resolve().relative_to(link_target)
                # target is under link_target — link_target is an ancestor → cycle
                continue
            except ValueError:
                pass
            # Block symlinks that resolve to system directories.
            if _is_blocked_system_path(link_target):
                continue
            is_dir = link_target.is_dir()
            # Keep the display path relative to workspace (don't follow the link)
            display_path = str(Path(item.name))
            if rel and rel != '.':
                display_path = rel + '/' + display_path
            try:
                item_stat = item.lstat()
                mtime_ns = item_stat.st_mtime_ns
            except OSError:
                mtime_ns = None
            entry = {
                'name': item.name,
                'path': display_path,
                'type': 'symlink',
                'target': str(link_target),
                'is_dir': is_dir,
                'mtime_ns': mtime_ns,
            }
            if not is_dir:
                try:
                    entry['size'] = link_target.stat().st_size
                except OSError:
                    entry['size'] = None
            entries.append(entry)
        else:
            # Use rel-based path so entries under symlink targets (outside
            # the workspace root) still get a valid workspace-relative path.
            entry_path = item.name
            if rel and rel != '.':
                entry_path = rel + '/' + item.name
            try:
                item_stat = item.stat()
                size = item_stat.st_size if item.is_file() else None
                mtime_ns = item_stat.st_mtime_ns
            except OSError:
                size = None
                mtime_ns = None
            entries.append({
                'name': item.name,
                'path': entry_path,
                'type': 'dir' if item.is_dir() else 'file',
                'size': size,
                'mtime_ns': mtime_ns,
            })
        if len(entries) >= 200:
            break
    return entries


def dir_signature(workspace: Path, rel: str = '.', entries: list[dict] | None = None) -> str:
    """Return a cheap, stable signature for a listed workspace directory.

    The signature is based only on bounded directory-entry metadata already used
    by the workspace tree: names, displayed paths, entry type, file sizes,
    mtimes, and symlink targets. It intentionally does not read file contents.
    """
    if entries is None:
        entries = list_dir(workspace, rel)
    payload = []
    for entry in entries:
        payload.append({
            'name': entry.get('name'),
            'path': entry.get('path'),
            'type': entry.get('type'),
            'is_dir': entry.get('is_dir'),
            'size': entry.get('size'),
            'mtime_ns': entry.get('mtime_ns'),
            'target': entry.get('target'),
        })
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def read_file_content(workspace: Path, rel: str) -> dict:
    target = safe_resolve_ws(workspace, rel)
    if not target.is_file():
        raise FileNotFoundError(f"Not a file: {rel}")
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File too large ({size} bytes, max {MAX_FILE_BYTES})")
    content = target.read_text(encoding='utf-8', errors='replace')
    return {'path': rel, 'content': content, 'size': size, 'lines': content.count('\n') + 1}


# ── Git detection ──────────────────────────────────────────────────────────

def _run_git(args, cwd, timeout=3):
    """Run a git command and return stdout, or None on failure."""
    try:
        r = subprocess.run(
            ['git'] + args, cwd=str(cwd), capture_output=True,
            text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def git_info_for_workspace(workspace: Path) -> dict:
    """Return git info for a workspace directory, or None if not a git repo."""
    if not (workspace / '.git').exists():
        return None
    branch = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], workspace)
    if branch is None:
        return None
    # Run the remaining git commands in parallel via threads — they are
    # independent subprocess calls and together can take 50-200ms when run
    # serially.  Threading is safe here because each call blocks only on the
    # subprocess pipe, not on the GIL.
    def _ahead():
        r = _run_git(['rev-list', '--count', '@{u}..HEAD'], workspace)
        return int(r) if r and r.isdigit() else 0
    def _behind():
        r = _run_git(['rev-list', '--count', 'HEAD..@{u}'], workspace)
        return int(r) if r and r.isdigit() else 0
    def _status():
        out = _run_git(['status', '--porcelain'], workspace) or ''
        lines = [l for l in out.splitlines() if l]
        modified = sum(1 for l in lines if len(l) >= 2 and (l[0] in 'MAR' or l[1] in 'MAR'))
        untracked = sum(1 for l in lines if l.startswith('??'))
        return len(lines), modified, untracked
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_status = pool.submit(_status)
        f_ahead  = pool.submit(_ahead)
        f_behind = pool.submit(_behind)
        dirty, modified, untracked = f_status.result()
        ahead  = f_ahead.result()
        behind = f_behind.result()
    return {
        'branch': branch,
        'dirty': dirty,
        'modified': modified,
        'untracked': untracked,
        'ahead': ahead,
        'behind': behind,
        'is_git': True,
    }


# ── FastAPI migration layer (lazy re-exports) ───────────────────────────────
_FASTAPI_LAYER_EXPORTS = {
    "SettingsRepository": ("app.repositories.settings", "SettingsRepository"),
}


def _fastapi_layer_import(module_path: str, attr: str):
    import importlib

    return getattr(importlib.import_module(module_path), attr)


def settings_repository() -> "SettingsRepository":
    """Return a SettingsRepository instance (FastAPI migration shim)."""
    return _fastapi_layer_import("app.repositories.settings", "SettingsRepository")()


def repository_load_workspaces() -> list:
    """Load workspace list (compat alias for domain ``load_workspaces``)."""
    return load_workspaces()


def repository_save_workspaces(workspaces: list) -> None:
    """Save workspace list (compat alias for domain ``save_workspaces``)."""
    save_workspaces(workspaces)


def repository_resolve_trusted_workspace(path: str | Path | None = None) -> Path:
    """Resolve trusted workspace (compat alias for domain helper)."""
    return resolve_trusted_workspace(path)


def __getattr__(name: str):
    target = _FASTAPI_LAYER_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = target
    return _fastapi_layer_import(module_path, attr)
