"""Session persistence repository — wraps api.models JSON CRUD."""

from __future__ import annotations

from typing import Any

from app.domain.models import Session, all_sessions, new_session
from app.domain.session_persistence import load_session_with_recovery, persist_session


class SessionRepository:
    """File-backed session store delegating to api.models."""

    def load(self, session_id: str) -> Session | None:
        return load_session_with_recovery(session_id)

    def load_metadata_only(self, session_id: str) -> Session | None:
        return Session.load_metadata_only(session_id)

    def get(self, session_id: str, *, metadata_only: bool = False) -> Session:
        from app.domain.models import get_session

        return get_session(session_id, metadata_only=metadata_only)

    def create(
        self,
        *,
        workspace: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        profile: str | None = None,
        project_id: str | None = None,
        worktree_info: dict | None = None,
    ) -> Session:
        return new_session(
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            profile=profile,
            project_id=project_id,
            worktree_info=worktree_info,
        )

    def save(
        self,
        session: Session,
        *,
        touch_updated_at: bool = True,
        skip_index: bool = False,
    ) -> None:
        persist_session(
            session,
            touch_updated_at=touch_updated_at,
            skip_index=skip_index,
        )

    def list_sessions(self, diag: Any = None) -> list[dict]:
        return all_sessions(diag=diag)

    def pop_from_cache(self, session_id: str) -> None:
        from app.domain.config import LOCK, SESSIONS

        with LOCK:
            SESSIONS.pop(session_id, None)

    def delete_session_files(self, session_id: str) -> None:
        from app.domain.models import SESSION_DIR

        try:
            from app.storage.repositories.chat_sessions import get_chat_sessions_repository

            get_chat_sessions_repository().delete(session_id)
        except Exception:
            pass

        path = (SESSION_DIR / f"{session_id}.json").resolve()
        path.relative_to(SESSION_DIR.resolve())
        path.unlink(missing_ok=True)
        path.with_suffix(".json.bak").unlink(missing_ok=True)

    def prune_index(self, session_id: str) -> None:
        from app.domain.models import prune_session_from_index

        prune_session_from_index(session_id)
