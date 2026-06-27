"""Git service — native FastAPI cutover for workspace git operations."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from app.domain.helpers import _sanitize_error, require
from app.domain.models import get_session

logger = logging.getLogger(__name__)


class GitService:
    def _git_error(self, err: Exception, *, status: int = 400) -> tuple[dict[str, Any], int]:
        return (
            {
                "error": _sanitize_error(err),
                "code": getattr(err, "code", "git_failed") or "git_failed",
            },
            status,
        )

    def _session(self, session_id: str) -> tuple[Any | None, dict[str, Any] | None, int | None]:
        if not session_id:
            return None, {"error": "session_id required"}, 400
        try:
            return get_session(session_id), None, None
        except KeyError:
            return None, {"error": "Session not found"}, 404

    def _workspace(self, session_id: str) -> tuple[Path | None, dict[str, Any] | None, int | None]:
        session, err, status = self._session(session_id)
        if err:
            return None, err, status
        from app.domain.workspace import resolve_session_workspace

        return resolve_session_workspace(session.workspace), None, None

    def _session_and_workspace(
        self,
        session_id: str,
    ) -> tuple[Any | None, Path | None, dict[str, Any] | None, int | None]:
        session, err, status = self._session(session_id)
        if err:
            return None, None, err, status
        from app.domain.workspace import resolve_session_workspace

        return session, resolve_session_workspace(session.workspace), None, None

    def _locked_by_active_stream(self, session: Any) -> bool:
        stream_id = getattr(session, "active_stream_id", None)
        if not stream_id:
            return False
        try:
            from app.domain.config import STREAMS, STREAMS_LOCK

            with STREAMS_LOCK:
                return stream_id in STREAMS
        except Exception:
            return False

    def _reject_destructive_if_unsafe(
        self,
        session: Any,
    ) -> tuple[dict[str, Any], int] | None:
        from app.domain.workspace_git import (
            GitWorkspaceError,
            WORKSPACE_GIT_DESTRUCTIVE_ENV,
            workspace_git_destructive_enabled,
        )

        if not workspace_git_destructive_enabled():
            return self._git_error(
                GitWorkspaceError(
                    f"Destructive workspace Git operations are disabled. Set {WORKSPACE_GIT_DESTRUCTIVE_ENV}=1 to enable them.",
                    "destructive_git_disabled",
                ),
                status=403,
            )
        if self._locked_by_active_stream(session):
            return self._git_error(
                GitWorkspaceError(
                    "A session run is active. Wait for it to finish before running this Git operation.",
                    "active_stream",
                ),
                status=409,
            )
        return None

    @staticmethod
    def _paths_from_body(body: dict[str, Any]) -> list[str]:
        raw_paths = body.get("paths")
        if raw_paths is None and body.get("path"):
            raw_paths = [body.get("path")]
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        if not isinstance(raw_paths, list):
            raise ValueError("paths must be a list")
        return [str(path) for path in raw_paths]

    def _llm_git_commit_message(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        session: Any | None = None,
    ) -> str:
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
            main_model, main_provider, main_base_url = resolve_model_provider(model_for_resolution)
            main_api_key = None
            try:
                from app.domain.oauth import resolve_runtime_provider_with_anthropic_env_lock
                from hermes_cli.runtime_provider import resolve_runtime_provider

                runtime = resolve_runtime_provider_with_anthropic_env_lock(
                    resolve_runtime_provider,
                    requested=main_provider,
                )
                main_api_key = runtime.get("api_key")
                if not main_provider:
                    main_provider = runtime.get("provider")
                if not main_base_url:
                    main_base_url = runtime.get("base_url")
            except Exception as exc:
                logger.debug("git commit message runtime provider resolution failed: %s", exc)
            if isinstance(main_provider, str) and main_provider.startswith("custom:"):
                custom_key, custom_base = resolve_custom_provider_connection(main_provider)
                if not main_api_key and custom_key:
                    main_api_key = custom_key
                if not main_base_url and custom_base:
                    main_base_url = custom_base

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            main_runtime = {
                "provider": main_provider,
                "model": main_model,
                "base_url": main_base_url,
                "api_key": main_api_key,
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
            except Exception as exc:
                logger.debug(
                    "git commit message auxiliary model failed; falling back to main model: %s",
                    exc,
                )

            from run_agent import AIAgent

            agent = AIAgent(
                model=main_model,
                provider=main_provider,
                base_url=main_base_url,
                api_key=main_api_key,
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

    def git_status(self, session_id: str) -> tuple[dict[str, Any], int | None]:
        workspace, err, status = self._workspace(session_id)
        if err:
            return err, status
        try:
            from app.domain.workspace_git import GitWorkspaceError, git_status

            return {"git": git_status(workspace)}, None
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_branches(self, session_id: str) -> tuple[dict[str, Any], int | None]:
        workspace, err, status = self._workspace(session_id)
        if err:
            return err, status
        try:
            from app.domain.workspace_git import GitWorkspaceError, git_branches

            return {"branches": git_branches(workspace)}, None
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_diff(
        self,
        *,
        session_id: str,
        path: str,
        kind: str = "unstaged",
    ) -> tuple[dict[str, Any], int | None]:
        workspace, err, status = self._workspace(session_id)
        if err:
            return err, status
        if not path:
            return {"error": "path required"}, 400
        try:
            from app.domain.workspace_git import GitWorkspaceError, git_diff

            return {"diff": git_diff(workspace, path, kind)}, None
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_info(self, session_id: str) -> tuple[dict[str, Any], int | None]:
        session, err, status = self._session(session_id)
        if err:
            return err, status
        try:
            from app.domain.workspace_git import GitWorkspaceError, git_status

            from app.domain.workspace import resolve_session_workspace

            status_payload = git_status(resolve_session_workspace(session.workspace))
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code
        totals = status_payload.get("totals") or {}
        info = None if not status_payload.get("is_git") else {
            "branch": status_payload.get("branch"),
            "dirty": totals.get("changed", 0),
            "modified": (totals.get("staged", 0) or 0) + (totals.get("unstaged", 0) or 0),
            "untracked": totals.get("untracked", 0),
            "ahead": status_payload.get("ahead", 0),
            "behind": status_payload.get("behind", 0),
            "is_git": True,
        }
        return {"git": info}, None

    def git_stage(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id")
            paths = self._paths_from_body(body)
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_stage

            return {"ok": True, "git": git_stage(workspace, paths)}, None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_unstage(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id")
            paths = self._paths_from_body(body)
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_unstage

            return {"ok": True, "git": git_unstage(workspace, paths)}, None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_discard(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id")
            paths = self._paths_from_body(body)
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_discard

            return {
                "ok": True,
                "git": git_discard(
                    workspace,
                    paths,
                    delete_untracked=bool(body.get("delete_untracked")),
                ),
            }, None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_commit_message(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        from app.domain.workspace_git import (
            GitWorkspaceError,
            clean_generated_commit_message,
            staged_commit_message_prompt,
        )

        try:
            require(body, "session_id")
            from app.domain.workspace import resolve_session_workspace

            session = get_session(body["session_id"])
            workspace = resolve_session_workspace(session.workspace)
            prompt = staged_commit_message_prompt(workspace)
            message = clean_generated_commit_message(
                self._llm_git_commit_message(
                    prompt["system_prompt"],
                    prompt["user_prompt"],
                    session=session,
                )
            )
            if not message:
                raise GitWorkspaceError("No commit message was generated")
            return {
                "ok": True,
                "message": message,
                "truncated": bool(prompt.get("truncated")),
            }, None
        except KeyError:
            return {"error": "Session not found"}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code
        except Exception as exc:
            logger.exception("git commit message generation failed")
            return {"error": _sanitize_error(exc)}, 500

    def git_commit_message_selected(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        from app.domain.workspace_git import (
            GitWorkspaceError,
            clean_generated_commit_message,
            selected_commit_message_prompt,
        )

        try:
            require(body, "session_id")
            paths = self._paths_from_body(body)
            from app.domain.workspace import resolve_session_workspace

            session = get_session(body["session_id"])
            workspace = resolve_session_workspace(session.workspace)
            prompt = selected_commit_message_prompt(workspace, paths)
            message = clean_generated_commit_message(
                self._llm_git_commit_message(
                    prompt["system_prompt"],
                    prompt["user_prompt"],
                    session=session,
                )
            )
            if not message:
                raise GitWorkspaceError("No commit message was generated")
            return {
                "ok": True,
                "message": message,
                "truncated": bool(prompt.get("truncated")),
            }, None
        except KeyError:
            return {"error": "Session not found"}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code
        except Exception as exc:
            logger.exception("selected git commit message generation failed")
            return {"error": _sanitize_error(exc)}, 500

    def git_commit(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id", "message")
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_commit

            return git_commit(workspace, body.get("message", "")), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_commit_selected(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id", "message")
            paths = self._paths_from_body(body)
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_commit_selected

            return git_commit_selected(workspace, body.get("message", ""), paths), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_fetch(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return self._git_remote_action(body, "fetch")

    def git_pull(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return self._git_remote_action(body, "pull")

    def git_push(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return self._git_remote_action(body, "push")

    def _git_remote_action(
        self,
        body: dict[str, Any],
        action: str,
    ) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id")
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            if action in {"pull", "push"}:
                blocked = self._reject_destructive_if_unsafe(session)
                if blocked:
                    return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_fetch, git_pull, git_push

            actions = {
                "fetch": git_fetch,
                "pull": git_pull,
                "push": git_push,
            }
            return actions[action](workspace), None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_checkout(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id", "ref", "mode")
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_checkout

            result = git_checkout(
                workspace,
                str(body.get("ref", "")),
                str(body.get("mode", "local")),
                new_branch=body.get("new_branch"),
                track=bool(body.get("track")),
                dirty_mode=str(body.get("dirty_mode", "block")),
            )
            return {
                "ok": True,
                "git": result.get("status"),
                "branches": result.get("branches"),
                "current_branch": result.get("current_branch"),
                "message": result.get("message", ""),
            }, None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code

    def git_stash_checkout(self, body: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        try:
            require(body, "session_id", "ref", "mode")
            session, workspace, err, status = self._session_and_workspace(body["session_id"])
            if err:
                return err, status
            blocked = self._reject_destructive_if_unsafe(session)
            if blocked:
                return blocked
            from app.domain.workspace_git import GitWorkspaceError, git_stash_and_checkout

            result = git_stash_and_checkout(
                workspace,
                str(body.get("ref", "")),
                str(body.get("mode", "local")),
                new_branch=body.get("new_branch"),
                track=bool(body.get("track")),
            )
            return {
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
            }, None
        except ValueError as exc:
            return {"error": str(exc)}, 400
        except GitWorkspaceError as exc:
            payload, code = self._git_error(exc)
            return payload, code
