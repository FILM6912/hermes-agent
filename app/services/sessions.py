"""Session service — thin layer over SessionRepository."""

from __future__ import annotations

import copy
import io
import json
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable

from app.domain.models import Session, all_sessions, title_from

from app.repositories.sessions import SessionRepository

if TYPE_CHECKING:
    from app.domain.users import UserAccess
else:
    UserAccess = object  # noqa: A001 — typing-only alias


def _invoke_routes_json_handler(
    handler_fn: Callable[..., Any],
    body: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Run a legacy routes.py JSON handler and capture its response payload."""

    class _CaptureHandler:
        def __init__(self) -> None:
            self.status = 200
            self.headers: dict[str, str] = {}
            self.wfile = io.BytesIO()

        def send_response(self, status: int, message: str | None = None) -> None:
            self.status = status

        def send_header(self, key: str, value: str) -> None:
            self.headers[key] = value

        def end_headers(self) -> None:
            return None

    handler = _CaptureHandler()
    handler_fn(handler, body)
    raw = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(raw) if raw else {}
    return payload, handler.status


class SessionService:
    def __init__(self, repository: SessionRepository | None = None) -> None:
        self._repo = repository or SessionRepository()

    def load(self, session_id: str) -> Session | None:
        return self._repo.load(session_id)

    def load_metadata_only(self, session_id: str) -> Session | None:
        return self._repo.load_metadata_only(session_id)

    def save(
        self,
        session: Session,
        *,
        touch_updated_at: bool = True,
        skip_index: bool = False,
    ) -> None:
        self._repo.save(
            session,
            touch_updated_at=touch_updated_at,
            skip_index=skip_index,
        )

    def list_sessions(self, diag: Any = None) -> list[dict]:
        return self._repo.list_sessions(diag=diag)

    def list_sidebar(
        self,
        *,
        all_profiles: bool = False,
        access: "UserAccess | None" = None,
    ) -> dict[str, Any]:
        """Build the GET /api/sessions sidebar payload (legacy parity)."""
        from app.domain.config import load_settings
        from app.domain.agent_sessions import is_cli_session_row_visible
        from app.domain.models import get_cli_sessions
        from app.domain.profiles import _profiles_match, active_profile_for_access, get_active_profile_name
        from app.domain.request_diagnostics import RequestDiagnostics
        from app.domain.routes import (  # noqa: PLC0415 — legacy helpers until extracted
            _keep_latest_messaging_session_per_source,
            _redact_text,
        )
        from app.domain.session_sidebar import (
            CLI_VISIBLE_SESSION_CAP,
            _cap_recent_cli_sessions,
            _is_cli_session_for_settings,
            _merge_cli_sidebar_metadata,
            _reconcile_stale_stream_state_for_session_rows,
        )
        from app.domain.users import legacy_user_access

        access = access or legacy_user_access()
        if access.restricts_profiles:
            all_profiles = False
        scope_profile = (
            access.profile_name or "default"
            if access.restricts_profiles
            else get_active_profile_name()
        )

        diag = RequestDiagnostics.maybe_start("GET", "/api/v1/sessions")
        try:
            if diag:
                diag.stage("all_sessions")
            webui_sessions = self._repo.list_sessions(diag=diag)
            if diag:
                diag.stage("reconcile_stale_stream_state")
            if _reconcile_stale_stream_state_for_session_rows(webui_sessions):
                if diag:
                    diag.stage("all_sessions_after_stale_stream_reconcile")
                webui_sessions = self._repo.list_sessions(diag=diag)
            if diag:
                diag.stage("load_settings")
            settings = load_settings()
            show_cli_sessions = bool(settings.get("show_cli_sessions"))
            if show_cli_sessions:
                if diag:
                    diag.stage("get_cli_sessions")
                cli = get_cli_sessions()
                if diag:
                    diag.stage("merge_cli_sessions")
                cli_by_id = {s["session_id"]: s for s in cli}
                for s in webui_sessions:
                    meta = cli_by_id.get(s.get("session_id"))
                    if not meta:
                        continue
                    from app.domain.routes import (  # noqa: PLC0415
                        _is_messaging_session_record,
                    )

                    if _is_messaging_session_record(meta):
                        s.update(_merge_cli_sidebar_metadata(s, meta))
                        if s.get("session_id") != meta.get("session_id"):
                            s["session_id"] = meta.get("session_id")
                    else:
                        for key in (
                            "source_tag",
                            "raw_source",
                            "session_source",
                            "source_label",
                        ):
                            if not s.get(key) and meta.get(key):
                                s[key] = meta[key]
                webui_sessions = [
                    s for s in webui_sessions if is_cli_session_row_visible(s)
                ]
                webui_ids = {s["session_id"] for s in webui_sessions}
                from app.domain.models import (  # noqa: PLC0415
                    _hide_from_default_sidebar as _cron_hide,
                )

                deduped_cli = [
                    s
                    for s in cli
                    if s["session_id"] not in webui_ids
                    and is_cli_session_row_visible(s)
                    and not _cron_hide(s)
                ]
            else:
                if diag:
                    diag.stage("filter_webui_sessions")
                webui_sessions = [
                    s for s in webui_sessions if not _is_cli_session_for_settings(s)
                ]
                deduped_cli = []
            if diag:
                diag.stage("sort_sessions")
            merged = webui_sessions + deduped_cli
            merged.sort(
                key=lambda s: s.get("last_message_at")
                or s.get("updated_at", 0)
                or 0,
                reverse=True,
            )
            if diag:
                diag.stage("active_profile")
            active_profile = active_profile_for_access(get_active_profile_name(), access)
            if diag:
                diag.stage("profile_filter")
            if all_profiles:
                scoped = merged
                other_profile_count = len(merged) - len(
                    [s for s in merged if _profiles_match(s.get("profile"), scope_profile)]
                )
            else:
                scoped = [
                    s
                    for s in merged
                    if _profiles_match(s.get("profile"), scope_profile)
                ]
                other_profile_count = len(merged) - len(scoped)
            if diag:
                diag.stage("messaging_dedupe")
            scoped = _keep_latest_messaging_session_per_source(
                scoped,
                show_previous_messaging_sessions=bool(
                    settings.get("show_previous_messaging_sessions")
                ),
            )
            if show_cli_sessions:
                if diag:
                    diag.stage("cli_cap")
                scoped = _cap_recent_cli_sessions(
                    scoped, cli_cap=CLI_VISIBLE_SESSION_CAP
                )
            if diag:
                diag.stage("redact_sessions")
            safe_merged = []
            for s in scoped:
                item = dict(s)
                if isinstance(item.get("title"), str):
                    item["title"] = _redact_text(item["title"])
                safe_merged.append(item)
            if diag:
                diag.stage("response_write")
            return {
                "sessions": safe_merged,
                "cli_count": len(deduped_cli),
                "all_profiles": all_profiles,
                "active_profile": active_profile,
                "other_profile_count": other_profile_count,
                "server_time": time.time(),
                "server_tz": time.strftime("%z"),
            }
        finally:
            if diag:
                diag.finish()

    def export_session(self, session_id: str) -> tuple[bytes, dict[str, str], int]:
        """Return redacted session JSON bytes, response headers, and HTTP status."""
        import json

        from app.domain.models import get_session
        from app.domain.routes import redact_session_data  # noqa: PLC0415

        sid = (session_id or "").strip()
        if not sid:
            return b"", {}, 400
        try:
            session = get_session(sid)
        except KeyError:
            return b"", {}, 404
        safe = redact_session_data(session.__dict__)
        payload = json.dumps(safe, ensure_ascii=False, indent=2)
        encoded = payload.encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Disposition": f'attachment; filename="hermes-{sid}.json"',
            "Cache-Control": "no-store",
        }
        return encoded, headers, 200

    def branch_session(
        self,
        *,
        session_id: str,
        keep_count: int | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Fork a session from an optional message boundary."""
        from app.domain.config import LOCK, SESSIONS, SESSIONS_MAX
        from app.domain.models import Session, get_cli_session_messages, get_session
        from app.domain.routes import (  # noqa: PLC0415
            _is_messaging_session_record,
            _lookup_cli_session_metadata,
            _merged_session_messages_for_display,
            _session_requires_cli_metadata_lookup,
        )
        from app.domain.session_events import publish_session_list_changed

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        try:
            source = get_session(sid)
        except KeyError as exc:
            raise KeyError("Session not found") from exc

        custom_title = str(title).strip()[:80] if title else None
        if custom_title == "":
            custom_title = None

        try:
            source.save()
        except Exception:
            pass

        cli_meta = (
            _lookup_cli_session_metadata(source.session_id)
            if _session_requires_cli_metadata_lookup(source)
            else {}
        )
        is_messaging_session = _is_messaging_session_record(source) or _is_messaging_session_record(
            cli_meta
        )
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

        if custom_title:
            branch_title = custom_title
        else:
            source_title = source.title or "Untitled"
            branch_title = f"{source_title} (fork)"

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

        if forked_messages:
            branch.save()
            publish_session_list_changed("session_branch")

        return {
            "session_id": branch.session_id,
            "title": branch_title,
            "parent_session_id": source.session_id,
        }

    def search_sessions(
        self,
        *,
        q: str = "",
        content_search: bool = True,
        depth: int = 5,
        access: "UserAccess | None" = None,
    ) -> dict[str, Any]:
        """Search sessions by title and optional message content (legacy parity)."""
        from app.domain.models import get_session
        from app.domain.routes import (  # noqa: PLC0415
            _redact_text,
            _session_search_message_text,
            _session_search_preview,
        )
        from app.domain.session_search_scope import webui_session_row_visible
        from app.domain.users import legacy_user_access

        access = access or legacy_user_access()
        query = (q or "").lower().strip()
        def _include_row(row: dict[str, Any]) -> bool:
            return webui_session_row_visible(row, access)

        if not query:
            safe_sessions = []
            for row in self._repo.list_sessions():
                if not _include_row(row):
                    continue
                item = dict(row)
                if isinstance(item.get("title"), str):
                    item["title"] = _redact_text(item["title"])
                safe_sessions.append(item)
            return {"sessions": safe_sessions}

        results: list[dict[str, Any]] = []
        for row in self._repo.list_sessions():
            if not _include_row(row):
                continue
            title_match = query in (row.get("title") or "").lower()
            if title_match:
                item = dict(row, match_type="title")
                if isinstance(item.get("title"), str):
                    item["title"] = _redact_text(item["title"])
                results.append(item)
                continue
            if content_search:
                try:
                    sess = get_session(row["session_id"])
                    msgs = sess.messages[:depth] if depth else sess.messages
                    for message in msgs:
                        text = _session_search_message_text(message)
                        if query in str(text).lower():
                            item = dict(row, match_type="content")
                            preview = _session_search_preview(text, query)
                            if preview:
                                item["match_preview"] = _redact_text(preview)
                            if isinstance(item.get("title"), str):
                                item["title"] = _redact_text(item["title"])
                            results.append(item)
                            break
                except (KeyError, Exception):
                    pass
        return {"sessions": results, "query": query, "count": len(results)}

    def recovery_audit(self) -> dict[str, Any]:
        from app.domain.models import SESSION_DIR, _active_state_db_path
        from app.domain.session_recovery import audit_session_recovery

        return audit_session_recovery(SESSION_DIR, state_db_path=_active_state_db_path())

    def recovery_repair_safe(self) -> tuple[dict[str, Any], int]:
        from app.domain.models import SESSION_DIR, _active_state_db_path
        from app.domain.session_recovery import repair_safe_session_recovery

        result = repair_safe_session_recovery(SESSION_DIR, state_db_path=_active_state_db_path())
        status = 200 if result.get("clean") else 409
        return result, status

    def worktree_status(self, session_id: str) -> dict[str, Any]:
        from app.domain.models import get_session
        from app.domain.worktrees import worktree_status_for_session

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        try:
            session = get_session(sid, metadata_only=True)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        return {"status": worktree_status_for_session(session)}

    def worktree_remove(self, session_id: str, *, force: bool = False) -> dict[str, Any]:
        from app.domain.models import get_session
        from app.domain.worktrees import remove_worktree_for_session

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id must be a non-empty string")
        if not all(c in "0123456789abcdefghijklmnopqrstuvwxyz_" for c in sid):
            raise ValueError("Invalid session_id")
        try:
            session = get_session(sid, metadata_only=True)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        return remove_worktree_for_session(session, force=force)

    _MAX_DRAFT_TEXT = 50_000
    _MAX_DRAFT_FILES = 50

    def create_session(
        self,
        *,
        workspace: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        profile: str | None = None,
        project_id: str | None = None,
        prev_session_id: str | None = None,
        worktree: bool | str | None = None,
        access: "UserAccess | None" = None,
    ) -> dict[str, Any]:
        """Create a new session (legacy POST /api/session/new parity)."""
        from app.domain.routes import _session_model_state_from_request  # noqa: PLC0415
        from app.domain.session_events import publish_session_list_changed
        from app.domain.workspace import get_last_workspace, resolve_trusted_workspace
        from app.domain.profiles import active_profile_for_access, get_active_profile_name
        from app.domain.users import legacy_user_access, session_allowed_for_access

        access = access or legacy_user_access()
        if access.restricts_profiles:
            if profile and not session_allowed_for_access(profile, access):
                raise ValueError("Profile not allowed for this account")
            profile = active_profile_for_access(
                profile or get_active_profile_name(),
                access,
            )

        resolved_workspace = None
        if workspace:
            try:
                from app.domain.workspace import (
                    disk_path_to_virtual,
                    is_virtual_workspace_path,
                    nested_workspaces_enabled,
                )

                disk_ws = resolve_trusted_workspace(workspace)
                if nested_workspaces_enabled():
                    virtual = disk_path_to_virtual(disk_ws)
                    resolved_workspace = virtual or (
                        str(workspace).strip()
                        if is_virtual_workspace_path(workspace)
                        else str(disk_ws)
                    )
                else:
                    resolved_workspace = str(disk_ws)
            except (TypeError, ValueError) as exc:
                raise ValueError(str(exc)) from exc
        worktree_info = None
        worktree_requested = worktree is True or str(worktree or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if worktree_requested:
            try:
                from app.domain.worktrees import create_worktree_for_workspace

                base_workspace = resolved_workspace or str(
                    resolve_trusted_workspace(get_last_workspace())
                )
                worktree_info = create_worktree_for_workspace(base_workspace)
                resolved_workspace = worktree_info["path"]
            except (TypeError, ValueError) as exc:
                raise ValueError(str(exc)) from exc
            except Exception as exc:
                raise RuntimeError(f"Failed to create worktree: {exc}") from exc
        resolved_model, resolved_provider = _session_model_state_from_request(
            model,
            model_provider,
        )
        if prev_session_id:
            try:
                from app.domain.config import SESSION_AGENT_CACHE, SESSION_AGENT_CACHE_LOCK
                from app.domain.session_lifecycle import commit_session_memory

                prev_agent = None
                with SESSION_AGENT_CACHE_LOCK:
                    cached = SESSION_AGENT_CACHE.get(prev_session_id)
                    if cached:
                        prev_agent = cached[0]
                commit_session_memory(prev_session_id, agent=prev_agent)
            except Exception:
                pass
        session = self._repo.create(
            workspace=resolved_workspace,
            model=resolved_model,
            model_provider=resolved_provider,
            profile=profile,
            project_id=project_id,
            worktree_info=worktree_info,
        )
        from app.domain.session_search_scope import stamp_session_owner

        if stamp_session_owner(session, access):
            session.save()
        if worktree_info:
            publish_session_list_changed("session_new")
        return {"session": session.compact() | {"messages": session.messages}}

    def rename_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.routes import (  # noqa: PLC0415
            _ensure_full_session_before_mutation,
            _get_session_agent_lock,
        )
        from app.domain.session_events import publish_session_list_changed

        body = {"session_id": session_id, "title": title}
        require(body, "session_id", "title")
        try:
            session = self._repo.get(body["session_id"])
            session = _ensure_full_session_before_mutation(body["session_id"], session)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        with _get_session_agent_lock(body["session_id"]):
            session.title = str(body["title"]).strip()[:80] or "Untitled"
            session.save()
        publish_session_list_changed("session_rename")
        return {"session": session.compact()}

    def delete_session(self, *, session_id: str) -> dict[str, Any]:
        import shutil

        from app.domain.config import SESSION_AGENT_LOCKS, SESSION_AGENT_LOCKS_LOCK, _evict_session_agent
        from app.domain.routes import (  # noqa: PLC0415
            _is_messaging_session_id,
            _lookup_cli_session_metadata,
            _worktree_retained_payload_for_session_id,
        )
        from app.domain.session_events import publish_session_list_changed

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        if not all(c in "0123456789abcdefghijklmnopqrstuvwxyz_" for c in sid):
            raise ValueError("Invalid session_id")
        cli_meta = _lookup_cli_session_metadata(sid)
        if cli_meta.get("read_only"):
            raise ValueError("Read-only imported sessions cannot be deleted from WebUI")
        is_messaging = _is_messaging_session_id(sid)
        worktree_retained = _worktree_retained_payload_for_session_id(sid)
        self._repo.pop_from_cache(sid)
        _evict_session_agent(sid)
        try:
            self._repo.delete_session_files(sid)
        except Exception as exc:
            raise ValueError("Invalid session_id") from exc
        try:
            self._repo.prune_index(sid)
        except Exception:
            pass
        try:
            from app.domain.upload import _session_attachment_dir

            shutil.rmtree(_session_attachment_dir(sid), ignore_errors=True)
        except Exception:
            pass
        with SESSION_AGENT_LOCKS_LOCK:
            SESSION_AGENT_LOCKS.pop(sid, None)
        try:
            from app.domain.terminal import close_terminal

            close_terminal(sid)
        except Exception:
            pass
        if not is_messaging:
            try:
                from app.domain.models import delete_cli_session

                delete_cli_session(sid)
            except Exception:
                pass
        publish_session_list_changed("session_delete")
        return {"ok": True, **worktree_retained}

    def pin_session(self, *, session_id: str, pinned: bool = True) -> dict[str, Any]:
        from app.domain.config import LOCK, SESSIONS, load_settings
        from app.domain.helpers import require
        from app.domain.routes import (  # noqa: PLC0415
            _ensure_full_session_before_mutation,
            _get_session_agent_lock,
            _session_field,
        )
        from app.domain.session_events import publish_session_list_changed

        body = {"session_id": session_id, "pinned": pinned}
        require(body, "session_id")
        try:
            session = self._repo.get(body["session_id"])
            session = _ensure_full_session_before_mutation(body["session_id"], session)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        pin_requested = bool(body.get("pinned", True))
        if pin_requested and not getattr(session, "pinned", False):
            persisted_pinned_ids = {
                _session_field(existing, "session_id", None)
                for existing in self._repo.list_sessions()
                if _session_field(existing, "pinned", False)
                and not _session_field(existing, "archived", False)
            }
            with LOCK:
                pinned_ids = set(persisted_pinned_ids)
                pinned_ids.update(
                    sid
                    for sid, existing in SESSIONS.items()
                    if getattr(existing, "pinned", False)
                    and not getattr(existing, "archived", False)
                )
                pinned_ids.discard(body["session_id"])
                pinned_sessions_limit = int(
                    load_settings().get("pinned_sessions_limit", 3) or 3
                )
                if len(pinned_ids) >= pinned_sessions_limit:
                    raise ValueError(
                        f"Up to {pinned_sessions_limit} sessions can be pinned. "
                        "Unpin one before pinning another."
                    )
                session.pinned = True
            with _get_session_agent_lock(body["session_id"]):
                session.save()
        else:
            with _get_session_agent_lock(body["session_id"]):
                session.pinned = pin_requested
                session.save()
        publish_session_list_changed("session_pin")
        return {"ok": True, "session": session.compact()}

    def get_composer_draft(self, *, session_id: str) -> dict[str, Any]:
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        try:
            session = self._repo.get(sid)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        draft = getattr(session, "composer_draft", {}) or {}
        return {"draft": draft}

    def save_composer_draft(
        self,
        *,
        session_id: str,
        text: str | None = None,
        files: list | None = None,
    ) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.routes import _get_session_agent_lock  # noqa: PLC0415

        body = {"session_id": session_id, "text": text, "files": files}
        require(body, "session_id")
        sid = body["session_id"]
        draft_text = body.get("text")
        draft_files = body.get("files")
        if draft_text is not None and not isinstance(draft_text, str):
            draft_text = ""
        if isinstance(draft_text, str) and len(draft_text) > self._MAX_DRAFT_TEXT:
            draft_text = draft_text[: self._MAX_DRAFT_TEXT]
        if draft_files is not None and not isinstance(draft_files, list):
            draft_files = []
        if isinstance(draft_files, list) and len(draft_files) > self._MAX_DRAFT_FILES:
            draft_files = draft_files[: self._MAX_DRAFT_FILES]
        try:
            session = self._repo.get(sid)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        with _get_session_agent_lock(sid):
            draft = getattr(session, "composer_draft", {}) or {}
            if draft_text is not None:
                draft["text"] = draft_text
            if draft_files is not None:
                draft["files"] = draft_files
            session.composer_draft = draft
            session.save(touch_updated_at=False, skip_index=True)
        return {"ok": True, "draft": session.composer_draft}

    def update_session(
        self,
        *,
        session_id: str,
        workspace: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.domain.config import _evict_session_agent
        from app.domain.helpers import require
        from app.domain.routes import (  # noqa: PLC0415
            _get_session_agent_lock,
            _resolve_context_length_for_session_model,
            _session_model_state_from_request,
        )
        from app.domain.workspace import resolve_trusted_workspace, set_last_workspace

        payload = dict(body or {})
        payload.setdefault("session_id", session_id)
        if workspace is not None and "workspace" not in payload:
            payload["workspace"] = workspace
        if model is not None and "model" not in payload:
            payload["model"] = model
        if model_provider is not None and "model_provider" not in payload:
            payload["model_provider"] = model_provider
        require(payload, "session_id")
        try:
            session = self._repo.get(payload["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        old_ws = getattr(session, "workspace", "")
        old_model = getattr(session, "model", None)
        old_provider = getattr(session, "model_provider", None)
        try:
            from app.domain.workspace import (
                disk_path_to_virtual,
                is_virtual_workspace_path,
                nested_workspaces_enabled,
            )

            raw_ws = payload.get("workspace", session.workspace)
            disk_ws = resolve_trusted_workspace(raw_ws)
            if nested_workspaces_enabled():
                virtual = disk_path_to_virtual(disk_ws)
                new_ws = virtual or (
                    str(raw_ws).strip()
                    if is_virtual_workspace_path(raw_ws)
                    else str(disk_ws)
                )
            else:
                new_ws = str(disk_ws)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        with _get_session_agent_lock(payload["session_id"]):
            session.workspace = new_ws
            if "model" in payload or "model_provider" in payload:
                resolved_model, provider = _session_model_state_from_request(
                    payload.get("model", session.model),
                    payload.get("model_provider")
                    if "model_provider" in payload
                    else None,
                    getattr(session, "model_provider", None),
                )
                if resolved_model is not None:
                    session.model = resolved_model
                session.model_provider = provider
                if (
                    str(old_model or "") != str(getattr(session, "model", "") or "")
                    or str(old_provider or "") != str(getattr(session, "model_provider", "") or "")
                ):
                    session.context_length = _resolve_context_length_for_session_model(
                        getattr(session, "model", None),
                        getattr(session, "model_provider", None),
                    )
                    session.threshold_tokens = 0
                    session.last_prompt_tokens = 0
                    _evict_session_agent(payload["session_id"])
            session.save()
        if str(old_ws or "") != str(new_ws or ""):
            try:
                from app.domain.terminal import close_terminal

                close_terminal(payload["session_id"])
            except Exception:
                pass
        set_last_workspace(new_ws)
        return {"session": session.compact() | {"messages": session.messages}}

    def archive_session(self, *, session_id: str, archived: bool = True) -> dict[str, Any]:
        from app.domain.config import LOCK, SESSIONS
        from app.domain.helpers import require
        from app.domain.models import (
            Session,
            get_cli_session_messages,
            import_cli_session,
        )
        from app.domain.routes import (  # noqa: PLC0415
            _get_session_agent_lock,
            _is_messaging_session_record,
            _lookup_cli_session_metadata,
            _worktree_retained_payload,
        )
        from app.domain.session_events import publish_session_list_changed
        from app.domain.workspace import get_last_workspace

        body = {"session_id": session_id, "archived": archived}
        require(body, "session_id")
        sid = body["session_id"]
        try:
            session = self._repo.get(sid)
            if getattr(session, "_loaded_metadata_only", False):
                session = Session.load(sid)
                if session is None:
                    raise KeyError(sid)
                with LOCK:
                    SESSIONS[sid] = session
        except KeyError:
            cli_meta = _lookup_cli_session_metadata(sid)
            if not cli_meta:
                raise KeyError("Session not found") from None
            if cli_meta.get("read_only"):
                raise ValueError(
                    "Read-only imported sessions cannot be archived from WebUI"
                )
            if _is_messaging_session_record(cli_meta):
                session = Session(
                    session_id=sid,
                    title=cli_meta.get("title")
                    or title_from(get_cli_session_messages(sid), "CLI Session"),
                    workspace=get_last_workspace(),
                    messages=[],
                    model=cli_meta.get("model") or "unknown",
                    created_at=cli_meta.get("created_at"),
                    updated_at=cli_meta.get("updated_at"),
                )
                session.is_cli_session = True
                session.source_tag = cli_meta.get("source_tag")
                session.raw_source = cli_meta.get("raw_source") or cli_meta.get("source_tag")
                session.session_source = cli_meta.get("session_source")
                session.source_label = cli_meta.get("source_label")
                session.user_id = cli_meta.get("user_id")
                session.chat_id = cli_meta.get("chat_id")
                session.chat_type = cli_meta.get("chat_type")
                session.thread_id = cli_meta.get("thread_id")
                session.session_key = cli_meta.get("session_key")
                session.platform = cli_meta.get("platform")
                session.save(touch_updated_at=False)
            else:
                msgs = get_cli_session_messages(sid)
                if not msgs:
                    raise KeyError("Session not found")
                session = import_cli_session(
                    sid,
                    cli_meta.get("title") or title_from(msgs, "CLI Session"),
                    msgs,
                    cli_meta.get("model") or "unknown",
                    profile=cli_meta.get("profile"),
                    created_at=cli_meta.get("created_at"),
                    updated_at=cli_meta.get("updated_at"),
                )
                session.is_cli_session = True
                session.source_tag = cli_meta.get("source_tag")
                session.raw_source = cli_meta.get("raw_source") or cli_meta.get("source_tag")
                session.session_source = cli_meta.get("session_source")
                session.source_label = cli_meta.get("source_label")
                session.user_id = cli_meta.get("user_id")
                session.chat_id = cli_meta.get("chat_id")
                session.chat_type = cli_meta.get("chat_type")
                session.thread_id = cli_meta.get("thread_id")
                session.session_key = cli_meta.get("session_key")
                session.platform = cli_meta.get("platform")
        with _get_session_agent_lock(sid):
            session.archived = bool(body.get("archived", True))
            session.save(touch_updated_at=False)
        publish_session_list_changed("session_archive")
        return {
            "ok": True,
            "session": session.compact(),
            **_worktree_retained_payload(session),
        }

    def move_session(self, *, session_id: str, project_id: str | None = None) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.models import load_projects
        from app.domain.profiles import _profiles_match, get_active_profile_name
        from app.domain.routes import _get_session_agent_lock  # noqa: PLC0415
        from app.domain.session_events import publish_session_list_changed

        body = {"session_id": session_id, "project_id": project_id}
        require(body, "session_id")
        try:
            session = self._repo.get(body["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        target_pid = body.get("project_id") or None
        if target_pid:
            active_profile = get_active_profile_name()
            target = next(
                (project for project in load_projects() if project["project_id"] == target_pid),
                None,
            )
            if not target:
                raise KeyError("Project not found")
            if not _profiles_match(target.get("profile"), active_profile):
                raise KeyError("Project not found")
        with _get_session_agent_lock(body["session_id"]):
            session.project_id = target_pid
            session.save()
        publish_session_list_changed("session_move")
        return {"ok": True, "session": session.compact()}

    def import_cli(self, *, session_id: str) -> dict[str, Any]:
        """Import or refresh a CLI session (legacy POST /api/session/import_cli)."""
        from app.domain.helpers import require
        from app.domain.models import (
            Session,
            get_cli_session_messages,
            get_cli_sessions,
            import_cli_session,
        )
        from app.domain.routes import (  # noqa: PLC0415
            _is_cli_tool_metadata_enrichment,
            _is_messages_refresh_prefix_match,
        )
        from app.domain.session_events import publish_session_list_changed
        from app.domain.workspace import get_last_workspace

        body = {"session_id": session_id}
        require(body, "session_id")
        sid = str(body["session_id"])
        existing = self._repo.load(sid)
        if existing:
            fresh_msgs = get_cli_session_messages(sid)
            changed = False
            cli_meta = None
            for cs in list(get_cli_sessions()):
                if cs["session_id"] == sid:
                    cli_meta = cs
                    break
            if fresh_msgs and len(fresh_msgs) > len(existing.messages):
                if _is_messages_refresh_prefix_match(existing.messages, fresh_msgs):
                    existing.messages = fresh_msgs
                    changed = True
            elif fresh_msgs and _is_cli_tool_metadata_enrichment(
                existing.messages, fresh_msgs
            ):
                existing.messages = fresh_msgs
                changed = True
            if cli_meta:
                updates = {
                    "is_cli_session": True,
                    "source_tag": existing.source_tag or cli_meta.get("source_tag"),
                    "raw_source": existing.raw_source
                    or cli_meta.get("raw_source")
                    or cli_meta.get("source_tag"),
                    "session_source": existing.session_source
                    or cli_meta.get("session_source"),
                    "source_label": existing.source_label or cli_meta.get("source_label"),
                    "parent_session_id": existing.parent_session_id
                    or cli_meta.get("parent_session_id"),
                }
                for attr, value in updates.items():
                    if getattr(existing, attr, None) != value:
                        setattr(existing, attr, value)
                        changed = True
            if changed:
                existing.save(touch_updated_at=False)
                publish_session_list_changed("session_import_cli")
            return {
                "session": existing.compact()
                | {
                    "messages": existing.messages,
                    "is_cli_session": True,
                    "read_only": bool((cli_meta or {}).get("read_only")),
                },
                "imported": False,
            }

        msgs = get_cli_session_messages(sid)
        if not msgs:
            raise KeyError("Session not found in CLI store")

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

        title = cli_title or title_from(msgs, "CLI Session")
        from app.domain.models import ensure_cron_project, is_cron_session

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
            return {"session": session_payload, "imported": False}

        session = import_cli_session(
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
            session.project_id = cron_project_id
        session.is_cli_session = True
        session.source_tag = cli_source_tag
        session.raw_source = cli_raw_source or cli_source_tag
        session.session_source = cli_session_source
        session.source_label = cli_source_label
        session.user_id = cli_user_id
        session.chat_id = cli_chat_id
        session.chat_type = cli_chat_type
        session.thread_id = cli_thread_id
        session.session_key = cli_session_key
        session.platform = cli_platform
        session._cli_origin = sid
        session.save(touch_updated_at=False)
        publish_session_list_changed("session_import_cli")
        return {
            "session": session.compact()
            | {
                "messages": msgs,
                "is_cli_session": True,
            },
            "imported": True,
        }

    def truncate_session(self, *, session_id: str, keep_count: int | None) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.models import get_session
        from app.domain.routes import _get_session_agent_lock  # noqa: PLC0415

        body = {"session_id": session_id, "keep_count": keep_count}
        require(body, "session_id")
        if body.get("keep_count") is None:
            raise ValueError("Missing required field(s): keep_count")
        try:
            session = get_session(body["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        keep = int(body["keep_count"])
        with _get_session_agent_lock(body["session_id"]):
            session.messages = session.messages[:keep]
            try:
                from app.domain.session_ops import _truncation_watermark_for

                session.truncation_watermark = _truncation_watermark_for(session.messages)
            except Exception:
                session.truncation_watermark = 0.0
            session.save()
        return {"ok": True, "session": session.compact() | {"messages": session.messages}}

    def duplicate_session(self, *, session_id: str) -> dict[str, Any]:
        from app.domain.config import LOCK, SESSIONS, SESSIONS_MAX
        from app.domain.models import Session
        from app.domain.session_events import publish_session_list_changed

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        session = Session.load(sid)
        if not session:
            raise KeyError("Session not found")
        copied_session = Session(
            session_id=uuid.uuid4().hex[:12],
            title=(session.title or "Untitled") + " (copy)",
            workspace=session.workspace,
            model=session.model,
            model_provider=session.model_provider,
            messages=copy.deepcopy(session.messages),
            tool_calls=copy.deepcopy(session.tool_calls),
            pinned=False,
            archived=False,
            project_id=session.project_id,
            profile=session.profile,
            input_tokens=session.input_tokens,
            output_tokens=session.output_tokens,
            estimated_cost=session.estimated_cost,
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
        copied_session.save()
        publish_session_list_changed("session_duplicate")
        return {
            "session": copied_session.compact() | {"messages": copied_session.messages},
        }

    def clear_session(self, *, session_id: str) -> dict[str, Any]:
        from app.domain.config import _evict_session_agent
        from app.domain.helpers import require
        from app.domain.models import get_session
        from app.domain.routes import _get_session_agent_lock  # noqa: PLC0415

        body = {"session_id": session_id}
        require(body, "session_id")
        try:
            session = get_session(body["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        sid = body["session_id"]
        with _get_session_agent_lock(sid):
            session.messages = []
            session.tool_calls = []
            session.title = "Untitled"
            session.save()
        _evict_session_agent(sid)
        return {"ok": True, "session": session.compact()}

    def conversation_rounds(
        self,
        *,
        session_id: str,
        since: float | None = None,
    ) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.models import CONVERSATION_ROUND_THRESHOLD, count_conversation_rounds

        body: dict[str, Any] = {"session_id": session_id, "since": since}
        require(body, "session_id")
        sid = str(body.get("session_id") or "").strip()
        if not sid:
            raise ValueError("session_id is required")
        parsed_since = body.get("since")
        if parsed_since is not None:
            try:
                parsed_since = float(parsed_since)
            except (TypeError, ValueError) as exc:
                raise ValueError("since must be a unix timestamp (number)") from exc
        rounds = count_conversation_rounds(sid, since=parsed_since)
        return {
            "ok": True,
            "rounds": rounds,
            "threshold": CONVERSATION_ROUND_THRESHOLD,
            "should_show": rounds >= CONVERSATION_ROUND_THRESHOLD,
        }

    def handoff_summary(
        self,
        *,
        session_id: str,
        since: float | None = None,
    ) -> tuple[dict[str, Any], int]:
        from app.domain.routes import _handle_handoff_summary  # noqa: PLC0415

        body: dict[str, Any] = {"session_id": session_id}
        if since is not None:
            body["since"] = since
        return _invoke_routes_json_handler(_handle_handoff_summary, body)

    def set_toolsets(
        self,
        *,
        session_id: str,
        toolsets: list[str] | None,
    ) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.models import get_session
        from app.domain.routes import _get_session_agent_lock  # noqa: PLC0415

        body = {"session_id": session_id, "toolsets": toolsets}
        require(body, "session_id")
        sid = body["session_id"]
        parsed_toolsets = body.get("toolsets")
        if parsed_toolsets is not None:
            if not isinstance(parsed_toolsets, list) or not parsed_toolsets:
                raise ValueError("toolsets must be a non-empty list or null")
            if not all(isinstance(item, str) and item for item in parsed_toolsets):
                raise ValueError("each toolset must be a non-empty string")
        try:
            session = get_session(sid)
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        with _get_session_agent_lock(sid):
            session.enabled_toolsets = parsed_toolsets
            session.save()
        return {"ok": True, "enabled_toolsets": session.enabled_toolsets}

    def import_session(self, body: dict[str, Any]) -> dict[str, Any]:
        from app.domain.routes import _handle_session_import  # noqa: PLC0415

        payload, status = _invoke_routes_json_handler(_handle_session_import, body)
        if status >= 400:
            message = payload.get("error") or payload.get("detail") or "Import failed"
            raise ValueError(str(message))
        return payload

    def retry_last_turn(self, *, session_id: str) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.session_ops import retry_last

        body = {"session_id": session_id}
        require(body, "session_id")
        try:
            result = retry_last(body["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        except ValueError as exc:
            return {"error": str(exc)}
        return {"ok": True, **result}

    def undo_last_turn(self, *, session_id: str) -> dict[str, Any]:
        from app.domain.helpers import require
        from app.domain.session_ops import undo_last

        body = {"session_id": session_id}
        require(body, "session_id")
        try:
            result = undo_last(body["session_id"])
        except KeyError as exc:
            raise KeyError("Session not found") from exc
        except ValueError as exc:
            return {"error": str(exc)}
        return {"ok": True, **result}

    def lineage_report(self, *, session_id: str) -> dict[str, Any]:
        from app.domain.agent_sessions import read_session_lineage_report
        from app.domain.models import _active_state_db_path

        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        report = read_session_lineage_report(_active_state_db_path(), sid)
        if not report.get("found"):
            raise KeyError("Session not found")
        return report

    def compress_status(self, session_id: str) -> tuple[dict[str, Any], int]:
        from app.domain.routes import _handle_session_compress_status  # noqa: PLC0415

        return _invoke_routes_json_handler(
            lambda handler, body: _handle_session_compress_status(handler, body.get("session_id", "")),
            {"session_id": session_id},
        )

    def compress_start(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        from app.domain.routes import _handle_session_compress_start  # noqa: PLC0415

        return _invoke_routes_json_handler(_handle_session_compress_start, body)

    def compress(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        from app.domain.routes import _handle_session_compress  # noqa: PLC0415

        return _invoke_routes_json_handler(_handle_session_compress, body)

    # Re-export legacy helpers until dedicated service logic lands.
    title_from = staticmethod(title_from)
    all_sessions = staticmethod(all_sessions)
