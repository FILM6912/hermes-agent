"""
Hermes Web UI -- Profile state management.
Wraps hermes_cli.profiles to provide profile switching for the web UI.

API shim note (FastAPI migration):
  This module remains the legacy import surface for profile operations used by
  server.py and api/routes.py. During the FastAPI migration, route handlers will
  move to thin shims that delegate to app.services.profiles (see app/repositories/
  for the repository layer). Do not add new business logic here once the service
  layer lands — extend app.services.profiles instead.

The web UI maintains a process-level "active profile" that determines which
HERMES_HOME directory is used for config, skills, memory, cron, and API keys.
Profile switches update os.environ['HERMES_HOME'] and monkey-patch module-level
cached paths in hermes-agent modules (skills_tool, skill_manager_tool,
cron/jobs) that snapshot HERMES_HOME at import time.
"""
import functools
import json
import logging
import contextvars
import os
import re
import shutil
import sys
import threading
import time
import copy
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from app.domain.session_events import publish_session_list_changed

if TYPE_CHECKING:
    from app.repositories.profiles import ProfileRepository
    from app.services.profiles import (
        ProfileService,
        sync_all_profiles_from_default_api,
        sync_profile_from_default_api,
    )

logger = logging.getLogger(__name__)


class ProfileAccessError(PermissionError):
    """Raised when a user attempts a profile operation outside their binding."""


PROFILE_MANAGEMENT_FORBIDDEN_DETAIL = "Permission required: profiles:manage"


def _profile_access_unrestricted(user) -> bool:
    from app.core.security import user_can_switch_all_profiles

    return user_can_switch_all_profiles(user)


def filter_profiles_for_user(profiles: list, user) -> list:
    """Return only profiles assigned to *user* (unrestricted viewers see all)."""
    from app.domain.users import get_user, is_multi_user_enabled

    if not is_multi_user_enabled() or user is None or _profile_access_unrestricted(user):
        return profiles
    record = None
    user_id = getattr(user, "user_id", None)
    if user_id:
        record = get_user(str(user_id))
    allowed = record.assigned_profile_names() if record else ()
    if not allowed:
        bound = getattr(user, "profile_name", None) or "default"
        allowed = (bound,)
    return [
        row
        for row in profiles
        if any(_profiles_match(row.get("name"), name) for name in allowed)
    ]


def ensure_profile_switch_allowed(name: str, user) -> None:
    """Allow switching only among profiles assigned to this account."""
    from app.domain.users import get_user, is_multi_user_enabled, user_may_access_profile

    if not is_multi_user_enabled() or user is None or _profile_access_unrestricted(user):
        return
    record = None
    user_id = getattr(user, "user_id", None)
    if user_id:
        record = get_user(str(user_id))
    if record is not None and user_may_access_profile(name, record):
        return
    allowed = getattr(user, "profile_names", None) or ()
    if not allowed and getattr(user, "profile_name", None):
        allowed = (user.profile_name,)
    if any(_profiles_match(name, item) for item in allowed):
        return
    bound = getattr(user, "profile_name", None) or "default"
    raise ProfileAccessError(
        f"Profile {name!r} is not available for this account (assigned: {', '.join(allowed) or bound!r})"
    )


def ensure_profile_management_allowed(user) -> None:
    """Only callers with ``profiles:manage`` may create/delete/sync profiles in multi-user mode."""
    from app.core.security import user_can_manage_profiles
    from app.domain.users import is_multi_user_enabled

    if is_multi_user_enabled() and user is not None and not user_can_manage_profiles(user):
        raise ProfileAccessError(PROFILE_MANAGEMENT_FORBIDDEN_DETAIL)


def ensure_profile_list_allowed(user) -> None:
    """Regular users may list their assigned profiles; unrestricted viewers may list all."""
    from app.domain.users import is_multi_user_enabled

    if not is_multi_user_enabled() or user is None:
        return
    if _profile_access_unrestricted(user):
        return
    # Assigned-profile listing is allowed for role=user.


def ensure_profile_create_allowed(user) -> None:
    """Only administrators may create profiles when multi-user mode is active."""
    ensure_profile_management_allowed(user)


def active_profile_for_user(active: str, user) -> str:
    """Clamp the reported active profile to a regular user's assigned profiles."""
    from app.domain.users import get_user, is_multi_user_enabled, user_may_access_profile

    if not is_multi_user_enabled() or user is None or _profile_access_unrestricted(user):
        return active
    record = None
    user_id = getattr(user, "user_id", None)
    if user_id:
        record = get_user(str(user_id))
    if record is not None:
        if user_may_access_profile(active, record):
            return active
        names = record.assigned_profile_names()
        return names[0] if names else (record.profile_name or "default")
    bound = getattr(user, "profile_name", None) or "default"
    if _profiles_match(active, bound):
        return active
    return bound


def active_profile_for_access(active: str, access) -> str:
    """Back-compat alias for UserAccess / CurrentUser profile clamping."""
    return active_profile_for_user(active, access)


# ── Constants (match hermes_cli.profiles upstream) ─────────────────────────
_PROFILE_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
_PROFILE_DIRS = [
    'memories', 'sessions', 'skills', 'skins',
    'logs', 'plans', 'workspace', 'cron',
]
_CLONE_CONFIG_FILES = ['config.yaml', '.env', 'SOUL.md']
_CLONE_SUBDIR_FILES = ['memories/MEMORY.md', 'memories/USER.md']
_DEFAULT_CLONE_SOURCE = 'default'

# Top-level config.yaml keys copied verbatim from the default profile on sync.
_MODEL_SYNC_TOP_LEVEL_KEYS = frozenset({
    'model',
    'custom_providers',
    'providers',
    'fallback_providers',
    'model_catalog',
    'openrouter',
    'auxiliary',
})

# ── Module state ────────────────────────────────────────────────────────────
_active_profile = 'default'
_profile_lock = threading.Lock()
_loaded_profile_env_keys: set[str] = set()

# Per-request profile context: set per-request by ProfileContextMiddleware,
# cleared after.  Enables per-client profile isolation (issue #798) — each
# HTTP request reads its own profile from the hermes_profile cookie instead of
# the process-global _active_profile.
#
# This MUST be a contextvars.ContextVar, not threading.local: the async
# middleware that sets it runs on the event-loop thread, but sync FastAPI
# route handlers (def, not async def) execute on a *different* anyio threadpool
# worker thread (run_in_threadpool / anyio.to_thread.run_sync). A
# threading.local set on the event-loop thread is empty on that worker thread,
# so profile-scoped sync endpoints (workspace list, sessions, settings, …) would
# silently fall back to the process-global 'default' profile. ContextVars are
# copied into the threadpool worker by anyio, so the request's profile
# propagates correctly to sync handlers (issue: profile context threadpool).
_request_profile: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "hermes_request_profile", default=None
)

# Thread-local kept only for the cron-call reentrancy depth counter, which runs
# synchronously within a single thread under _cron_env_lock. Profile context no
# longer lives here (see _request_profile above).
_tls = threading.local()

_SKILL_HOME_MODULES = ("tools.skills_tool", "tools.skill_manager_tool")


def snapshot_skill_home_modules() -> dict[str, dict[str, object]]:
    """Snapshot imported skill-module path globals before a temporary patch."""
    snapshot: dict[str, dict[str, object]] = {}
    for module_name in _SKILL_HOME_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            snapshot[module_name] = {"module_present": False}
            continue
        snapshot[module_name] = {
            "module_present": True,
            "has_HERMES_HOME": hasattr(module, "HERMES_HOME"),
            "HERMES_HOME": getattr(module, "HERMES_HOME", None),
            "has_SKILLS_DIR": hasattr(module, "SKILLS_DIR"),
            "SKILLS_DIR": getattr(module, "SKILLS_DIR", None),
        }
    return snapshot


def patch_skill_home_modules(home: Path) -> None:
    """Patch imported skill modules that cache HERMES_HOME at import time."""
    for module_name in _SKILL_HOME_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        try:
            module.HERMES_HOME = home
            module.SKILLS_DIR = home / "skills"
        except AttributeError:
            logger.debug("Failed to patch %s module", module_name)


_VIRTUAL_PATH_TOOL_PATCHES = (
    ("tools.terminal_tool", "terminal_tool", ("command", "workdir")),
    ("tools.code_execution_tool", "execute_code", ("code",)),
)


def _resolve_virtual_path_rewrite_profile_home() -> Path | None:
    try:
        return get_active_hermes_home()
    except Exception:
        home = os.environ.get("HERMES_HOME")
        return Path(home).expanduser() if home else None


def patch_terminal_virtual_path_rewrite() -> None:
    """Rewrite ``/workspace/...`` in terminal/execute_code args before execution."""
    try:
        from app.domain.workspace import (
            nested_workspaces_enabled,
            rewrite_virtual_paths_in_shell_command,
        )
    except ImportError:
        return
    if not nested_workspaces_enabled():
        return

    def _make_wrapper(original, arg_names):
        primary = arg_names[0]

        @functools.wraps(original)
        def _wrapped(*args, **kwargs):
            profile_home = _resolve_virtual_path_rewrite_profile_home()
            if args and isinstance(args[0], str) and args[0]:
                args = (
                    rewrite_virtual_paths_in_shell_command(
                        args[0],
                        profile_home=profile_home,
                    ),
                    *args[1:],
                )
            for name in arg_names:
                value = kwargs.get(name)
                if isinstance(value, str) and value:
                    kwargs[name] = rewrite_virtual_paths_in_shell_command(
                        value,
                        profile_home=profile_home,
                    )
            return original(*args, **kwargs)

        _wrapped._hermes_webui_virtual_rewrite = True  # type: ignore[attr-defined]
        _wrapped._hermes_webui_original = original  # type: ignore[attr-defined]
        _wrapped._hermes_webui_primary_arg = primary  # type: ignore[attr-defined]
        return _wrapped

    for module_name, attr_name, arg_names in _VIRTUAL_PATH_TOOL_PATCHES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        original = getattr(module, attr_name, None)
        if original is None or getattr(original, "_hermes_webui_virtual_rewrite", False):
            continue
        setattr(module, attr_name, _make_wrapper(original, arg_names))


_FILE_TOOL_CONTAINMENT_PATCHES = (
    ("tools.file_tools", "read_file_tool", "path"),
    ("tools.file_tools", "write_file_tool", "path"),
    ("tools.file_tools", "patch_tool", "path"),
    ("tools.file_tools", "search_tool", "path"),
)

_VISION_PATH_TOOL_PATCHES = (
    ("tools.vision_tools", "vision_analyze_tool", "image_url"),
    ("tools.vision_tools", "_vision_analyze_native", "image_url"),
)


def _guard_resolved_file_tool_path(path: str, *, tool_name: str, task_id: str = "default") -> None:
    resolved = path
    try:
        from tools.file_tools import _resolve_path_for_task

        resolved = str(_resolve_path_for_task(path, task_id))
    except Exception:
        try:
            base = os.environ.get("TERMINAL_CWD", os.getcwd())
            candidate = Path(path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(base) / candidate
            resolved = str(candidate.resolve())
        except OSError:
            resolved = path
    from app.domain.workspace import assert_account_workspace_path

    assert_account_workspace_path(resolved, tool_name=tool_name)


def _rewrite_file_tool_path(path_value: str) -> str:
    try:
        from app.domain.workspace import rewrite_virtual_path_in_file_arg
    except ImportError:
        return path_value
    profile_home = _resolve_virtual_path_rewrite_profile_home()
    return rewrite_virtual_path_in_file_arg(
        path_value,
        profile_home=profile_home,
        terminal_cwd=os.environ.get("TERMINAL_CWD"),
        active_workspace_virtual=os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL"),
    )


def _apply_rewritten_file_tool_path(
    path_value: str,
    *,
    path_kw: str,
    original,
    args: tuple,
    kwargs: dict,
) -> tuple[tuple, dict, str]:
    rewritten = _rewrite_file_tool_path(path_value)
    if path_kw in kwargs:
        kwargs = dict(kwargs)
        kwargs[path_kw] = rewritten
    elif path_kw == "path" and original.__name__ == "patch_tool" and len(args) >= 2:
        args = (args[0], rewritten, *args[2:])
    elif args and isinstance(args[0], str):
        args = (rewritten, *args[1:])
    return args, kwargs, rewritten


def _rewrite_vision_image_url(image_url: str) -> str:
    try:
        from app.domain.upload import resolve_agent_attachment_path
    except ImportError:
        return image_url
    terminal_cwd = os.environ.get("TERMINAL_CWD")
    virtual = os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL")
    return resolve_agent_attachment_path(
        image_url,
        session_workspace=terminal_cwd or virtual,
    )


def _custom_endpoint_supports_ollama_think(base_url: str) -> bool:
    """True when a custom OpenAI-compatible base URL is Ollama (``extra_body.think``)."""
    url = (base_url or "").strip()
    if not url:
        return False
    lower = url.lower()
    if "ollama.com" in lower:
        return True
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except Exception:
        return False
    return parsed.port == 11434


def _strip_non_ollama_think_param(api_kwargs: dict, base_url: str) -> dict:
    """Drop Ollama-only ``extra_body.think`` for LiteLLM/vLLM/RunPod custom routes."""
    if _custom_endpoint_supports_ollama_think(base_url):
        return api_kwargs
    extra = api_kwargs.get("extra_body")
    if not isinstance(extra, dict) or "think" not in extra:
        return api_kwargs
    patched = dict(api_kwargs)
    cleaned = dict(extra)
    cleaned.pop("think", None)
    if cleaned:
        patched["extra_body"] = cleaned
    else:
        patched.pop("extra_body", None)
    return patched


def apply_agent_runtime_patches() -> None:
    """Install process-global Hermes Agent hooks required by WebUI.

    Called at server startup and again before each streaming worker run so
    custom multimodal models (e.g. Qwen3.6 GGUF) are not misclassified as
    text-only and stripped from API payloads.
    """
    patch_extended_vision_capability_lookup()
    patch_custom_provider_think_param()


def patch_custom_provider_think_param() -> None:
    """Strip Ollama-only ``extra_body.think`` from non-Ollama custom provider calls.

    Hermes Agent's custom provider profile injects ``think=false`` when reasoning
    is disabled (title generation, ``reasoning_effort: none``). The OpenAI Python
    SDK promotes that to a top-level ``think`` kwarg, which LiteLLM forwards to
  vLLM/RunPod backends that reject it with HTTP 500.
    """
    try:
        import agent.chat_completion_helpers as chat_helpers
    except ImportError:
        return

    original = chat_helpers.build_api_kwargs
    if getattr(original, "_hermes_webui_think_gated", False):
        return

    @functools.wraps(original)
    def build_api_kwargs(agent, api_messages):
        kwargs = original(agent, api_messages)
        if (getattr(agent, "provider", "") or "").strip().lower() != "custom":
            return kwargs
        return _strip_non_ollama_think_param(
            kwargs,
            getattr(agent, "base_url", "") or "",
        )

    build_api_kwargs._hermes_webui_think_gated = True  # type: ignore[attr-defined]
    build_api_kwargs._hermes_webui_original = original  # type: ignore[attr-defined]
    chat_helpers.build_api_kwargs = build_api_kwargs


def patch_extended_vision_capability_lookup() -> None:
    """Extend agent vision lookup for custom/local multimodal models.

    ``run_agent.AIAgent._model_supports_vision()`` and
    ``agent.image_routing.decide_image_input_mode()`` consult
    ``_lookup_supports_vision``, which only knows models.dev metadata.
    Without this patch, WebUI may embed native ``image_url`` parts but the
    agent strips them before the provider call for Qwen3.6-style custom GGUF
    endpoints.
    """
    try:
        import agent.image_routing as image_routing
    except ImportError:
        return

    original = image_routing._lookup_supports_vision
    if getattr(original, "_hermes_webui_extended", False):
        return

    def _lookup_supports_vision(provider, model, cfg=None):
        result = original(provider, model, cfg)
        if result is True:
            return True
        try:
            from app.domain.streaming import _webui_extended_supports_vision

            if _webui_extended_supports_vision(cfg, provider=provider, model=model):
                return True
        except Exception:
            pass
        return result

    _lookup_supports_vision._hermes_webui_extended = True  # type: ignore[attr-defined]
    _lookup_supports_vision._hermes_webui_original = original  # type: ignore[attr-defined]
    image_routing._lookup_supports_vision = _lookup_supports_vision


def patch_vision_virtual_path_rewrite() -> None:
    """Rewrite ``/workspace/.uploads/...`` before vision tools open local files."""
    try:
        from app.domain.workspace import nested_workspaces_enabled
    except ImportError:
        return
    if not nested_workspaces_enabled():
        return

    def _make_wrapper(original, path_kw: str):
        @functools.wraps(original)
        async def _wrapped(*args, **kwargs):
            path_value = kwargs.get(path_kw)
            if not isinstance(path_value, str) or not path_value:
                if args and isinstance(args[0], str):
                    path_value = args[0]
            if isinstance(path_value, str) and path_value:
                rewritten = _rewrite_vision_image_url(path_value)
                if path_kw in kwargs:
                    kwargs = dict(kwargs)
                    kwargs[path_kw] = rewritten
                elif args and isinstance(args[0], str):
                    args = (rewritten, *args[1:])
            return await original(*args, **kwargs)

        _wrapped._hermes_webui_vision_path_rewrite = True  # type: ignore[attr-defined]
        _wrapped._hermes_webui_original = original  # type: ignore[attr-defined]
        return _wrapped

    for module_name, attr_name, path_kw in _VISION_PATH_TOOL_PATCHES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        original = getattr(module, attr_name, None)
        if original is None or getattr(original, "_hermes_webui_vision_path_rewrite", False):
            continue
        setattr(module, attr_name, _make_wrapper(original, path_kw))


def patch_account_workspace_containment() -> None:
    """Block agent file tools from reading or writing outside the account workspace."""
    try:
        from app.domain.workspace import nested_workspaces_enabled
    except ImportError:
        return
    if not nested_workspaces_enabled():
        return

    def _make_file_wrapper(original, path_kw: str):
        @functools.wraps(original)
        def _wrapped(*args, **kwargs):
            task_id = str(kwargs.get("task_id", "default"))
            path_value = kwargs.get(path_kw)
            if not isinstance(path_value, str) or not path_value:
                if path_kw == "path" and original.__name__ == "patch_tool" and len(args) >= 2:
                    path_value = args[1]
                elif args and isinstance(args[0], str):
                    path_value = args[0]
            if isinstance(path_value, str) and path_value:
                args, kwargs, rewritten = _apply_rewritten_file_tool_path(
                    path_value,
                    path_kw=path_kw,
                    original=original,
                    args=args,
                    kwargs=kwargs,
                )
                _guard_resolved_file_tool_path(
                    rewritten,
                    tool_name=original.__name__,
                    task_id=task_id,
                )
            return original(*args, **kwargs)

        _wrapped._hermes_webui_workspace_containment = True  # type: ignore[attr-defined]
        _wrapped._hermes_webui_original = original  # type: ignore[attr-defined]
        return _wrapped

    for module_name, attr_name, path_kw in _FILE_TOOL_CONTAINMENT_PATCHES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        original = getattr(module, attr_name, None)
        if original is None or getattr(original, "_hermes_webui_workspace_containment", False):
            continue
        setattr(module, attr_name, _make_file_wrapper(original, path_kw))


def patch_execute_code_session_approval() -> None:
    """Honor session/permanent execute_code approvals in ask/gateway mode."""
    module = sys.modules.get("tools.approval")
    if module is None:
        return
    original = getattr(module, "check_execute_code_guard", None)
    if original is None or getattr(original, "_hermes_webui_session_check", False):
        return

    @functools.wraps(original)
    def _wrapped(code: str, env_type: str):
        try:
            from tools.approval import get_current_session_key, is_approved
        except ImportError:
            return original(code, env_type)
        if is_approved(get_current_session_key(), "execute_code"):
            return {"approved": True, "message": None}
        return original(code, env_type)

    _wrapped._hermes_webui_session_check = True  # type: ignore[attr-defined]
    _wrapped._hermes_webui_original = original  # type: ignore[attr-defined]
    module.check_execute_code_guard = _wrapped


def restore_skill_home_modules(snapshot: dict[str, dict[str, object]]) -> None:
    """Restore skill-module globals captured by snapshot_skill_home_modules()."""
    for module_name, values in snapshot.items():
        module = sys.modules.get(module_name)
        if not values.get("module_present"):
            if module is not None:
                sys.modules.pop(module_name, None)
                parent_name, _, child_name = module_name.rpartition(".")
                parent = sys.modules.get(parent_name)
                if parent is not None:
                    try:
                        delattr(parent, child_name)
                    except AttributeError:
                        pass
            continue
        if module is None:
            continue
        for attr in ("HERMES_HOME", "SKILLS_DIR"):
            has_attr = bool(values.get(f"has_{attr}"))
            try:
                if has_attr:
                    setattr(module, attr, values.get(attr))
                else:
                    try:
                        delattr(module, attr)
                    except AttributeError:
                        pass
            except AttributeError:
                logger.debug("Failed to restore %s.%s", module_name, attr)


def _unwrap_profile_home_to_base(home: Path) -> Path:
    """Return the base Hermes home when *home* is already a named profile dir."""
    if home.parent.name == 'profiles':
        return home.parent.parent
    return home


def _resolve_base_hermes_home() -> Path:
    """Return the BASE ~/.hermes directory — the root that contains profiles/.

    This is intentionally distinct from HERMES_HOME, which tracks the *active
    profile's* home and changes on every profile switch.  The base dir must
    always point to the top-level .hermes regardless of which profile is active.

    Resolution order:
      1. HERMES_BASE_HOME env var (set explicitly, highest priority)
      2. HERMES_HOME env var — but only if it does NOT look like a profile subdir
         (i.e. its parent is not named 'profiles').  This handles test isolation
         where HERMES_HOME is set to an isolated test state dir.
      3. ~/.hermes (always-correct default)

    The bug this prevents: if HERMES_HOME has already been mutated to
    /home/user/.hermes/profiles/webui (by init_profile_state at startup),
    reading it here would make _DEFAULT_HERMES_HOME point to that subdir,
    causing switch_profile('webui') to look for
    /home/user/.hermes/profiles/webui/profiles/webui — which doesn't exist.

    HERMES_BASE_HOME normally points at the base home already, but isolated
    single-profile WebUI deployments can provide /base/profiles/<name> there as
    well.  Normalize both env vars through the same helper so active-profile
    and per-request resolution share one base-root contract (#749).
    """
    # Explicit override for tests or unusual setups
    base_override = os.getenv('HERMES_BASE_HOME', '').strip()
    if base_override:
        return _unwrap_profile_home_to_base(Path(base_override).expanduser())

    hermes_home = os.getenv('HERMES_HOME', '').strip()
    if hermes_home:
        p = Path(hermes_home).expanduser()
        # If HERMES_HOME points to a profiles/ subdir, walk up two levels to the base
        return _unwrap_profile_home_to_base(p)

    try:
        from app.domain.config import _platform_default_hermes_home

        return _platform_default_hermes_home()
    except ImportError:
        return Path.home() / '.hermes'

_DEFAULT_HERMES_HOME = _resolve_base_hermes_home()


def _read_active_profile_file() -> str:
    """Read the sticky active profile from ~/.hermes/active_profile."""
    ap_file = _DEFAULT_HERMES_HOME / 'active_profile'
    if ap_file.exists():
        try:
            name = ap_file.read_text(encoding="utf-8").strip()
            if name:
                return name
        except Exception:
            logger.debug("Failed to read active profile file")
    return 'default'


# ── Public API ──────────────────────────────────────────────────────────────

# ── Root-profile resolution (#1612) ────────────────────────────────────────
#
# Hermes Agent allows the root/default profile (~/.hermes itself) to have a
# display name other than the legacy literal 'default'.  When that happens,
# WebUI must NOT resolve the display name as ~/.hermes/profiles/<name> — that
# directory doesn't exist, and every site that does `if name == 'default':`
# will fall through to the wrong filesystem path.
#
# `_is_root_profile(name)` answers "does this name resolve to ~/.hermes?" and
# is the canonical replacement for scattered `if name == 'default':` checks
# in switch_profile, get_active_hermes_home, _validate_profile_name, etc.
#
# Cost note: list_profiles_api() shells out via hermes_cli (non-trivial), so
# we memoize the lookup. The cache is invalidated whenever profiles are
# created, deleted, renamed, or cloned — i.e. on every mutation site we
# control.
_root_profile_name_cache: set[str] = {'default'}
_root_profile_name_cache_lock = threading.Lock()
_root_profile_name_cache_loaded = False
_profiles_list_cache: list | None = None
_profiles_list_cache_at: float = 0.0
_profiles_list_cache_lock = threading.Lock()
_PROFILES_LIST_CACHE_TTL_SEC = 5.0


def _invalidate_profiles_list_cache() -> None:
    global _profiles_list_cache, _profiles_list_cache_at
    with _profiles_list_cache_lock:
        _profiles_list_cache = None
        _profiles_list_cache_at = 0.0


def _invalidate_root_profile_cache() -> None:
    """Drop the memoized root-profile-name set.

    Called whenever profile metadata might have changed: create, clone,
    delete, rename. The next _is_root_profile() call repopulates from
    list_profiles_api().
    """
    global _root_profile_name_cache_loaded
    with _root_profile_name_cache_lock:
        _root_profile_name_cache.clear()
        _root_profile_name_cache.add('default')
        _root_profile_name_cache_loaded = False
    _invalidate_profiles_list_cache()


def _is_root_profile(name: str) -> bool:
    """True if *name* resolves to the Hermes Agent root profile (~/.hermes).

    Matches the legacy 'default' alias plus any name where hermes_cli
    list_profiles() reports is_default=True. Memoized; call
    _invalidate_root_profile_cache() after mutating profile metadata.
    """
    global _root_profile_name_cache_loaded
    if not name:
        return False
    if name == 'default':
        return True
    with _root_profile_name_cache_lock:
        if _root_profile_name_cache_loaded:
            return name in _root_profile_name_cache
    # Cache miss — populate from hermes_cli.list_profiles(). Must NOT call
    # list_profiles_api() here: that helper calls _home_for_profile_name() which
    # calls back into _is_root_profile() and infinite-recurses (#profile_filter hang).
    try:
        from hermes_cli.profiles import list_profiles
        infos = list_profiles()
    except Exception:
        logger.debug("Failed to list profiles for root-profile lookup", exc_info=True)
        return False
    with _root_profile_name_cache_lock:
        _root_profile_name_cache.clear()
        _root_profile_name_cache.add('default')
        for p in infos:
            try:
                if p.is_default and p.name:
                    _root_profile_name_cache.add(p.name)
            except AttributeError:
                continue
        _root_profile_name_cache_loaded = True
        return name in _root_profile_name_cache


def _profiles_match(row_profile, active_profile) -> bool:
    """Return True if a session/project row's profile matches the active profile.

    Treats both the literal alias 'default' and any renamed-root display name
    (per _is_root_profile) as equivalent, so legacy rows tagged 'default'
    still surface when the user has renamed the root profile to e.g. 'kinni',
    and vice versa.

    A row with no profile (`None` or empty string) is treated as belonging to
    the root profile — that's the convention used by the legacy backfill at
    api/models.py::all_sessions, and matches the default seen in
    `static/sessions.js` (`S.activeProfile||'default'`).

    Originally lived in api/routes.py; relocated here so both routes.py and
    out-of-process consumers (mcp_server.py) can import the canonical helper
    instead of duplicating the body. See #1614 for the visibility model.
    """
    row = row_profile or 'default'
    active = active_profile or 'default'
    if row == active:
        return True
    # Cross-alias the renamed root.
    if _is_root_profile(row) and _is_root_profile(active):
        return True
    return False


def get_active_profile_name() -> str:
    """Return the currently active profile name.

    Priority:
      1. Per-request context var (set per-request from hermes_profile cookie),
         which propagates from the async middleware into sync threadpool route
         handlers — issues #798 and profile-context-threadpool.
      2. Process-level default (_active_profile), used outside request handling
         (CLI, background threads, startup).
    """
    request_name = _request_profile.get()
    if request_name is not None:
        return request_name
    return _active_profile


def set_request_profile(name: str) -> None:
    """Set the per-request profile context.

    Called by ProfileContextMiddleware at the start of each request when a
    hermes_profile cookie is present.  Always paired with
    clear_request_profile() in a finally block so the context is released after
    the request.  Stored in a contextvars.ContextVar so the value propagates
    into anyio threadpool workers that run sync route handlers.
    """
    _request_profile.set(name)


def clear_request_profile() -> None:
    """Clear the per-request profile context.

    Called by ProfileContextMiddleware in the finally block of each request.
    Safe to call even if set_request_profile() was never called; restores the
    fallback to the process-global _active_profile.
    """
    _request_profile.set(None)


def _resolve_profile_home_for_name(name: str) -> Path:
    """Resolve a logical profile name to its Hermes home path.

    Root/default aliases resolve to _DEFAULT_HERMES_HOME.  Valid named profiles
    resolve to _DEFAULT_HERMES_HOME/profiles/<name> even when the directory has
    not been created yet; the agent layer may create it on first use.  Invalid
    names fall back to the base home so traversal-shaped cookie values cannot
    influence filesystem paths.
    """
    if not name or _is_root_profile(name):
        return _DEFAULT_HERMES_HOME
    if not _PROFILE_ID_RE.fullmatch(name):
        return _DEFAULT_HERMES_HOME
    return _resolve_named_profile_home(name)


def get_active_hermes_home() -> Path:
    """Return the HERMES_HOME path for the currently active profile.

    Uses get_active_profile_name() so the per-request profile context (issue
    #798) is respected, not just the process-level global. The context
    propagates into sync threadpool handlers via a contextvars.ContextVar.
    """
    return _resolve_profile_home_for_name(get_active_profile_name())



# ── Cron-call profile isolation (issue: Scheduled jobs ignored active profile) ─
# `cron.jobs` reads HERMES_HOME from os.environ (process-global) at function-
# call time. That bypasses our per-request thread-local profile, so the
# `/api/crons*` endpoints always returned the process-default profile's jobs.
# This context manager swaps HERMES_HOME (and the cached module-level constants
# in cron.jobs) for the duration of a cron call, serialized by a lock so
# concurrent requests from different profiles don't race on the global env var.
#
# Thread-safety note on os.environ mutation:
# CPython's os.environ assignment is GIL-protected at the bytecode level, but
# multi-step read-modify-write sequences (snapshot prev → assign new → restore
# on exit) are NOT atomic without explicit serialization. The _cron_env_lock
# below makes the entire context-manager body run-to-completion serially, so
# all webui access to HERMES_HOME goes through one thread at a time. Any
# subprocess.Popen() call inside `run_job` inherits the env at fork time,
# which is also under the lock — so child processes always see a consistent
# (own-profile) HERMES_HOME, never a half-swapped state.
_cron_env_lock = threading.Lock()


def _cron_profile_context_depth() -> int:
    return int(getattr(_tls, 'cron_profile_depth', 0) or 0)


def _push_cron_profile_context_depth() -> None:
    _tls.cron_profile_depth = _cron_profile_context_depth() + 1


def _pop_cron_profile_context_depth() -> None:
    depth = _cron_profile_context_depth()
    _tls.cron_profile_depth = max(0, depth - 1)


def _home_for_scheduled_cron_job(job: dict) -> Path:
    """Resolve the profile home an auto-fired scheduler job should execute in.

    Legacy jobs with no profile keep the scheduler's server-default profile.
    Jobs pinned to a named profile execute under that profile's HERMES_HOME, so
    an in-process WebUI scheduler thread does not leak process-global config or
    .env into the agent run. If a profile was deleted after the job was saved,
    fall back to the server default rather than crashing every scheduler tick.
    """
    raw = str((job or {}).get('profile') or '').strip()
    if not raw:
        return get_active_hermes_home()
    if _is_root_profile(raw):
        return _DEFAULT_HERMES_HOME
    if not _PROFILE_ID_RE.fullmatch(raw):
        logger.warning(
            "Cron job %s has invalid profile %r; falling back to server default",
            (job or {}).get('id', '?'), raw,
        )
        return get_active_hermes_home()
    home = _resolve_named_profile_home(raw)
    if not home.is_dir():
        logger.warning(
            "Cron job %s references missing profile %r; falling back to server default",
            (job or {}).get('id', '?'), raw,
        )
        return get_active_hermes_home()
    return home


def install_cron_scheduler_profile_isolation() -> None:
    """Patch cron.scheduler.run_job for WebUI in-process scheduler safety.

    Standard WebUI deployments do not start the scheduler thread in-process, but
    if a future/single-process deployment calls cron.scheduler.tick() from the
    WebUI worker, tick's background job path has no request TLS context. Wrap
    run_job so each auto-fired job's persisted ``profile`` field gets the same
    HERMES_HOME isolation as the manual /api/crons/run path.
    """
    try:
        import cron.scheduler as _cs
    except ImportError:
        logger.debug("install_cron_scheduler_profile_isolation: cron.scheduler unavailable")
        return

    original = getattr(_cs, 'run_job', None)
    if original is None or getattr(original, '_webui_profile_isolated', False):
        return

    def _webui_profile_isolated_run_job(job, *args, **kwargs):
        # Manual WebUI runs already enter cron_profile_context_for_home before
        # calling run_job. Avoid nesting the non-reentrant env lock or changing
        # the explicitly selected manual execution profile.
        if _cron_profile_context_depth() > 0:
            return original(job, *args, **kwargs)
        try:
            with cron_profile_context_for_home(_home_for_scheduled_cron_job(job)):
                return original(job, *args, **kwargs)
        finally:
            publish_session_list_changed("cron_complete")

    _webui_profile_isolated_run_job._webui_profile_isolated = True
    _webui_profile_isolated_run_job._webui_original_run_job = original
    _cs.run_job = _webui_profile_isolated_run_job


class cron_profile_context_for_home:
    """Context manager that pins HERMES_HOME to an explicit profile home path.

    Use this variant from worker threads that don't have TLS context (e.g. the
    background thread started by /api/crons/run). The HTTP-side variant below
    resolves the home via TLS.
    """

    def __init__(self, home: Path):
        self._home = Path(home)

    def __enter__(self):
        _cron_env_lock.acquire()
        _push_cron_profile_context_depth()
        try:
            self._prev_env = os.environ.get('HERMES_HOME')
            self._prev_kanban_home = os.environ.get('HERMES_KANBAN_HOME')
            os.environ['HERMES_HOME'] = str(self._home)
            os.environ['HERMES_KANBAN_HOME'] = str(self._home)

            # Re-patch cron.jobs module-level constants (see main context manager
            # below for the rationale).
            self._prev_cj = None
            try:
                import cron.jobs as _cj
                self._prev_cj = (_cj.HERMES_DIR, _cj.CRON_DIR, _cj.JOBS_FILE, _cj.OUTPUT_DIR)
                _cj.HERMES_DIR = self._home
                _cj.CRON_DIR = self._home / 'cron'
                _cj.JOBS_FILE = _cj.CRON_DIR / 'jobs.json'
                _cj.OUTPUT_DIR = _cj.CRON_DIR / 'output'
            except (ImportError, AttributeError):
                logger.debug("cron_profile_context_for_home: cron.jobs unavailable")

            # cron.scheduler snapshots _hermes_home at import time and run_job()
            # reads config/.env from that module global. Patch it alongside
            # cron.jobs so manual WebUI runs actually execute under the selected
            # profile, not merely write output metadata there (#617).
            self._prev_cs = None
            try:
                import cron.scheduler as _cs
                self._prev_cs = (
                    getattr(_cs, '_hermes_home', None),
                    getattr(_cs, '_LOCK_DIR', None),
                    getattr(_cs, '_LOCK_FILE', None),
                )
                _cs._hermes_home = self._home
                _cs._LOCK_DIR = self._home / 'cron'
                _cs._LOCK_FILE = _cs._LOCK_DIR / '.tick.lock'
            except (ImportError, AttributeError):
                logger.debug("cron_profile_context_for_home: cron.scheduler unavailable")
        except Exception:
            _pop_cron_profile_context_depth()
            _cron_env_lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._prev_env is None:
                os.environ.pop('HERMES_HOME', None)
            else:
                os.environ['HERMES_HOME'] = self._prev_env
            if getattr(self, '_prev_kanban_home', None) is None:
                os.environ.pop('HERMES_KANBAN_HOME', None)
            else:
                os.environ['HERMES_KANBAN_HOME'] = self._prev_kanban_home
            if self._prev_cj is not None:
                try:
                    import cron.jobs as _cj
                    _cj.HERMES_DIR, _cj.CRON_DIR, _cj.JOBS_FILE, _cj.OUTPUT_DIR = self._prev_cj
                except (ImportError, AttributeError):
                    pass
            if getattr(self, '_prev_cs', None) is not None:
                try:
                    import cron.scheduler as _cs
                    _cs._hermes_home, _cs._LOCK_DIR, _cs._LOCK_FILE = self._prev_cs
                except (ImportError, AttributeError):
                    pass
        finally:
            _pop_cron_profile_context_depth()
            _cron_env_lock.release()
        return False


class cron_profile_context:
    """Context manager that pins HERMES_HOME to the TLS-active profile.

    Usage:
        with cron_profile_context():
            from cron.jobs import list_jobs
            jobs = list_jobs(include_disabled=True)

    Serializes cron API calls across profiles (cron API is low-frequency;
    serialization cost is negligible compared to correctness).
    """

    def __enter__(self):
        _cron_env_lock.acquire()
        _push_cron_profile_context_depth()
        try:
            self._prev_env = os.environ.get('HERMES_HOME')
            self._prev_kanban_home = os.environ.get('HERMES_KANBAN_HOME')
            home = get_active_hermes_home()
            os.environ['HERMES_HOME'] = str(home)
            # Per-profile Kanban DB under <profile_home>/kanban.db (WebUI tabs).
            os.environ['HERMES_KANBAN_HOME'] = str(home)

            # Re-patch cron.jobs module-level constants. They are snapshot at
            # import time (line 68-71 of cron/jobs.py) and don't participate in
            # the module's __getattr__ lazy path, so env-var alone is not enough
            # for callers that reference the module constants directly.
            self._prev_cj = None
            try:
                import cron.jobs as _cj
                self._prev_cj = (_cj.HERMES_DIR, _cj.CRON_DIR, _cj.JOBS_FILE, _cj.OUTPUT_DIR)
                _cj.HERMES_DIR = home
                _cj.CRON_DIR = home / 'cron'
                _cj.JOBS_FILE = _cj.CRON_DIR / 'jobs.json'
                _cj.OUTPUT_DIR = _cj.CRON_DIR / 'output'
            except (ImportError, AttributeError):
                logger.debug("cron_profile_context: cron.jobs unavailable; env-var only")

            self._prev_cs = None
            try:
                import cron.scheduler as _cs
                self._prev_cs = (
                    getattr(_cs, '_hermes_home', None),
                    getattr(_cs, '_LOCK_DIR', None),
                    getattr(_cs, '_LOCK_FILE', None),
                )
                _cs._hermes_home = home
                _cs._LOCK_DIR = home / 'cron'
                _cs._LOCK_FILE = _cs._LOCK_DIR / '.tick.lock'
            except (ImportError, AttributeError):
                logger.debug("cron_profile_context: cron.scheduler unavailable; env-var only")
        except Exception:
            _pop_cron_profile_context_depth()
            _cron_env_lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            # Restore env var
            if self._prev_env is None:
                os.environ.pop('HERMES_HOME', None)
            else:
                os.environ['HERMES_HOME'] = self._prev_env
            if getattr(self, '_prev_kanban_home', None) is None:
                os.environ.pop('HERMES_KANBAN_HOME', None)
            else:
                os.environ['HERMES_KANBAN_HOME'] = self._prev_kanban_home

            # Restore cron.jobs module constants
            if self._prev_cj is not None:
                try:
                    import cron.jobs as _cj
                    _cj.HERMES_DIR, _cj.CRON_DIR, _cj.JOBS_FILE, _cj.OUTPUT_DIR = self._prev_cj
                except (ImportError, AttributeError):
                    pass
            if getattr(self, '_prev_cs', None) is not None:
                try:
                    import cron.scheduler as _cs
                    _cs._hermes_home, _cs._LOCK_DIR, _cs._LOCK_FILE = self._prev_cs
                except (ImportError, AttributeError):
                    pass
        finally:
            _pop_cron_profile_context_depth()
            _cron_env_lock.release()
        return False


# Alias for non-cron HTTP handlers (Kanban, etc.) that delegate to hermes_cli
# code reading os.environ at call time. Uses the same lock + env pinning.
profile_request_context = cron_profile_context


def get_hermes_home_for_profile(name: str) -> Path:
    """Return the HERMES_HOME Path for *name* without mutating any process state.

    Safe to call from per-request context (streaming, session creation) because
    it reads only the filesystem — it never touches os.environ, module-level
    cached paths, or the process-level _active_profile global.

    Falls back to _DEFAULT_HERMES_HOME (same as 'default') when *name* is None,
    empty, 'default', or does not match the profile-name format (rejects path
    traversal such as '../../etc').
    """
    return _resolve_profile_home_for_name(name)


_TERMINAL_ENV_MAPPINGS = {
    'backend': 'TERMINAL_ENV',
    'env_type': 'TERMINAL_ENV',
    'cwd': 'TERMINAL_CWD',
    'timeout': 'TERMINAL_TIMEOUT',
    'lifetime_seconds': 'TERMINAL_LIFETIME_SECONDS',
    'modal_mode': 'TERMINAL_MODAL_MODE',
    'docker_image': 'TERMINAL_DOCKER_IMAGE',
    'docker_forward_env': 'TERMINAL_DOCKER_FORWARD_ENV',
    'docker_env': 'TERMINAL_DOCKER_ENV',
    'docker_mount_cwd_to_workspace': 'TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE',
    'singularity_image': 'TERMINAL_SINGULARITY_IMAGE',
    'modal_image': 'TERMINAL_MODAL_IMAGE',
    'daytona_image': 'TERMINAL_DAYTONA_IMAGE',
    'container_cpu': 'TERMINAL_CONTAINER_CPU',
    'container_memory': 'TERMINAL_CONTAINER_MEMORY',
    'container_disk': 'TERMINAL_CONTAINER_DISK',
    'container_persistent': 'TERMINAL_CONTAINER_PERSISTENT',
    'docker_volumes': 'TERMINAL_DOCKER_VOLUMES',
    'persistent_shell': 'TERMINAL_PERSISTENT_SHELL',
    'ssh_host': 'TERMINAL_SSH_HOST',
    'ssh_user': 'TERMINAL_SSH_USER',
    'ssh_port': 'TERMINAL_SSH_PORT',
    'ssh_key': 'TERMINAL_SSH_KEY',
    'ssh_persistent': 'TERMINAL_SSH_PERSISTENT',
    'local_persistent': 'TERMINAL_LOCAL_PERSISTENT',
}


def _stringify_env_value(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def get_profile_runtime_env(home: Path) -> dict[str, str]:
    """Return env vars needed to run an agent turn for a profile home.

    WebUI profile switching is per-client/cookie scoped, so it intentionally
    does not call ``switch_profile(..., process_wide=True)`` for every browser.
    Agent/tool code still consumes terminal backend settings through
    environment variables (matching ``hermes -p <profile>``), so streaming must
    apply the selected profile's terminal config and ``.env`` for the duration
    of that run.
    """
    home = Path(home).expanduser()
    env: dict[str, str] = {}

    try:
        import yaml as _yaml

        cfg_path = home / 'config.yaml'
        cfg = _yaml.safe_load(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}

    terminal_cfg = cfg.get('terminal', {}) if isinstance(cfg, dict) else {}
    if isinstance(terminal_cfg, dict):
        for key, env_key in _TERMINAL_ENV_MAPPINGS.items():
            if key in terminal_cfg and terminal_cfg[key] is not None:
                env[env_key] = _stringify_env_value(terminal_cfg[key])

    env_path = home / '.env'
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        env[k] = v
        except Exception:
            logger.debug("Failed to read runtime env from %s", env_path)

    return env


@contextmanager
def profile_env_for_background_worker(
    session,
    purpose: str = "background worker",
    logger_override: Optional[logging.Logger] = None,
):
    """Temporarily route detached worker config reads through a profile.

    Background WebUI workers run outside the request/streaming thread that
    established the profile-scoped environment.  Workers that read agent config,
    runtime provider settings, or skill paths must temporarily apply the
    session/request profile env or they can fall back to the server-default
    profile. Pass either a session-like object with `.profile` or a profile name.
    """
    log = logger_override or logger
    raw_profile = session if isinstance(session, str) else getattr(session, "profile", "")
    profile = str(raw_profile or "").strip()
    if not profile or profile == "default":
        yield
        return

    try:
        # Lazy imports avoid a module-load cycle: streaming imports this helper.
        from app.domain.config import _clear_thread_env, _set_thread_env, _thread_ctx
        from app.domain.streaming import _ENV_LOCK

        profile_home_path = Path(get_hermes_home_for_profile(profile))
        runtime_env = get_profile_runtime_env(profile_home_path)
    except Exception:
        log.debug(
            "Failed to resolve profile env for %s profile %s; falling back to current env",
            purpose,
            profile,
            exc_info=True,
        )
        yield
        return

    thread_env = dict(runtime_env)
    thread_env["HERMES_HOME"] = str(profile_home_path)
    # Hybrid profile routing: keep the broad runtime env in WebUI's thread-local
    # channel for WebUI helpers, and also mirror it into process env for the
    # worker body because several production Hermes readers still call
    # os.getenv() directly for provider credentials.  Keep the _ENV_LOCK scope
    # narrow: serialize only setup/restore, not the whole worker body.
    skill_home_snapshot = None
    old_runtime_env: dict[str, Optional[str]] = {}
    old_hermes_home = None
    had_hermes_home = False
    previous_thread_env = getattr(_thread_ctx, "env", {}).copy()
    try:
        _set_thread_env(**thread_env)
        with _ENV_LOCK:
            old_runtime_env = {key: os.environ.get(key) for key in runtime_env}
            had_hermes_home = "HERMES_HOME" in os.environ
            old_hermes_home = os.environ.get("HERMES_HOME")
            skill_home_snapshot = snapshot_skill_home_modules()
            os.environ.update(runtime_env)
            os.environ["HERMES_HOME"] = str(profile_home_path)
            try:
                patch_skill_home_modules(profile_home_path)
            except Exception:
                log.debug(
                    "Failed to patch skill modules for %s profile %s",
                    purpose,
                    profile,
                    exc_info=True,
                )
        yield
    finally:
        if previous_thread_env:
            _set_thread_env(**previous_thread_env)
        else:
            _clear_thread_env()
        with _ENV_LOCK:
            for key, old_value in old_runtime_env.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value
            if had_hermes_home:
                os.environ["HERMES_HOME"] = old_hermes_home or ""
            else:
                os.environ.pop("HERMES_HOME", None)
            if skill_home_snapshot is not None:
                restore_skill_home_modules(skill_home_snapshot)


def _set_hermes_home(home: Path):
    """Set HERMES_HOME env var and monkey-patch cached module-level paths."""
    os.environ['HERMES_HOME'] = str(home)

    patch_skill_home_modules(home)

    # Patch cron/jobs module-level cache
    try:
        import cron.jobs as _cj
        _cj.HERMES_DIR = home
        _cj.CRON_DIR = home / 'cron'
        _cj.JOBS_FILE = _cj.CRON_DIR / 'jobs.json'
        _cj.OUTPUT_DIR = _cj.CRON_DIR / 'output'
    except (ImportError, AttributeError):
        logger.debug("Failed to patch cron.jobs module")

    try:
        import cron.scheduler as _cs
        _cs._hermes_home = home
        _cs._LOCK_DIR = home / 'cron'
        _cs._LOCK_FILE = _cs._LOCK_DIR / '.tick.lock'
    except (ImportError, AttributeError):
        logger.debug("Failed to patch cron.scheduler module")


def _reload_dotenv(home: Path):
    """Load .env from the profile dir into os.environ with profile isolation.

    Clears env vars that were loaded from the previously active profile before
    applying the current profile's .env. This prevents API keys and other
    profile-scoped secrets from leaking across profile switches.
    """
    global _loaded_profile_env_keys

    # Remove keys loaded from the previous profile first.
    for key in list(_loaded_profile_env_keys):
        os.environ.pop(key, None)
    _loaded_profile_env_keys = set()

    env_path = home / '.env'
    if not env_path.exists():
        return
    try:
        loaded_keys: set[str] = set()
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v:
                    os.environ[k] = v
                    loaded_keys.add(k)
        _loaded_profile_env_keys = loaded_keys
    except Exception:
        _loaded_profile_env_keys = set()
        logger.debug("Failed to reload dotenv from %s", env_path)


def _ensure_root_profile_cache() -> None:
    """Populate the renamed-root profile name cache once per process.

    Avoids a cold ``hermes_cli.profiles.list_profiles()`` call on the first
    WebUI profile switch after worker start.
    """
    if _root_profile_name_cache_loaded:
        return
    _is_root_profile("__warmup__")


def _warm_profile_switch_imports() -> None:
    """Import profile-switch dependencies at startup, not on first user switch.

    ``_default_workspace_for_home()`` lazily imports ``api.workspace``, which
    pulls in a large dependency tree (~250ms on a typical cold import). Without
    this warmup, the first ``POST /api/profile/switch`` in each uvicorn worker
    pays that cost and feels sluggish.
    """
    try:
        from app.domain.workspace import profile_workspace_rel, resolve_profile_workspace  # noqa: F401
    except Exception:
        logger.debug("Profile switch import warmup failed", exc_info=True)
        return
    _ensure_root_profile_cache()


def init_profile_state() -> None:
    """Initialize profile state at server startup.

    Reads ~/.hermes/active_profile, sets HERMES_HOME env var, patches
    module-level cached paths.  Called once from config.py after imports.
    """
    global _active_profile
    _active_profile = _read_active_profile_file()
    home = get_active_hermes_home()
    _set_hermes_home(home)
    install_cron_scheduler_profile_isolation()
    _reload_dotenv(home)
    _warm_profile_switch_imports()


def switch_profile(name: str, *, process_wide: bool = True) -> dict:
    """Switch the active profile.

    Validates the profile exists, updates process state, patches module caches,
    reloads .env, and reloads config.yaml.

    Args:
        name: Profile name to switch to.
        process_wide: If True (default), updates the process-global
            _active_profile.  Set to False for per-client switches from the
            WebUI where the profile is managed via cookie + thread-local (#798).

    Returns: {'profiles': [...], 'active': name}
    Raises ValueError if profile doesn't exist or agent is busy.
    """
    global _active_profile

    # Import here to avoid circular import at module load
    from app.domain.config import STREAMS, STREAMS_LOCK, reload_config

    # Process-wide profile switches mutate HERMES_HOME, module-level path caches,
    # os.environ-backed .env keys, and the global config cache. Keep those blocked
    # while any agent stream is active. Per-client WebUI switches are cookie/TLS
    # scoped (process_wide=False) and do not mutate those globals, so users can
    # leave a running session in one profile and start work in another (#1700).
    if process_wide:
        with STREAMS_LOCK:
            if len(STREAMS) > 0:
                raise RuntimeError(
                    'Cannot switch profiles while an agent is running. '
                    'Cancel or wait for it to finish.'
                )

    # Resolve profile directory
    if _is_root_profile(name):
        home = _DEFAULT_HERMES_HOME
    else:
        home = _resolve_named_profile_home(name)
        if not home.is_dir():
            raise ValueError(f"Profile '{name}' does not exist.")

    if process_wide:
        with _profile_lock:
            global _active_profile
            _active_profile = name
            _set_hermes_home(home)
            _reload_dotenv(home)

    if process_wide:
        # Write sticky default for CLI consistency
        try:
            ap_file = _DEFAULT_HERMES_HOME / 'active_profile'
            ap_file.write_text('' if _is_root_profile(name) else name, encoding='utf-8')
        except Exception:
            logger.debug("Failed to write active profile file")

        # Reload config.yaml from the new profile
        reload_config()

    # Return profile-specific defaults so frontend can apply them.
    # For process_wide=False (per-client switch), read the target profile's
    # config.yaml directly from disk rather than from _cfg_cache (process-global),
    # since reload_config() was intentionally skipped.
    if process_wide:
        from app.domain.config import get_config
        cfg = get_config()
    else:
        # Direct disk read — does not touch _cfg_cache
        cfg = _load_profile_config(home)
    model_cfg = cfg.get('model', {})
    default_model = None
    default_model_provider = None
    if isinstance(model_cfg, str):
        default_model = model_cfg
    elif isinstance(model_cfg, dict):
        default_model = model_cfg.get('default')
        default_model_provider = model_cfg.get('provider')

    return {
        'active': name,
        'default_model': default_model,
        'default_model_provider': default_model_provider,
        'default_workspace': _default_workspace_for_home(home, cfg),
    }


def _load_profile_config(home: Path) -> dict:
    """Load config.yaml for *home* without touching the process-global config cache."""
    cfg_path = home / 'config.yaml'
    if not cfg_path.exists():
        return {}
    try:
        import yaml as _yaml
        loaded = _yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        logger.debug("Failed to load config from %s", cfg_path)
        return {}


def _default_workspace_for_home(home: Path, cfg: dict | None = None) -> str:
    """Return the resolved default workspace path for a profile home directory."""
    home = home.expanduser().resolve()
    if cfg is None:
        cfg = _load_profile_config(home)
    try:
        from app.domain.workspace import resolve_profile_workspace, profile_workspace_rel

        lw_file = home / 'webui_state' / 'last_workspace.txt'
        if lw_file.exists():
            raw = lw_file.read_text(encoding='utf-8').strip()
            if raw:
                resolved = resolve_profile_workspace(raw, home)
                if resolved.is_dir():
                    return str(resolved.resolve())
        for key in ('workspace', 'default_workspace'):
            value = cfg.get(key)
            if value:
                resolved = resolve_profile_workspace(str(value), home)
                if resolved.is_dir():
                    return str(resolved.resolve())
        terminal_cfg = cfg.get('terminal', {})
        if isinstance(terminal_cfg, dict):
            cwd = terminal_cfg.get('cwd', '')
            if cwd and str(cwd) not in ('.', ''):
                resolved = resolve_profile_workspace(str(cwd), home)
                if resolved.is_dir():
                    return str(resolved.resolve())
        return str(resolve_profile_workspace(profile_workspace_rel(), home).resolve())
    except Exception:
        try:
            from app.domain.config import DEFAULT_WORKSPACE as _fallback
            return str(_fallback)
        except Exception:
            return str(Path.home())


def _workspace_name_for_home(home: Path, profile_name: str) -> str:
    """Return the display name for a profile's single workspace entry."""
    from app.domain.workspace import _state_dir_for_profile_home, profile_workspace_display_name

    ws_file = _state_dir_for_profile_home(home) / 'workspaces.json'
    if ws_file.exists():
        try:
            raw = json.loads(ws_file.read_text(encoding='utf-8'))
            if isinstance(raw, list) and raw:
                name = str(raw[0].get('name') or '').strip()
                if name:
                    return name
        except Exception:
            logger.debug("Failed to read workspace name from %s", ws_file)
    if not _is_root_profile(profile_name):
        return profile_name
    return profile_workspace_display_name()


def _profile_workspace_fields(home: Path, profile_name: str) -> dict:
    """Return workspace metadata serialized for /api/profiles entries."""
    cfg = _load_profile_config(home)
    return {
        'default_workspace': _default_workspace_for_home(home, cfg),
        'workspace_name': _workspace_name_for_home(home, profile_name),
    }


def _home_for_profile_name(
    name: str,
    profile_path: Path | None = None,
    *,
    is_default: bool | None = None,
) -> Path:
    if is_default is True or (is_default is None and _is_root_profile(name)):
        return _DEFAULT_HERMES_HOME
    if profile_path is not None:
        return profile_path.expanduser().resolve()
    return _resolve_named_profile_home(name)


def _profile_list_entry_rank(entry: dict) -> tuple[int, int]:
    """Higher rank wins when hermes_cli returns duplicate profile names."""
    is_default = 1 if entry.get('is_default') else 0
    path = Path(str(entry.get('path') or '')).expanduser()
    try:
        is_root_path = path.resolve() == _DEFAULT_HERMES_HOME.resolve()
    except OSError:
        is_root_path = False
    return (is_default, int(is_root_path))


def _dedupe_profile_list_entries(entries: list[dict]) -> list[dict]:
    """Return one row per profile name (prefer root/default metadata)."""
    best_by_name: dict[str, dict] = {}
    order: list[str] = []
    for entry in entries:
        name = str(entry.get('name') or '').strip()
        if not name:
            continue
        if name not in best_by_name:
            best_by_name[name] = entry
            order.append(name)
            continue
        if _profile_list_entry_rank(entry) > _profile_list_entry_rank(best_by_name[name]):
            best_by_name[name] = entry
    return [best_by_name[name] for name in order]


def list_profiles_api() -> list:
    """List all profiles with metadata, serialized for JSON response."""
    global _profiles_list_cache, _profiles_list_cache_at
    now = time.monotonic()
    with _profiles_list_cache_lock:
        if (
            _profiles_list_cache is not None
            and (now - _profiles_list_cache_at) < _PROFILES_LIST_CACHE_TTL_SEC
        ):
            cached = [dict(item) for item in _profiles_list_cache]
            active = get_active_profile_name()
            for item in cached:
                item['is_active'] = item.get('name') == active
            return cached

    try:
        from hermes_cli.profiles import list_profiles
        infos = list_profiles()
    except ImportError:
        # hermes_cli not available -- return just the default
        return [_default_profile_dict()]

    active = get_active_profile_name()
    result = []
    for p in infos:
        home = _home_for_profile_name(p.name, p.path, is_default=p.is_default)
        entry = {
            'name': p.name,
            'path': str(p.path),
            'is_default': p.is_default,
            'is_active': p.name == active,
            'gateway_running': p.gateway_running,
            'model': p.model,
            'provider': p.provider,
            'has_env': p.has_env,
            'skill_count': p.skill_count,
        }
        entry.update(_profile_workspace_fields(home, p.name))
        result.append(entry)
    result = _dedupe_profile_list_entries(result)
    with _profiles_list_cache_lock:
        _profiles_list_cache = [dict(item) for item in result]
        _profiles_list_cache_at = time.monotonic()
    return result


def _default_profile_dict() -> dict:
    """Fallback profile dict when hermes_cli is not importable."""
    home = _DEFAULT_HERMES_HOME
    entry = {
        'name': 'default',
        'path': str(home),
        'is_default': True,
        'is_active': True,
        'gateway_running': False,
        'model': None,
        'provider': None,
        'has_env': (home / '.env').exists(),
        'skill_count': 0,
    }
    entry.update(_profile_workspace_fields(home, 'default'))
    return entry


def _validate_profile_name(name: str):
    """Validate profile name format (matches hermes_cli.profiles upstream)."""
    if name == 'default':
        raise ValueError("Cannot create a profile named 'default' -- it is the built-in profile.")
    # Use fullmatch (not match) so a trailing newline can't sneak past the $ anchor
    if not _PROFILE_ID_RE.fullmatch(name):
        raise ValueError(
            f"Invalid profile name {name!r}. "
            "Must match [a-z0-9][a-z0-9_-]{0,63}"
        )


def _profiles_root() -> Path:
    """Return the canonical root that contains named profiles."""
    return (_DEFAULT_HERMES_HOME / 'profiles').resolve()


def _resolve_named_profile_home(name: str) -> Path:
    """Resolve a named profile to a directory under the profiles root.

    Validates *name* as a logical profile identifier first, then resolves the
    final filesystem path and enforces containment under ~/.hermes/profiles.
    """
    _validate_profile_name(name)
    profiles_root = _profiles_root()
    candidate = (profiles_root / name).resolve()
    candidate.relative_to(profiles_root)
    return candidate


def _create_profile_fallback(name: str, clone_from: str = None,
                              clone_config: bool = False) -> Path:
    """Create a profile directory without hermes_cli (Docker/standalone fallback)."""
    profile_dir = _DEFAULT_HERMES_HOME / 'profiles' / name
    if profile_dir.exists():
        raise FileExistsError(f"Profile '{name}' already exists.")

    # Bootstrap directory structure (exist_ok=False so a concurrent create raises)
    profile_dir.mkdir(parents=True, exist_ok=False)
    for subdir in _PROFILE_DIRS:
        (profile_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Clone config files (and skills) from the default/root profile when requested.
    if clone_config and clone_from:
        if _is_root_profile(clone_from):
            source_dir = _DEFAULT_HERMES_HOME
        else:
            source_dir = _DEFAULT_HERMES_HOME / 'profiles' / clone_from
        if source_dir.is_dir():
            for filename in _CLONE_CONFIG_FILES:
                src = source_dir / filename
                if src.exists():
                    shutil.copy2(src, profile_dir / filename)
            source_skills = source_dir / 'skills'
            if source_skills.is_dir():
                shutil.copytree(source_skills, profile_dir / 'skills', dirs_exist_ok=True)
                if _is_root_profile(clone_from):
                    from app.domain.skill_ownership import collect_skill_names, mark_skills_inherited

                    mark_skills_inherited(
                        profile_dir / 'skills',
                        collect_skill_names(profile_dir / 'skills'),
                    )
            for relpath in _CLONE_SUBDIR_FILES:
                src = source_dir / relpath
                if src.exists():
                    dst = profile_dir / relpath
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

    return profile_dir


def _resolve_profile_clone_defaults(
    clone_from: str | None,
    clone_config: bool | None,
) -> tuple[str, bool]:
    """New profiles copy the default profile unless explicitly overridden."""
    if clone_from is None:
        clone_from = _DEFAULT_CLONE_SOURCE
    if clone_config is None:
        clone_config = True
    return clone_from, clone_config


def _write_endpoint_to_config(profile_dir: Path, base_url: str = None, api_key: str = None) -> None:
    """Write custom endpoint fields into config.yaml for a profile."""
    if not base_url and not api_key:
        return
    config_path = profile_dir / 'config.yaml'
    try:
        import yaml as _yaml
    except ImportError:
        return
    cfg = {}
    if config_path.exists():
        try:
            loaded = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            logger.debug("Failed to load config from %s", config_path)
    model_section = cfg.get('model', {})
    if not isinstance(model_section, dict):
        model_section = {}
    if base_url:
        model_section['base_url'] = base_url
    if api_key:
        model_section['api_key'] = api_key
    cfg['model'] = model_section
    config_path.write_text(_yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding='utf-8')


def _clean_profile_config_value(value: Optional[str], field: str) -> Optional[str]:
    """Return a safe single-line config value or raise ValueError."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if any(ch in cleaned for ch in ("\x00", "\r", "\n")):
        raise ValueError(f"{field} must be a single-line value")
    if len(cleaned) > 512:
        raise ValueError(f"{field} is too long")
    return cleaned


def _split_webui_provider_model_value(default_model: Optional[str], model_provider: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Normalize WebUI-internal @provider:model picker values for config.yaml."""
    model = _clean_profile_config_value(default_model, "default_model")
    provider = _clean_profile_config_value(model_provider, "model_provider")
    if model and model.startswith("@") and ":" in model:
        provider_part, model_part = model[1:].rsplit(":", 1)
        provider = provider or _clean_profile_config_value(provider_part, "model_provider")
        model = _clean_profile_config_value(model_part, "default_model")
    return model, provider


def _strip_webui_provider_prefix(model_id: object) -> str:
    value = str(model_id or "").strip()
    if value.startswith("@") and ":" in value:
        return value.rsplit(":", 1)[1]
    return value


def _profile_model_selection_exists(
    available_models: object,
    default_model: Optional[str],
    model_provider: Optional[str],
) -> bool:
    """Return True when a profile default model/provider exists in /api/models."""
    if not default_model and not model_provider:
        return True
    if not isinstance(available_models, dict):
        return False

    provider_seen = False
    model_seen = False
    for group in available_models.get("groups", []) or []:
        if not isinstance(group, dict):
            continue
        provider_id = str(group.get("provider_id") or "").strip()
        if model_provider and provider_id != model_provider:
            continue
        if model_provider and provider_id == model_provider:
            provider_seen = True
        for model in group.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            if default_model and (
                model_id == default_model
                or _strip_webui_provider_prefix(model_id) == default_model
            ):
                model_seen = True
                if model_provider:
                    return True
        if not default_model and provider_seen:
            return True

    if model_provider and not provider_seen:
        return False
    return bool(model_seen)


def _get_available_models_for_profile_validation() -> dict:
    from app.domain.config import get_available_models

    return get_available_models()


def _validate_profile_model_selection(
    default_model: Optional[str],
    model_provider: Optional[str],
    available_models: Optional[dict] = None,
) -> None:
    """Reject profile model defaults that do not exist in the server catalog."""
    if not default_model and not model_provider:
        return
    catalog = (
        available_models
        if available_models is not None
        else _get_available_models_for_profile_validation()
    )
    if _profile_model_selection_exists(catalog, default_model, model_provider):
        return
    if default_model and model_provider:
        raise ValueError(
            f"Selected model '{default_model}' is not available for provider '{model_provider}'"
        )
    if default_model:
        raise ValueError(f"Selected model '{default_model}' is not available")
    raise ValueError(f"Selected model provider '{model_provider}' is not available")


def _write_workspace_to_config(profile_dir: Path, workspace_path: Path) -> None:
    """Write the profile's canonical workspace path into config.yaml."""
    config_path = profile_dir / 'config.yaml'
    try:
        import yaml as _yaml
    except ImportError:
        return
    cfg = {}
    if config_path.exists():
        try:
            loaded = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            logger.debug("Failed to load config from %s", config_path)
    from app.domain.workspace import profile_workspace_rel

    rel_path = profile_workspace_rel()
    cfg['workspace'] = rel_path
    terminal_section = cfg.get('terminal', {})
    if not isinstance(terminal_section, dict):
        terminal_section = {}
    terminal_section['cwd'] = rel_path
    cfg['terminal'] = terminal_section
    config_path.write_text(
        _yaml.dump(cfg, default_flow_style=False, allow_unicode=True),
        encoding='utf-8',
    )


def _write_model_defaults_to_config(
    profile_dir: Path,
    *,
    default_model: Optional[str] = None,
    model_provider: Optional[str] = None,
    update_default: bool = True,
    update_provider: bool = True,
) -> None:
    """Write model default/provider fields into config.yaml for a profile."""
    default_model, model_provider = _split_webui_provider_model_value(default_model, model_provider)
    if update_default and not default_model and update_provider and not model_provider:
        return
    if not update_default and not update_provider:
        return
    config_path = profile_dir / 'config.yaml'
    try:
        import yaml as _yaml
    except ImportError:
        return
    cfg = {}
    if config_path.exists():
        try:
            loaded = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            logger.debug("Failed to load config from %s", config_path)
    model_section = cfg.get('model', {})
    if not isinstance(model_section, dict):
        model_section = {}
    if default_model and update_default:
        model_section['default'] = default_model
    if model_provider and update_provider:
        model_section['provider'] = model_provider
    cfg['model'] = model_section
    config_path.write_text(_yaml.dump(cfg, default_flow_style=False, allow_unicode=True), encoding='utf-8')


def create_profile_api(name: str, clone_from: str = None,
                       clone_config: bool | None = None,
                       base_url: str = None,
                       api_key: str = None,
                       default_model: str = None,
                       model_provider: str = None) -> dict:
    """Create a new profile. Returns the new profile info dict."""
    _validate_profile_name(name)
    clone_from, clone_config = _resolve_profile_clone_defaults(clone_from, clone_config)
    # Defense-in-depth: validate clone_from here too, even though routes.py
    # also validates it. Any caller that bypasses the HTTP layer gets protection.
    if not _is_root_profile(clone_from):
        _validate_profile_name(clone_from)
    default_model, model_provider = _split_webui_provider_model_value(default_model, model_provider)
    _validate_profile_model_selection(default_model, model_provider)

    try:
        from hermes_cli.profiles import create_profile
        create_profile(
            name,
            clone_from=clone_from,
            clone_config=clone_config,
            clone_all=False,
            no_alias=True,
        )
    except ImportError:
        _create_profile_fallback(name, clone_from, clone_config)

    # Resolve the profile directory from the profile list when possible.
    # hermes_cli and the webui runtime do not always agree on the exact root,
    # so we prefer the path returned by list_profiles_api() and fall back to the
    # standard profile location only if the profile cannot be found there yet.
    profile_path = _DEFAULT_HERMES_HOME / 'profiles' / name
    for p in list_profiles_api():
        if p['name'] == name:
            try:
                profile_path = Path(p.get('path') or profile_path)
            except Exception:
                logger.debug("Failed to parse profile path")
            break

    profile_path.mkdir(parents=True, exist_ok=True)

    # Seed bundled skills only when the caller opts out of cloning (#2305).
    # Default WebUI creation clones config/skills from the default profile.
    if not clone_config:
        try:
            from hermes_cli.profiles import seed_profile_skills
            seed_profile_skills(profile_path, quiet=True)
        except ImportError:
            logger.debug(
                'seed_profile_skills unavailable — bundled skills not seeded '
                'for profile %s (hermes_cli not in path)',
                name,
            )
        except Exception:
            logger.warning(
                'Bundled skills could not be seeded for profile %s; '
                'profile created successfully anyway',
                name,
                exc_info=True,
            )

    _write_endpoint_to_config(profile_path, base_url=base_url, api_key=api_key)
    _write_model_defaults_to_config(
        profile_path,
        default_model=default_model,
        model_provider=model_provider,
    )

    from app.domain.workspace import ensure_profile_workspace, profile_workspace_dir

    profile_workspace = profile_workspace_dir(profile_path)
    ensure_profile_workspace(profile_path, name=name)
    _write_workspace_to_config(profile_path, profile_workspace)

    # Invalidate cached root-profile-name lookup; create_profile may have added
    # a new profile that flips is_default semantics on the agent side (#1612).
    _invalidate_root_profile_cache()

    # Find and return the newly created profile info.
    # When hermes_cli is not importable, list_profiles_api() also falls back
    # to the stub default-only list and won't find the new profile by name.
    # In that case, return a complete profile dict directly.
    for p in list_profiles_api():
        if p['name'] == name:
            return p
    return {
        'name': name,
        'path': str(profile_path),
        'is_default': False,
        'is_active': _active_profile == name,
        'gateway_running': False,
        'model': None,
        'provider': None,
        'has_env': (profile_path / '.env').exists(),
        'skill_count': 0,
    }


def _load_config_yaml(path: Path) -> dict:
    """Load a config.yaml file as a dict (empty dict when missing/invalid)."""
    if not path.is_file():
        return {}
    try:
        import yaml as _yaml
        loaded = _yaml.safe_load(path.read_text(encoding='utf-8'))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        logger.warning("Failed to load config from %s", path, exc_info=True)
        return {}


def _save_config_yaml(path: Path, cfg: dict) -> None:
    import yaml as _yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _yaml.dump(cfg, default_flow_style=False, allow_unicode=True),
        encoding='utf-8',
    )


def _deep_merge_missing_dict(
    target: dict,
    source: dict,
    *,
    skip_top_level: frozenset[str] = frozenset(),
    path_prefix: str = '',
) -> tuple[dict, list[str]]:
    """Deep-merge *source* into *target*, adding only missing keys."""
    result = copy.deepcopy(target)
    added: list[str] = []
    for key, src_val in source.items():
        if key in skip_top_level:
            continue
        full_key = f'{path_prefix}.{key}' if path_prefix else str(key)
        if key not in result:
            result[key] = copy.deepcopy(src_val)
            added.append(full_key)
        elif isinstance(result[key], dict) and isinstance(src_val, dict):
            merged, sub_added = _deep_merge_missing_dict(
                result[key],
                src_val,
                skip_top_level=skip_top_level,
                path_prefix=full_key,
            )
            result[key] = merged
            added.extend(sub_added)
    return result, added


def _remove_skill_path(path: Path) -> None:
    """Remove a skill directory or symlink under a profile skills folder."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _skill_tree_matches(source: Path, target: Path) -> bool:
    """Return True when *target* already matches the default *source* skill payload."""
    import filecmp

    if source.is_symlink():
        if not target.is_symlink():
            return False
        try:
            return source.resolve() == target.resolve()
        except OSError:
            return False
    if not source.is_dir():
        return False
    if not target.is_dir() or target.is_symlink():
        return False
    comparison = filecmp.dircmp(source, target)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    if comparison.diff_files:
        return False
    return all(
        _skill_tree_matches(source / sub, target / sub)
        for sub in comparison.common_dirs
    )


def _sync_skills_from_source(source_home: Path, target_home: Path) -> tuple[list[str], list[str]]:
    """Copy or overwrite skill directories from *source_home* into *target_home*."""
    import os

    source_skills = source_home / 'skills'
    target_skills = target_home / 'skills'
    target_skills.mkdir(parents=True, exist_ok=True)
    added: list[str] = []
    skipped: list[str] = []
    if not source_skills.is_dir():
        return added, skipped
    from app.domain.skill_ownership import collect_skill_names, mark_skills_inherited

    for item in sorted(source_skills.iterdir()):
        if item.name.startswith('.'):
            continue
        dst = target_skills / item.name
        if dst.exists() or dst.is_symlink():
            if _skill_tree_matches(item, dst):
                skipped.append(item.name)
                continue
            _remove_skill_path(dst)

        if item.is_symlink():
            try:
                resolved = item.resolve()
            except OSError:
                skipped.append(item.name)
                continue
            if not resolved.is_dir():
                skipped.append(item.name)
                continue
            rel_target = os.path.relpath(resolved, dst.parent)
            dst.symlink_to(rel_target)
            added.append(item.name)
            mark_skills_inherited(target_skills, collect_skill_names(resolved) or {item.name})
            continue

        if not item.is_dir():
            continue

        shutil.copytree(item, dst)
        added.append(item.name)
        mark_skills_inherited(target_skills, collect_skill_names(dst))
    return added, skipped


def _sync_soul_from_source(source_home: Path, target_home: Path) -> tuple[list[str], list[str]]:
    """Copy the default profile's SOUL.md verbatim into the target profile.

    The agent soul must match the default profile exactly after a sync, so the
    target SOUL.md is overwritten (or created) with a byte-for-byte copy of the
    default SOUL.md rather than additively merging missing paragraphs.

    Edge cases:
    - Default has no SOUL.md (missing) or an empty/whitespace-only SOUL.md:
      the target is left untouched (nothing to copy from).
    - Target already matches the default exactly: reported as skipped, no write.
    """
    dst = target_home / 'SOUL.md'
    src = source_home / 'SOUL.md'
    if not src.is_file():
        return [], []

    source_text = src.read_text(encoding='utf-8', errors='replace')
    if not source_text.strip():
        return [], []

    target_text = dst.read_text(encoding='utf-8', errors='replace') if dst.is_file() else None
    if target_text == source_text:
        return [], ['SOUL.md']

    dst.write_text(source_text, encoding='utf-8')
    return ['SOUL.md'], []


def _sync_auth_from_source(source_home: Path, target_home: Path) -> tuple[list[str], list[str]]:
    """Copy the default profile's auth.json verbatim into the target profile.

  Provider credentials (OpenRouter, Nous Portal, OAuth pools, etc.) live in
  auth.json rather than config.yaml, so model sync must include this file.
    """
    dst = target_home / 'auth.json'
    src = source_home / 'auth.json'
    if not src.is_file():
        return [], []

    source_text = src.read_text(encoding='utf-8', errors='replace')
    if not source_text.strip():
        return [], []

    target_text = dst.read_text(encoding='utf-8', errors='replace') if dst.is_file() else None
    if target_text == source_text:
        return [], ['auth.json']

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(source_text, encoding='utf-8')
    try:
        os.chmod(dst, 0o600)
    except OSError:
        logger.debug('Failed to chmod auth.json at %s', dst, exc_info=True)
    return ['auth.json'], []


def _sync_mcp_servers_from_source(source_cfg: dict, target_cfg: dict) -> tuple[list[str], list[str]]:
    """Copy or overwrite MCP servers from *source_cfg* into *target_cfg*."""
    target_servers = target_cfg.get('mcp_servers', {})
    if not isinstance(target_servers, dict):
        target_servers = {}
    source_servers = source_cfg.get('mcp_servers', {})
    if not isinstance(source_servers, dict):
        source_servers = {}
    added: list[str] = []
    skipped: list[str] = []
    for name, scfg in source_servers.items():
        key = str(name or '').strip()
        if not key:
            continue
        if not isinstance(scfg, dict):
            continue
        new_cfg = copy.deepcopy(scfg)
        if target_servers.get(key) == new_cfg:
            skipped.append(key)
            continue
        target_servers[key] = new_cfg
        added.append(key)
    target_cfg['mcp_servers'] = target_servers
    return added, skipped


def _default_profile_home() -> Path:
    return _DEFAULT_HERMES_HOME.expanduser().resolve()


def _normalized_model_config(cfg: dict) -> object | None:
    """Return a comparable model config payload from config.yaml."""
    model_cfg = cfg.get('model')
    if model_cfg is None:
        return None
    if isinstance(model_cfg, str):
        cleaned = model_cfg.strip()
        return cleaned or None
    if isinstance(model_cfg, dict):
        return copy.deepcopy(model_cfg)
    return None


def _sync_model_stack_from_source(
    source_cfg: dict,
    target_cfg: dict,
) -> tuple[list[str], list[str]]:
    """Replace model-related config sections with the default profile's values."""
    added: list[str] = []
    skipped: list[str] = []
    for key in sorted(_MODEL_SYNC_TOP_LEVEL_KEYS):
        source_val = source_cfg.get(key)
        if source_val is None:
            if key in target_cfg:
                del target_cfg[key]
                added.append(key)
            continue
        new_val = copy.deepcopy(source_val)
        if target_cfg.get(key) == new_val:
            skipped.append(key)
            continue
        target_cfg[key] = new_val
        added.append(key)
    return added, skipped


def _models_cache_path_for_profile(profile_name: str) -> Path:
    """Return the on-disk /api/models cache path for *profile_name*."""
    import re

    from app.domain.config import STATE_DIR

    safe = re.sub(r'[^\w.-]', '_', str(profile_name or '').strip().lower())[:128]
    return STATE_DIR / f'models_cache.{safe or "default"}.json'


def _invalidate_models_disk_cache_for_profile(profile_name: str) -> None:
    """Drop persisted model-catalog cache for *profile_name* after a sync."""
    cache_path = _models_cache_path_for_profile(profile_name)
    try:
        cache_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning('Failed to delete models cache %s: %s', cache_path, exc)

    try:
        from app.domain.config import invalidate_models_cache
        if get_active_profile_name() == profile_name:
            invalidate_models_cache(delete_disk=False)
    except Exception:
        logger.debug('Failed to invalidate in-memory models cache for %s', profile_name, exc_info=True)


def _sync_model_config_from_source(
    source_cfg: dict,
    target_cfg: dict,
) -> tuple[list[str], list[str]]:
    """Replace model-related config with the default profile (compat wrapper)."""
    return _sync_model_stack_from_source(source_cfg, target_cfg)


def sync_profile_from_default_api(name: str) -> dict:
    """Sync a profile from the default profile.

    Overwrites skills and MCP servers that share a name with the default
    profile, copies the default profile's full model stack (model,
    custom_providers, providers, and related keys) and auth.json verbatim,
    adds missing config keys (additive for other config), and copies the
    default profile's SOUL.md verbatim.
    """
    if _is_root_profile(name):
        raise ValueError("Cannot sync the default profile from itself.")
    _validate_profile_name(name)
    target_home = _resolve_named_profile_home(name)
    if not target_home.is_dir():
        raise ValueError(f"Profile '{name}' does not exist.")
    source_home = _default_profile_home()

    added = {'config': [], 'mcp_servers': [], 'skills': [], 'files': []}
    skipped = {'config': [], 'mcp_servers': [], 'skills': [], 'files': []}

    skill_added, skill_skipped = _sync_skills_from_source(source_home, target_home)
    added['skills'] = skill_added
    skipped['skills'] = skill_skipped

    soul_added, soul_skipped = _sync_soul_from_source(source_home, target_home)
    added['files'].extend(soul_added)
    skipped['files'].extend(soul_skipped)

    auth_added, auth_skipped = _sync_auth_from_source(source_home, target_home)
    added['files'].extend(auth_added)
    skipped['files'].extend(auth_skipped)

    source_cfg = _load_config_yaml(source_home / 'config.yaml')
    target_cfg = _load_config_yaml(target_home / 'config.yaml')
    mcp_added, mcp_skipped = _sync_mcp_servers_from_source(source_cfg, target_cfg)
    added['mcp_servers'] = mcp_added
    skipped['mcp_servers'] = mcp_skipped

    merged_cfg, cfg_added = _deep_merge_missing_dict(
        target_cfg,
        source_cfg,
        skip_top_level=frozenset({'mcp_servers'} | _MODEL_SYNC_TOP_LEVEL_KEYS),
    )
    merged_cfg['mcp_servers'] = target_cfg.get('mcp_servers', {})
    model_added, model_skipped = _sync_model_stack_from_source(source_cfg, merged_cfg)
    added['config'] = cfg_added + model_added
    skipped['config'] = model_skipped

    if cfg_added or mcp_added or model_added:
        _save_config_yaml(target_home / 'config.yaml', merged_cfg)

    _invalidate_models_disk_cache_for_profile(name)
    _invalidate_root_profile_cache()
    return {
        'ok': True,
        'name': name,
        'added': added,
        'skipped': skipped,
    }


def update_profile_model_api(
    name: str,
    *,
    default_model: Optional[str] = None,
    model_provider: Optional[str] = None,
    update_default: bool = True,
    update_provider: bool = True,
) -> dict:
    """Update a profile's default model/provider in its config.yaml."""
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValueError("Profile name is required")
    default_model, model_provider = _split_webui_provider_model_value(
        default_model,
        model_provider,
    )
    if update_default and not default_model and update_provider and not model_provider:
        raise ValueError("default_model or model_provider is required")

    profile_home: Path | None = None
    for row in list_profiles_api():
        if row.get("name") == cleaned:
            raw_path = row.get("path")
            if raw_path:
                profile_home = Path(str(raw_path)).expanduser().resolve()
            break
    if profile_home is None:
        if cleaned == "default" or _is_root_profile(cleaned):
            profile_home = _default_profile_home()
        else:
            _validate_profile_name(cleaned)
            candidate = _resolve_named_profile_home(cleaned)
            if not candidate.is_dir():
                raise ValueError(f"Profile '{cleaned}' does not exist.")
            profile_home = candidate

    existing_model: dict = {}
    config_path = profile_home / "config.yaml"
    if config_path.exists():
        try:
            import yaml as _yaml

            loaded = _yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("model"), dict):
                existing_model = loaded["model"]
        except Exception:
            logger.debug("Failed to load profile config for partial model update")

    if update_default or update_provider:
        validate_model = default_model if update_default else existing_model.get("default")
        validate_provider = model_provider if update_provider else existing_model.get("provider")
        _validate_profile_model_selection(
            str(validate_model).strip() if validate_model else None,
            str(validate_provider).strip() if validate_provider else None,
        )

    _write_model_defaults_to_config(
        profile_home,
        default_model=default_model,
        model_provider=model_provider,
        update_default=update_default,
        update_provider=update_provider,
    )
    _invalidate_root_profile_cache()

    for row in list_profiles_api():
        if row.get("name") == cleaned:
            return {"ok": True, "profile": row}
    return {"ok": True, "profile": {"name": cleaned, "path": str(profile_home)}}


def sync_all_profiles_from_default_api() -> dict:
    """Sync every non-default profile from the default profile."""
    synced: list[dict] = []
    try:
        from hermes_cli.profiles import list_profiles
        profile_rows = list_profiles()
    except ImportError:
        profile_rows = []
        profiles_root = _profiles_root()
        if profiles_root.is_dir():
            for entry in sorted(profiles_root.iterdir()):
                if entry.is_dir() and _PROFILE_ID_RE.match(entry.name):
                    profile_rows.append(type('_Row', (), {'name': entry.name})())

    for row in profile_rows:
        pname = getattr(row, 'name', None) or (row.get('name') if isinstance(row, dict) else None)
        if not pname or _is_root_profile(pname):
            continue
        try:
            synced.append(sync_profile_from_default_api(pname))
        except ValueError as exc:
            synced.append({'ok': False, 'name': pname, 'error': str(exc)})

    return {'ok': True, 'profiles': synced}


def delete_profile_api(name: str) -> dict:
    """Delete a profile. Switches to default first if it's the active one."""
    if _is_root_profile(name):
        raise ValueError("Cannot delete the default profile.")
    _validate_profile_name(name)

    # If deleting the active profile, switch to default first
    if _active_profile == name:
        try:
            switch_profile('default')
        except RuntimeError:
            raise RuntimeError(
                f"Cannot delete active profile '{name}' while an agent is running. "
                "Cancel or wait for it to finish."
            )

    profile_dir = _resolve_named_profile_home(name)
    try:
        from app.domain.workspace import delete_profile_workspace
        delete_profile_workspace(profile_dir)
    except Exception:
        logger.warning(
            "Failed to delete workspace for profile %s",
            name,
            exc_info=True,
        )

    try:
        from hermes_cli.profiles import delete_profile
        delete_profile(name, yes=True)
    except ImportError:
        # Manual fallback: just remove the directory
        import shutil
        if profile_dir.is_dir():
            shutil.rmtree(str(profile_dir))
        else:
            raise ValueError(f"Profile '{name}' does not exist.")

    # Drop cached root-profile-name lookup — list_profiles_api() shape changed.
    _invalidate_root_profile_cache()
    return {'ok': True, 'name': name}


# ── FastAPI migration layer (lazy re-exports) ───────────────────────────────
_FASTAPI_LAYER_EXPORTS = {
    "ProfileRepository": ("app.repositories.profiles", "ProfileRepository"),
    "ProfileService": ("app.services.profiles", "ProfileService"),
    "sync_profile_from_default_api": (
        "app.services.profiles",
        "sync_profile_from_default_api",
    ),
    "sync_all_profiles_from_default_api": (
        "app.services.profiles",
        "sync_all_profiles_from_default_api",
    ),
}


def _fastapi_layer_import(module_path: str, attr: str):
    import importlib

    return getattr(importlib.import_module(module_path), attr)


def profile_repository() -> "ProfileRepository":
    """Return a ProfileRepository instance (FastAPI migration shim)."""
    return _fastapi_layer_import("app.repositories.profiles", "ProfileRepository")()


def profile_service() -> "ProfileService":
    """Return a ProfileService instance (FastAPI migration shim)."""
    return _fastapi_layer_import("app.services.profiles", "ProfileService")()


def __getattr__(name: str):
    target = _FASTAPI_LAYER_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = target
    return _fastapi_layer_import(module_path, attr)
