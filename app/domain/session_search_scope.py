"""Per-user scoping for session_search and WebUI session search APIs."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SCOPING_PATCHED = False


def normalize_session_owner_id(access: Any | None) -> str | None:
    """Return the normalized account id used for session ownership checks."""
    if access is None:
        return None
    raw = (
        getattr(access, "user_id", None)
        or getattr(access, "username", None)
        or getattr(access, "email", None)
    )
    cleaned = str(raw or "").strip().lower()
    return cleaned or None


def session_search_scoping_enabled(access: Any | None) -> bool:
    """True when multi-user mode is active and the caller has an account id."""
    if access is None:
        return False
    if not getattr(access, "multi_user_enabled", False):
        return False
    return normalize_session_owner_id(access) is not None


def profile_allowed_for_session_search(profile: str | None, access: Any | None) -> bool:
    if access is None or not session_search_scoping_enabled(access):
        return True
    if not getattr(access, "restricts_profiles", False):
        return True
    from app.domain.profiles import _profiles_match

    allowed = getattr(access, "allowed_profile_names", lambda: ())()
    if not allowed:
        return True
    target = str(profile or "").strip() or "default"
    return any(_profiles_match(target, name) for name in allowed)


def owned_webui_session_ids_for_user(
    user_id: str,
    *,
    profile: str | None = None,
) -> frozenset[str]:
    """Session ids owned by ``user_id`` in the WebUI JSON store."""
    uid = str(user_id or "").strip().lower()
    if not uid:
        return frozenset()

    from app.domain.models import all_sessions
    from app.domain.profiles import _profiles_match

    ids: set[str] = set()
    for row in all_sessions():
        sid = str(row.get("session_id") or "").strip()
        if not sid:
            continue
        owner = str(row.get("owner_user_id") or "").strip().lower()
        if owner:
            if owner == uid:
                ids.add(sid)
            continue
        if profile and _profiles_match(row.get("profile"), profile):
            # Legacy rows without owner_user_id are excluded from recall.
            continue
    return frozenset(ids)


def session_row_visible_to_user(
    meta: dict[str, Any] | None,
    *,
    user_id: str,
    owned_webui_ids: frozenset[str],
    session_id: str | None = None,
) -> bool:
    """Return True when a state.db session row may be recalled for ``user_id``."""
    uid = str(user_id or "").strip().lower()
    if not uid:
        return True
    sid = str((meta or {}).get("id") or session_id or "").strip()
    if not sid:
        return False
    row_user = str((meta or {}).get("user_id") or "").strip().lower()
    if row_user:
        return row_user == uid
    source = str((meta or {}).get("source") or "").strip().lower()
    if source == "webui":
        return sid in owned_webui_ids
    return False


class UserScopedSessionDB:
    """Filter SessionDB reads to sessions owned by one WebUI account."""

    def __init__(
        self,
        inner: Any,
        *,
        user_id: str,
        owned_webui_ids: frozenset[str],
    ) -> None:
        self._inner = inner
        self._user_id = str(user_id or "").strip().lower()
        self._owned_webui_ids = owned_webui_ids

    def _visible(self, session_id: str | None, meta: dict[str, Any] | None = None) -> bool:
        sid = str(session_id or (meta or {}).get("id") or "").strip()
        if not sid:
            return False
        row = dict(meta or {})
        if "user_id" not in row or row.get("user_id") in (None, ""):
            try:
                loaded = self._inner.get_session(sid) or {}
                if loaded:
                    row = {**loaded, **row}
            except Exception:
                pass
        return session_row_visible_to_user(
            row,
            user_id=self._user_id,
            owned_webui_ids=self._owned_webui_ids,
            session_id=sid,
        )

    def search_messages(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._inner.search_messages(*args, **kwargs)
        return [row for row in rows if self._visible(row.get("session_id"), row)]

    def list_sessions_rich(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._inner.list_sessions_rich(*args, **kwargs)
        return [row for row in rows if self._visible(row.get("id"), row)]

    def search_sessions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._inner.search_sessions(*args, **kwargs)
        return [row for row in rows if self._visible(row.get("id"), row)]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        meta = self._inner.get_session(session_id)
        if not meta:
            return None
        if not self._visible(session_id, meta):
            return None
        return meta

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        if not self._visible(session_id):
            return []
        return self._inner.get_messages(session_id)

    def get_messages_around(self, session_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not self._visible(session_id):
            return {"window": [], "messages_before": 0, "messages_after": 0}
        return self._inner.get_messages_around(session_id, *args, **kwargs)

    def ensure_session(self, *args: Any, **kwargs: Any) -> str:
        kwargs.setdefault("user_id", self._user_id)
        return self._inner.ensure_session(*args, **kwargs)

    def close(self) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def wrap_session_db_for_access(inner: Any | None, access: Any | None) -> Any | None:
    if inner is None or not session_search_scoping_enabled(access):
        return inner
    user_id = normalize_session_owner_id(access)
    if not user_id:
        return inner
    profile = getattr(access, "profile_name", None)
    owned = owned_webui_session_ids_for_user(user_id, profile=profile)
    return UserScopedSessionDB(inner, user_id=user_id, owned_webui_ids=owned)


def stamp_session_owner(session: Any, access: Any | None) -> bool:
    """Attach ``owner_user_id`` to a WebUI session when multi-user is active."""
    if session is None or not session_search_scoping_enabled(access):
        return False
    user_id = normalize_session_owner_id(access)
    if not user_id:
        return False
    current = str(getattr(session, "owner_user_id", None) or "").strip().lower()
    if current == user_id:
        return False
    session.owner_user_id = user_id
    return True


def tag_state_db_session_user(db: Any, session_id: str, user_id: str) -> None:
    sid = str(session_id or "").strip()
    uid = str(user_id or "").strip()
    if not sid or not uid or db is None:
        return

    def _do(conn: Any) -> None:
        conn.execute(
            "UPDATE sessions SET user_id = ? WHERE id = ? AND (user_id IS NULL OR user_id = '')",
            (uid, sid),
        )

    try:
        db._execute_write(_do)
    except Exception:
        logger.debug("Failed to tag state.db session %s with user_id", sid, exc_info=True)


def webui_session_row_visible(row: dict[str, Any], access: Any | None) -> bool:
    if not session_search_scoping_enabled(access):
        return True
    user_id = normalize_session_owner_id(access)
    if not user_id:
        return True
    owner = str(row.get("owner_user_id") or "").strip().lower()
    if owner:
        return owner == user_id
    return False


def install_webui_session_search_scoping() -> None:
    """Monkey-patch hermes-agent session_search helpers for per-user recall."""
    global _SCOPING_PATCHED
    if _SCOPING_PATCHED:
        return
    try:
        import tools.session_search_tool as session_search_tool
    except ImportError:
        return

    original_search = session_search_tool.session_search
    original_resolve = session_search_tool._resolve_profile_db
    original_locate = session_search_tool._locate_session_db

    def _access() -> Any:
        from app.domain.workspace import get_request_user_access

        return get_request_user_access()

    def _scoped_resolve_profile_db(profile: str | None):
        access = _access()
        if session_search_scoping_enabled(access):
            if profile and not profile_allowed_for_session_search(profile, access):
                raise ValueError(f"profile '{profile}' is not available for this account")
            db = original_resolve(profile)
            return wrap_session_db_for_access(db, access)
        return original_resolve(profile)

    def _scoped_locate_session_db(session_id: str):
        access = _access()
        db, owner = original_locate(session_id)
        if db is None:
            return None, None
        if not session_search_scoping_enabled(access):
            return db, owner
        wrapped = wrap_session_db_for_access(db, access)
        if wrapped is None or wrapped.get_session(session_id) is None:
            try:
                db.close()
            except Exception:
                pass
            return None, None
        return wrapped, owner

    def _scoped_session_search(*args: Any, **kwargs: Any):
        access = _access()
        db = kwargs.get("db")
        kwargs["db"] = wrap_session_db_for_access(db, access)
        profile = kwargs.get("profile")
        if session_search_scoping_enabled(access):
            if profile and not profile_allowed_for_session_search(profile, access):
                from tools.registry import tool_error

                return tool_error(
                    f"profile '{profile}' is not available for this account",
                    success=False,
                )
        return original_search(*args, **kwargs)

    session_search_tool._resolve_profile_db = _scoped_resolve_profile_db
    session_search_tool._locate_session_db = _scoped_locate_session_db
    session_search_tool.session_search = _scoped_session_search
    _SCOPING_PATCHED = True
