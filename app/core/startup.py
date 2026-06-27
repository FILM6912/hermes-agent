"""Startup and shutdown hooks extracted from server.py main()."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from app.domain.config import DEFAULT_WORKSPACE, SESSION_DIR, STATE_DIR
from app.domain.startup import fix_credential_permissions

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_CONTAINER_STARTUP_DEFER_SECONDS = 5.0


def _within_container() -> bool:
    try:
        with open("/.within_container", "r"):
            return True
    except FileNotFoundError:
        return False


def raise_fd_soft_limit(target: int = 4096) -> dict:
    """Best-effort raise of RLIMIT_NOFILE (ported from server.py)."""
    try:
        import resource
    except ImportError:
        return {"status": "unsupported"}

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    desired = int(target)
    if hard not in (-1, getattr(resource, "RLIM_INFINITY", object())):
        desired = min(desired, int(hard))
    if soft >= desired:
        return {"status": "unchanged", "soft": soft, "hard": hard}
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (desired, hard))
    except Exception as exc:
        return {
            "status": "error",
            "soft": soft,
            "hard": hard,
            "error": str(exc),
        }
    return {
        "status": "raised",
        "soft": desired,
        "hard": hard,
        "previous_soft": soft,
    }


def startup_session_recovery(*, rebuild_index: bool = True) -> None:
    try:
        from app.domain.models import _active_state_db_path
        from app.domain.session_recovery import recover_all_sessions_on_startup

        result = recover_all_sessions_on_startup(
            SESSION_DIR,
            rebuild_index=rebuild_index,
            state_db_path=_active_state_db_path(),
        )
        if result.get("restored"):
            print(
                f"[recovery] Restored {result['restored']}/{result['scanned']} sessions from .bak (see #1558).",
                flush=True,
            )
    except Exception as exc:
        print(f"[recovery] startup recovery failed: {exc}", flush=True)


def startup_agent_import_check() -> None:
    from app.domain.config import _HERMES_FOUND, verify_hermes_imports
    from app.domain.startup import auto_install_agent_deps

    ok, missing, errors = verify_hermes_imports()
    if not ok and _HERMES_FOUND:
        print(
            f"[!!] Warning: Hermes agent found but missing modules: {missing}",
            flush=True,
        )
        for mod, err in errors.items():
            print(f"     {mod}: {err}", flush=True)
        print(
            "     Attempting to install missing dependencies from agent requirements.txt...",
            flush=True,
        )
        auto_install_agent_deps()
        ok, missing, errors = verify_hermes_imports()
        if not ok:
            print(f"[!!] Still missing after install attempt: {missing}", flush=True)
            for mod, err in errors.items():
                print(f"     {mod}: {err}", flush=True)
            print("     Agent features may not work correctly.", flush=True)
        else:
            print("[ok] Agent dependencies installed successfully.", flush=True)


def apply_agent_runtime_patches() -> None:
    """Apply Hermes Agent runtime hooks once the agent package is importable."""
    try:
        from app.domain.profiles import apply_agent_runtime_patches as _apply

        _apply()
    except Exception as exc:
        print(f"[startup] agent runtime patches skipped: {exc}", flush=True)


def _deferred_container_startup_tasks() -> None:
    time.sleep(_CONTAINER_STARTUP_DEFER_SECONDS)
    try:
        startup_session_recovery(rebuild_index=False)
    except Exception as exc:
        print(f"[startup] deferred session recovery failed: {exc}", flush=True)
    try:
        startup_agent_import_check()
    except Exception as exc:
        print(f"[startup] deferred agent import check failed: {exc}", flush=True)
    apply_agent_runtime_patches()


def run_startup(app: FastAPI) -> None:
    """Run synchronous startup work before accepting traffic."""
    from app.domain.config import HOST, print_startup_config
    from app.domain.auth import is_auth_enabled

    print_startup_config()

    fd_limit = raise_fd_soft_limit()
    if fd_limit.get("status") == "raised":
        print(
            f"[ok] Raised file descriptor soft limit "
            f"{fd_limit.get('previous_soft')} -> {fd_limit.get('soft')}",
            flush=True,
        )
    elif fd_limit.get("status") == "error":
        print(
            f"[!!] WARNING: Could not raise file descriptor limit: {fd_limit.get('error')}",
            flush=True,
        )

    fix_credential_permissions()

    try:
        from app.domain.workspace import best_effort_repair_shared_workspace_ownership

        aligned = best_effort_repair_shared_workspace_ownership()
        if aligned:
            print(
                f"[startup] aligned ownership on {aligned} shared workspace path(s)",
                flush=True,
            )
    except Exception as exc:
        print(f"[startup] shared workspace ownership repair skipped: {exc}", flush=True)

    try:
        from app.domain.users import bootstrap_default_admin

        bootstrap_default_admin()
    except Exception as exc:
        print(f"[!!] WARNING: Multi-user admin bootstrap failed: {exc}", flush=True)

    within_container = _within_container()
    if within_container:
        threading.Thread(
            target=_deferred_container_startup_tasks,
            daemon=True,
            name="container-startup",
        ).start()
    else:
        startup_session_recovery(rebuild_index=True)

    if within_container:
        print("[ok] Running within container.", flush=True)

    if HOST not in ("127.0.0.1", "::1", "localhost") and not is_auth_enabled():
        print(f"[!!] WARNING: Binding to {HOST} with NO PASSWORD SET.", flush=True)
        print(
            "     Anyone on the network can access your filesystem and agent.",
            flush=True,
        )
        print(
            "     Set a password via Settings or HERMES_WEBUI_PASSWORD env var.",
            flush=True,
        )
        print(
            "     To suppress: bind to 127.0.0.1 or set a password.",
            flush=True,
        )
        if within_container:
            print(
                "     Note: You are running within a container, must bind to "
                "0.0.0.0 (IPv4) or :: (IPv6) to publish the port.",
                flush=True,
            )
    elif not is_auth_enabled():
        print(
            "  [tip] No password set. Any process on this machine can read sessions",
            flush=True,
        )
        print(
            "        and memory via the local API. Set HERMES_WEBUI_PASSWORD to",
            flush=True,
        )
        print("        enable authentication.", flush=True)

    if not within_container:
        startup_agent_import_check()
    apply_agent_runtime_patches()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_WORKSPACE.mkdir(parents=True, exist_ok=True)

    try:
        from app.storage.schema import init_storage
        from app.storage.migrate import run_storage_migrations

        storage_info = init_storage()
        migrated = run_storage_migrations()
        from app.domain.auth import bootstrap_auth_sessions
        from app.storage.repositories.sessions import ensure_sessions_migrated
        from app.storage.repositories.chat_sessions import get_chat_sessions_repository

        bootstrap_auth_sessions()
        ensure_sessions_migrated()
        chat_repo = get_chat_sessions_repository()
        if chat_repo.enabled():
            imported_sessions = chat_repo.import_from_disk(SESSION_DIR)
            if imported_sessions:
                print(
                    f"[ok] Imported {imported_sessions} chat session(s) into Supabase webui_sessions.",
                    flush=True,
                )
        json_migrated = migrated.get("json") or {}
        imported = [k for k, v in json_migrated.items() if v == "imported"]
        if imported:
            print(
                f"[ok] WebUI storage (local={storage_info.get('local_backend')}"
                f"{', supabase=postgres' if storage_info.get('supabase_enabled') else ''}): "
                f"migrated {', '.join(imported)} into database.",
                flush=True,
            )
        else:
            supabase_note = (
                ", users/chat-sessions→supabase"
                if storage_info.get("supabase_enabled")
                else ""
            )
            print(
                f"[ok] WebUI storage ready (local={storage_info.get('local_backend')}"
                f"{supabase_note}, schema v{storage_info.get('schema_version')}).",
                flush=True,
            )
    except Exception as exc:
        print(f"[!!] WARNING: WebUI database storage init failed: {exc}", flush=True)

    try:
        from app.domain.gateway_watcher import start_watcher

        start_watcher()
    except Exception as exc:
        print(f"[!!] WARNING: Gateway watcher failed to start: {exc}", flush=True)

    app.state.within_container = within_container


def run_shutdown() -> None:
    try:
        from app.domain.gateway_watcher import stop_watcher

        stop_watcher()
    except Exception:
        logger.debug("Failed to stop gateway watcher during shutdown")
    try:
        from app.domain.session_lifecycle import drain_all_on_shutdown

        drain_all_on_shutdown()
    except Exception:
        logger.debug("Failed to drain lifecycle on shutdown", exc_info=True)
