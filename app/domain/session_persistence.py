"""Documented write-path facade for WebUI session JSON sidecars.

This module is the c2 durability seam (PR1): callers that persist or load
conversation state should route through :func:`persist_session` and
:func:`load_session_with_recovery` so post-save side effects stay in one place.
Turn-journal append, streaming checkpoints, and chat_streaming internals are
out of scope for PR1 — see PR2.

Invariants (see ``docs/CONTRACTS.md``, ``app/domain/session_recovery.py``,
``docs/rfcs/turn-journal.md``, ``docs/rfcs/canonical-session-resolution.md``):

- **#1558 metadata-only guard:** never atomically overwrite on-disk messages
  with ``[]`` from a ``load_metadata_only`` stub; ``persist_session`` refuses
  via ``Session.save``.
- **Shrink-guard backup:** before a save that would shrink ``messages[]``, copy
  the previous JSON to ``<sid>.json.bak`` (atomic tmp+replace). Normal grows
  skip backup.
- **Atomic sidecar write:** session JSON uses pid/thread tmp + ``fsync`` +
  ``os.replace``; on-disk schema is unchanged.
- **Sidebar index cache:** after a full save, refresh ``_index.json`` via
  incremental patch unless ``skip_index=True``; index is advisory, not source
  of truth for transcripts.
- **Load-time recovery:** ``load_session_with_recovery`` may restore live JSON
  from ``.bak`` when the backup has strictly more messages (same rules as
  ``recover_session`` / startup recovery).
- **Session ID allowlist:** only ``[0-9a-z_]`` IDs are loaded; path traversal
  is rejected at the storage boundary.

PR2 remainder: route more call sites through this facade, consolidate
turn-journal hooks on submit/complete, and move delete/index-prune clusters.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models import Session

logger = logging.getLogger(__name__)


def write_shrink_guard_backup(session_path: Path, *, incoming_messages: list) -> None:
    """Write ``<sid>.json.bak`` when an incoming save would shrink ``messages[]``.

    Best-effort: failures do not block the main save. Mirrors the #1558 safeguard
    previously inlined in ``Session.save()``.
    """
    try:
        if not session_path.exists():
            return
        existing_text = session_path.read_text(encoding="utf-8")
        try:
            existing = json.loads(existing_text)
            existing_msg_count = len(existing.get("messages") or [])
        except (json.JSONDecodeError, ValueError):
            existing_msg_count = -1
        incoming_msg_count = len(incoming_messages or [])
        if existing_msg_count <= incoming_msg_count:
            return
        bak_path = session_path.with_suffix(".json.bak")
        bak_tmp = bak_path.with_suffix(
            f".bak.tmp.{os.getpid()}.{threading.current_thread().ident}"
        )
        try:
            with open(bak_tmp, "w", encoding="utf-8") as bf:
                bf.write(existing_text)
                bf.flush()
                os.fsync(bf.fileno())
            os.replace(bak_tmp, bak_path)
        except OSError:
            try:
                bak_tmp.unlink(missing_ok=True)
            except Exception:
                pass
    except OSError:
        pass


def refresh_session_index_after_save(session: Session) -> None:
    """Patch ``_index.json`` with this session's compact sidebar row."""
    from app.domain.models import _write_session_index

    _write_session_index(updates=[session])


def _session_from_chat_document(doc: dict) -> Session:
    from app.domain.models import Session

    payload = dict(doc)
    payload["session_id"] = str(
        payload.pop("session_id", None) or payload.pop("id", None) or ""
    ).strip()
    payload.pop("user_id", None)
    return Session(**payload)


def persist_session(
    session: Session,
    *,
    touch_updated_at: bool = True,
    skip_index: bool = False,
) -> None:
    """Persist one session sidecar and run post-save durability side effects."""
    session.save(touch_updated_at=touch_updated_at, skip_index=skip_index)
    try:
        from app.storage.repositories.chat_sessions import get_chat_sessions_repository

        get_chat_sessions_repository().upsert_from_session(session)
    except Exception:
        logger.debug(
            "Supabase chat session upsert failed for %s",
            getattr(session, "session_id", None),
            exc_info=True,
        )


def load_session_with_recovery(session_id: str) -> Session | None:
    """Load a session JSON sidecar, restoring from ``.bak`` when recommended."""
    from app.domain.models import SESSION_DIR, Session
    from app.domain.session_recovery import recover_session

    if not session_id or not all(
        c in "0123456789abcdefghijklmnopqrstuvwxyz_" for c in session_id
    ):
        return None

    try:
        from app.storage.repositories.chat_sessions import get_chat_sessions_repository

        repo = get_chat_sessions_repository()
        if repo.enabled():
            doc = repo.load(session_id)
            if doc:
                session = _session_from_chat_document(doc)
                session_path = SESSION_DIR / f"{session_id}.json"
                if not session_path.exists():
                    session.save(touch_updated_at=False, skip_index=True)
                return session
    except Exception:
        logger.debug(
            "Supabase chat session load failed for %s; falling back to disk",
            session_id,
            exc_info=True,
        )

    session_path = SESSION_DIR / f"{session_id}.json"
    if session_path.exists() or session_path.with_suffix(".json.bak").exists():
        recover_session(session_path)
    return Session.load(session_id)
