"""Chat conversation persistence in Supabase ``webui_sessions``."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.storage.connection import db_connection
from app.storage.audit import actor_or_system
from app.storage.timestamps import from_db_timestamp, to_db_timestamp, utc_now

logger = logging.getLogger(__name__)

_REPO_LOCK = threading.RLock()
_REPO: ChatSessionsRepository | None = None


def _backend() -> str:
    from app.storage.config import supabase_storage_enabled

    return "supabase" if supabase_storage_enabled() else "local"


def _session_owner_user_id(session: Any) -> str | None:
    try:
        from app.domain.workspace import get_request_user_access

        access = get_request_user_access()
        if access is not None:
            user_id = str(
                getattr(access, "user_id", None)
                or getattr(access, "username", None)
                or ""
            ).strip().lower()
            if user_id:
                return user_id
    except Exception:
        pass
    profile = str(getattr(session, "profile", None) or "").strip()
    if not profile:
        return None
    try:
        from app.domain.users import list_users

        for row in list_users():
            names = row.get("profile_names") or []
            primary = row.get("profile_name")
            if profile == primary or profile in names:
                return str(row.get("email") or row.get("username") or "").strip().lower() or None
    except Exception:
        logger.debug("Could not resolve user for profile %s", profile, exc_info=True)
    return None


class ChatSessionsRepository:
    """CRUD for agent chat sessions stored in ``webui_sessions`` on Supabase."""

    def enabled(self) -> bool:
        return _backend() == "supabase"

    def upsert_from_session(self, session: Any) -> None:
        if not self.enabled():
            return
        user_id = _session_owner_user_id(session)
        if not user_id:
            logger.debug(
                "Skipping Supabase chat session upsert for %s (no user_id)",
                getattr(session, "session_id", None),
            )
            return
        sid = str(getattr(session, "session_id", "") or "").strip()
        if not sid:
            return
        conversation = {
            "messages": getattr(session, "messages", None) or [],
            "tool_calls": getattr(session, "tool_calls", None) or [],
        }
        metadata: dict[str, Any] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "estimated_cost",
            "cache_read_tokens",
            "cache_write_tokens",
            "personality",
            "active_stream_id",
            "pending_user_message",
            "pending_attachments",
            "pending_started_at",
            "compression_anchor_visible_idx",
            "compression_anchor_message_key",
            "compression_anchor_summary",
            "pre_compression_snapshot",
            "context_engine",
            "compression_anchor_engine",
            "compression_anchor_mode",
            "compression_anchor_details",
            "context_engine_state",
            "context_length",
            "threshold_tokens",
            "last_prompt_tokens",
            "truncation_watermark",
            "gateway_routing",
            "gateway_routing_history",
            "llm_title_generated",
            "parent_session_id",
            "worktree_path",
            "worktree_branch",
            "worktree_repo_root",
            "worktree_created_at",
            "is_cli_session",
            "source_tag",
            "raw_source",
            "session_source",
            "source_label",
            "read_only",
            "enabled_toolsets",
            "composer_draft",
            "project_id",
            "message_count",
        ):
            if hasattr(session, key):
                metadata[key] = getattr(session, key)
        payload = {
            "id": sid,
            "user_id": user_id,
            "profile": str(getattr(session, "profile", None) or ""),
            "title": str(getattr(session, "title", None) or ""),
            "workspace": getattr(session, "workspace", None),
            "model": getattr(session, "model", None),
            "model_provider": getattr(session, "model_provider", None),
            "conversation": json.dumps(conversation, ensure_ascii=False),
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "pinned": 1 if getattr(session, "pinned", False) else 0,
            "archived": 1 if getattr(session, "archived", False) else 0,
            "created_at": getattr(session, "created_at", None),
            "updated_at": getattr(session, "updated_at", None),
        }
        with db_connection(backend="supabase") as (conn, dialect):
            now = utc_now(dialect)
            created = to_db_timestamp(payload["created_at"] or now, dialect)
            updated = to_db_timestamp(payload["updated_at"] or now, dialect)
            actor = actor_or_system(fallback=user_id)
            excluded = "EXCLUDED" if dialect.name == "postgres" else "excluded"
            conn.execute(
                dialect.q(
                    f"""
                    INSERT INTO webui_sessions (
                        id, user_id, profile, title, workspace, model, model_provider,
                        conversation, metadata, pinned, archived, created_at, updated_at,
                        created_by, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        user_id = {excluded}.user_id,
                        profile = {excluded}.profile,
                        title = {excluded}.title,
                        workspace = {excluded}.workspace,
                        model = {excluded}.model,
                        model_provider = {excluded}.model_provider,
                        conversation = {excluded}.conversation,
                        metadata = {excluded}.metadata,
                        pinned = {excluded}.pinned,
                        archived = {excluded}.archived,
                        updated_at = {excluded}.updated_at,
                        updated_by = {excluded}.updated_by
                    """
                ),
                (
                    payload["id"],
                    payload["user_id"],
                    payload["profile"],
                    payload["title"],
                    payload["workspace"],
                    payload["model"],
                    payload["model_provider"],
                    payload["conversation"],
                    payload["metadata"],
                    payload["pinned"],
                    payload["archived"],
                    created,
                    updated,
                    actor,
                    actor,
                ),
            )
            conn.commit()

    def load(self, session_id: str) -> dict[str, Any] | None:
        if not self.enabled():
            return None
        sid = str(session_id or "").strip()
        if not sid:
            return None
        with db_connection(backend="supabase") as (conn, dialect):
            row = conn.execute(
                dialect.q("SELECT * FROM webui_sessions WHERE id = ?"),
                (sid,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_document(row)

    def delete(self, session_id: str) -> bool:
        if not self.enabled():
            return False
        sid = str(session_id or "").strip()
        if not sid:
            return False
        with db_connection(backend="supabase") as (conn, dialect):
            cur = conn.execute(
                dialect.q("DELETE FROM webui_sessions WHERE id = ?"),
                (sid,),
            )
            conn.commit()
            return bool(getattr(cur, "rowcount", 0))

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        key = str(user_id or "").strip().lower()
        if not key:
            return []
        with db_connection(backend="supabase") as (conn, dialect):
            rows = conn.execute(
                dialect.q(
                    """
                    SELECT * FROM webui_sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC, created_at DESC
                    """
                ),
                (key,),
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def import_from_disk(self, session_dir: Any) -> int:
        if not self.enabled():
            return 0
        from pathlib import Path

        root = Path(session_dir)
        if not root.is_dir():
            return 0
        from app.domain.models import Session

        imported = 0
        for path in sorted(root.glob("*.json")):
            if path.name.startswith("_"):
                continue
            sid = path.stem
            try:
                session = Session.load(sid)
            except Exception:
                logger.debug("Skipping chat session import for %s", sid, exc_info=True)
                continue
            if session is None:
                continue
            try:
                self.upsert_from_session(session)
                imported += 1
            except Exception:
                logger.warning("Failed to import chat session %s to Supabase", sid, exc_info=True)
        return imported

    def _row_to_document(self, row: Any) -> dict[str, Any]:
        if hasattr(row, "keys"):
            data = {key: row[key] for key in row.keys()}
        else:
            keys = (
                "id",
                "user_id",
                "profile",
                "title",
                "workspace",
                "model",
                "model_provider",
                "conversation",
                "metadata",
                "pinned",
                "archived",
                "created_at",
                "updated_at",
            )
            data = {key: row[idx] for idx, key in enumerate(keys) if idx < len(row)}
        conversation_raw = data.get("conversation") or "{}"
        metadata_raw = data.get("metadata") or "{}"
        try:
            conversation = json.loads(str(conversation_raw))
        except json.JSONDecodeError:
            conversation = {}
        try:
            metadata = json.loads(str(metadata_raw))
        except json.JSONDecodeError:
            metadata = {}
        if not isinstance(conversation, dict):
            conversation = {}
        if not isinstance(metadata, dict):
            metadata = {}
        doc = {
            "session_id": str(data.get("id") or ""),
            "user_id": str(data.get("user_id") or ""),
            "profile": data.get("profile"),
            "title": data.get("title"),
            "workspace": data.get("workspace"),
            "model": data.get("model"),
            "model_provider": data.get("model_provider"),
            "messages": conversation.get("messages") or [],
            "tool_calls": conversation.get("tool_calls") or [],
            "pinned": bool(data.get("pinned")),
            "archived": bool(data.get("archived")),
            "created_at": from_db_timestamp(data.get("created_at")),
            "updated_at": from_db_timestamp(data.get("updated_at")),
            "created_by": str(data.get("created_by") or "").strip() or None,
            "updated_by": str(data.get("updated_by") or "").strip() or None,
        }
        doc.update(metadata)
        return doc


def get_chat_sessions_repository() -> ChatSessionsRepository:
    global _REPO
    with _REPO_LOCK:
        if _REPO is None:
            _REPO = ChatSessionsRepository()
        return _REPO


def reset_chat_sessions_repository() -> None:
    global _REPO
    with _REPO_LOCK:
        _REPO = None


__all__ = [
    "ChatSessionsRepository",
    "get_chat_sessions_repository",
    "reset_chat_sessions_repository",
]
