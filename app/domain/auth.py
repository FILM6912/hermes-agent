"""
Hermes Web UI -- optional authentication.
Off by default. Enable by setting HERMES_WEBUI_PASSWORD, configuring a
password in Settings, or registering passkeys and then going passwordless.
"""
import hashlib
import hmac
import http.cookies
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time

from app.domain.config import STATE_DIR, load_settings

logger = logging.getLogger(__name__)


# Default session TTL — 30 days. Kept as a module-level constant for backwards
# compatibility with downstream code and regression tests that import it.
# At runtime, prefer ``_resolve_session_ttl()`` which honours the env var and
# settings.json overrides; this constant is the floor / fallback.
SESSION_TTL = 86400 * 30  # 30 days


_TTL_MIN = 60
_TTL_MAX = 86400 * 365 * 10
_TTL_UNIT_SECONDS = {
    'y': 86400 * 365,
    'd': 86400,
    'h': 3600,
    'm': 60,
    's': 1,
}
_TTL_PART_RE = re.compile(r'(\d+)\s*([ydhms])', flags=re.IGNORECASE)


def _parse_session_ttl_value(raw: str) -> int | None:
    """Parse TTL from seconds string or human-readable duration tokens.

    Accepted examples: ``3600``, ``30d``, ``12h 30m``, ``1y 2d 10m 55s``.
    Returns ``None`` for invalid formats or out-of-range values.
    """
    value = (raw or '').strip()
    if not value:
        return None

    if value.isdigit():
        parsed = int(value)
    else:
        total = 0
        end = 0
        matched = False
        for match in _TTL_PART_RE.finditer(value):
            if value[end:match.start()].strip():
                return None
            qty = int(match.group(1))
            unit = match.group(2).lower()
            total += qty * _TTL_UNIT_SECONDS[unit]
            end = match.end()
            matched = True
        if not matched or value[end:].strip():
            return None
        parsed = total

    if _TTL_MIN <= parsed <= _TTL_MAX:
        return parsed
    return None


def _resolve_session_ttl() -> int:
    """Resolve session TTL from env > settings > default.

    Priority mirrors get_password_hash(): HERMES_WEBUI_SESSION_TTL env var
    first, then settings.json, falling back to ``SESSION_TTL`` (30 days).
    Env accepts seconds or duration tokens (e.g. ``30d``, ``12h 30m``).
    Values are clamped to [60s, 10 years] to prevent runaway cookies.
    """
    env_v = os.getenv('HERMES_WEBUI_SESSION_TTL', '').strip()
    env_ttl = _parse_session_ttl_value(env_v)
    if env_ttl is not None:
        return env_ttl
    s = load_settings()
    v = s.get('session_ttl_seconds')
    if isinstance(v, int) and _TTL_MIN <= v <= _TTL_MAX:
        return v
    return SESSION_TTL


# ── Public paths (no auth required) ─────────────────────────────────────────
PUBLIC_PATHS = frozenset({
    '/login', '/health', '/favicon.ico', '/sw.js',
    '/api/auth/login', '/api/auth/logout', '/api/auth/status',
    '/api/auth/passkey/options', '/api/auth/passkey/login',
    '/api/v1/system/bootstrap-admin',
    '/api/system/health', '/api/v1/system/health',
    '/manifest.json', '/manifest.webmanifest',
    '/session/manifest.json', '/session/manifest.webmanifest',
})

COOKIE_NAME = 'hermes_session'
CSRF_HEADER_NAME = 'X-Hermes-CSRF-Token'
_BEARER_AUTH_RE = re.compile(r'^Bearer\s+(\S+)\s*$', re.IGNORECASE)

_SESSIONS_FILE = STATE_DIR / '.sessions.json'

_SESSIONS_LOCK = threading.Lock()


def _sessions_repository():
    from app.storage.repositories.sessions import ensure_sessions_migrated, get_sessions_repository

    ensure_sessions_migrated()
    return get_sessions_repository()


def _persist_session(token: str, entry: dict) -> None:
    """Write a session to the in-process cache and normalized storage."""
    with _SESSIONS_LOCK:
        _sessions[token] = dict(entry)
    try:
        _sessions_repository().create_session(
            token,
            user_id=str(entry.get("user_id") or "legacy"),
            role=str(entry.get("role") or "admin"),
            exp=float(entry.get("exp") or time.time()),
        )
    except Exception as exc:
        from app.storage.config import supabase_storage_enabled

        if supabase_storage_enabled():
            logger.warning(
                "Failed to persist session to webui_sessions (Supabase configured): %s",
                exc,
            )
        else:
            logger.debug("Failed to persist session to webui_sessions: %s", exc)
        _save_sessions(_sessions)


def _lookup_session(token: str) -> dict | None:
    """Resolve session metadata from cache or normalized storage."""
    if not token:
        return None
    with _SESSIONS_LOCK:
        cached = _sessions.get(token)
    if cached is not None:
        normalized = _normalize_session_entry(cached)
        if normalized is not None:
            return normalized
    try:
        row = _sessions_repository().get_by_token(token)
    except Exception as exc:
        logger.debug("Failed to load session from webui_sessions: %s", exc)
        row = None
    if row is None:
        return None
    with _SESSIONS_LOCK:
        _sessions[token] = dict(row)
    return row


def _remove_session(token: str) -> None:
    with _SESSIONS_LOCK:
        _sessions.pop(token, None)
    try:
        _sessions_repository().revoke(token=token)
    except Exception as exc:
        logger.debug("Failed to revoke session in webui_sessions: %s", exc)
        _save_sessions(_sessions)


def _session_expiry(entry) -> float | None:
    """Return expiry timestamp from a session entry (legacy float or dict)."""
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, dict):
        exp = entry.get('exp')
        if isinstance(exp, (int, float)):
            return float(exp)
    return None


def _normalize_session_entry(entry, *, now: float | None = None) -> dict | None:
    """Normalize legacy float entries and dict entries into session metadata."""
    if now is None:
        now = time.time()
    exp = _session_expiry(entry)
    if exp is None or exp <= now:
        return None
    if isinstance(entry, dict):
        user_id = str(entry.get('user_id') or 'legacy')
        role = str(entry.get('role') or 'admin')
    else:
        user_id = 'legacy'
        role = 'admin'
    return {'exp': exp, 'user_id': user_id, 'role': role}


def _load_sessions() -> dict[str, dict]:
    """Load persisted sessions from STATE_DIR, pruning expired entries.

    Returns an empty dict on any read or parse error so startup is never
    blocked by a corrupt or missing sessions file.
    """
    try:
        if _SESSIONS_FILE.exists():
            data = json.loads(_SESSIONS_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('malformed sessions file — expected dict')
            now = time.time()
            sessions: dict[str, dict] = {}
            for token, entry in data.items():
                if not isinstance(token, str):
                    continue
                normalized = _normalize_session_entry(entry, now=now)
                if normalized is not None:
                    sessions[token] = normalized
            return sessions
    except Exception as e:
        logger.debug("Failed to load sessions file, starting fresh: %s", e)
    return {}


def _save_sessions(sessions: dict[str, dict]) -> None:
    """Atomically persist sessions to STATE_DIR/.sessions.json (0600).

    Uses a temp file + os.replace() so a crash mid-write never leaves a
    truncated file.  Mirrors the same pattern as .signing_key persistence.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix='.sessions.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(sessions, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _SESSIONS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to persist sessions: %s", e)


# Active sessions: token -> metadata (process cache; durable store is webui_sessions)
_sessions: dict[str, dict] = {}


def bootstrap_auth_sessions() -> None:
    """Warm the process cache from legacy JSON and migrate into webui_sessions.

    Call after ``init_storage()`` so the Supabase/SQLite schema exists before
    migration and new logins persist to ``webui_sessions``.
    """
    legacy = _load_sessions()
    if legacy:
        with _SESSIONS_LOCK:
            _sessions.update(legacy)
        try:
            repo = _sessions_repository()
            if repo.count() == 0:
                imported = repo.import_from_documents(legacy)
                if imported:
                    logger.info(
                        "Imported %s legacy auth session(s) from .sessions.json into webui_sessions",
                        imported,
                    )
        except Exception as exc:
            from app.storage.config import supabase_storage_enabled

            if supabase_storage_enabled():
                logger.warning("Auth session bootstrap migration skipped: %s", exc)
            else:
                logger.debug("Auth session bootstrap migration skipped: %s", exc)
    try:
        _sessions_repository().cleanup_expired()
    except Exception as exc:
        logger.debug("Auth session startup cleanup skipped: %s", exc)

# ── Login rate limiter ──────────────────────────────────────────────────────
_LOGIN_ATTEMPTS_FILE = STATE_DIR / '.login_attempts.json'
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 60  # seconds


def _load_login_attempts() -> dict[str, list[float]]:
    """Load persisted login attempts from STATE_DIR, pruning expired entries."""
    try:
        if _LOGIN_ATTEMPTS_FILE.exists():
            data = json.loads(_LOGIN_ATTEMPTS_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('malformed login-attempts file — expected dict')
            now = time.time()
            attempts: dict[str, list[float]] = {}
            for ip, raw_times in data.items():
                if not isinstance(ip, str) or not isinstance(raw_times, list):
                    continue
                fresh = [
                    float(t)
                    for t in raw_times
                    if isinstance(t, (int, float)) and now - float(t) < _LOGIN_WINDOW
                ]
                if fresh:
                    attempts[ip] = fresh
            return attempts
    except Exception as e:
        logger.debug("Failed to load login attempts file, starting fresh: %s", e)
    return {}


def _save_login_attempts(attempts: dict[str, list[float]]) -> None:
    """Atomically persist login attempts to STATE_DIR/.login_attempts.json (0600)."""
    try:
        _LOGIN_ATTEMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_LOGIN_ATTEMPTS_FILE.parent, suffix='.login_attempts.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(attempts, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _LOGIN_ATTEMPTS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.debug("Failed to persist login attempts: %s", e)


_login_attempts = _load_login_attempts()  # ip -> [timestamp, ...]
_LOGIN_ATTEMPTS_LOCK = threading.Lock()


def _check_login_rate(ip: str) -> bool:
    """Return True if the IP is allowed to attempt login (thread-safe)."""
    with _LOGIN_ATTEMPTS_LOCK:
        now = time.time()
        attempts = _login_attempts.get(ip, [])
        # Prune old attempts
        attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
        if attempts:
            _login_attempts[ip] = attempts
        else:
            _login_attempts.pop(ip, None)
        _save_login_attempts(_login_attempts)
        return len(attempts) < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt(ip: str) -> None:
    """Record a login attempt for rate limiting (thread-safe)."""
    with _LOGIN_ATTEMPTS_LOCK:
        now = time.time()
        attempts = _login_attempts.get(ip, [])
        attempts.append(now)
        _login_attempts[ip] = attempts
        _save_login_attempts(_login_attempts)


def _load_key(filename: str) -> bytes:
    """Load a 32-byte key from STATE_DIR, generating and persisting one if missing."""
    key_file = STATE_DIR / filename
    try:
        if key_file.exists():
            raw = key_file.read_bytes()
            if len(raw) >= 32:
                return raw[:32]
    except OSError:
        logger.debug("Failed to read key %s", filename)
    key = secrets.token_bytes(32)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(key)
        key_file.chmod(0o600)
    except OSError:
        logger.debug("Failed to persist key %s", filename)
    return key


_PBKDF2_KEY_CACHE: bytes | None = None
_SIGNING_KEY_CACHE: bytes | None = None


def _pbkdf2_key() -> bytes:
    global _PBKDF2_KEY_CACHE
    if _PBKDF2_KEY_CACHE is None:
        _PBKDF2_KEY_CACHE = _load_key('.pbkdf2_key')
    return _PBKDF2_KEY_CACHE


def _signing_key() -> bytes:
    global _SIGNING_KEY_CACHE
    if _SIGNING_KEY_CACHE is None:
        _SIGNING_KEY_CACHE = _load_key('.signing_key')
    return _SIGNING_KEY_CACHE


def _hash_password(password, *, salt: bytes | None = None) -> str:
    """PBKDF2-SHA256 with 600k iterations (OWASP recommendation).
    Salt is the persisted PBKDF2 key, which is secret and unique per
    installation. This keeps the stored hash format a plain hex string
    (no format change to settings.json) while replacing the predictable
    STATE_DIR-derived salt from the original implementation.

    The *salt* parameter exists solely to support transparent migration
    of password hashes that were computed with a different key (e.g. the
    old `.signing_key`). Normal callers should never pass it.
    """
    if salt is None:
        salt = _pbkdf2_key()
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return dk.hex()


_AUTH_HASH_LOCK = threading.Lock()
_AUTH_HASH_COMPUTED: bool = False
_AUTH_HASH_CACHE: str | None = None


def _invalidate_password_hash_cache() -> None:
    """Invalidate the in-process password hash cache so the next call to
    get_password_hash() re-reads from settings.json or the env var."""
    global _AUTH_HASH_COMPUTED, _AUTH_HASH_CACHE
    with _AUTH_HASH_LOCK:
        _AUTH_HASH_COMPUTED = False
        _AUTH_HASH_CACHE = None


def get_password_hash() -> str | None:
    """Return the active password hash, or None if auth is disabled.
    Priority: env var > settings.json.

    The hash is computed once and cached for the lifetime of the process.
    PBKDF2-600k takes ~1 s and is called on nearly every HTTP request via
    check_auth → is_auth_enabled, so caching avoids wasting a full second
    of CPU per request after the first one.

    Thread-safe: double-checked locking ensures that under a burst of
    concurrent requests only one thread computes PBKDF2, while the fast
    path (after initialisation) requires zero locks.
    """
    global _AUTH_HASH_COMPUTED, _AUTH_HASH_CACHE

    # Pytest subprocess mutates settings.json between tests; avoid stale auth cache.
    if os.environ.get("HERMES_WEBUI_TEST_NETWORK_BLOCK") == "1":
        env_pw = os.getenv('HERMES_WEBUI_PASSWORD', '').strip()
        if env_pw:
            return _hash_password(env_pw)
        return load_settings().get('password_hash') or None

    # Fast path — no lock needed once cache is populated.
    if _AUTH_HASH_COMPUTED:
        return _AUTH_HASH_CACHE

    with _AUTH_HASH_LOCK:
        # Re-check inside lock — another thread may have populated while
        # we were waiting to acquire.
        if _AUTH_HASH_COMPUTED:
            return _AUTH_HASH_CACHE

        env_pw = os.getenv('HERMES_WEBUI_PASSWORD', '').strip()
        if env_pw:
            result = _hash_password(env_pw)
        else:
            result = load_settings().get('password_hash') or None

        _AUTH_HASH_CACHE = result
        _AUTH_HASH_COMPUTED = True
        return result


def is_password_auth_enabled() -> bool:
    """True if a password is configured (env var or settings)."""
    return get_password_hash() is not None


def _passkey_feature_flag_enabled() -> bool:
    """Return True if the passkey/WebAuthn surface is enabled for this deployment.

    Passkey support is opt-in default-off behind a feature flag so deployments
    that don't want the WebAuthn surface (or whose RP-ID setup isn't ready for
    non-localhost hosts) can disable it entirely with no UI surface, no
    endpoints, no credential storage. To enable:

      - Set ``HERMES_WEBUI_PASSKEY=1`` in the environment, OR
      - Set ``webui_passkey_enabled: true`` in the per-profile config.yaml

    With the flag off, ``are_passkeys_enabled()`` always returns False even if
    credentials were registered in the past, and ``/login`` shows password-only.
    """
    env_value = os.getenv("HERMES_WEBUI_PASSKEY", "")
    if env_value:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from app.domain.config import get_config

        cfg = get_config()
        if isinstance(cfg, dict):
            raw = cfg.get("webui_passkey_enabled")
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        pass
    return False


def are_passkeys_enabled() -> bool:
    """True if the passkey feature flag is on AND at least one local passkey credential is registered."""
    if not _passkey_feature_flag_enabled():
        return False
    try:
        from app.domain.passkeys import passkeys_available

        return passkeys_available()
    except Exception as exc:
        logger.debug("Failed to inspect passkey availability: %s", exc)
        return False


def is_auth_enabled() -> bool:
    """True if password auth, passkey-only auth, or multi-user storage is configured."""
    from app.domain.users import is_multi_user_enabled

    return is_password_auth_enabled() or are_passkeys_enabled() or is_multi_user_enabled()


def verify_password(plain: str) -> bool:
    """Verify a plaintext password against the stored hash.

    Supports transparent migration of password hashes that were computed
    with the old `.signing_key` salt.  When the two keys differ and the
    legacy-salted hash matches, the password is transparently re-hashed
    with the current `.pbkdf2_key` and persisted to settings.json.
    """
    expected = get_password_hash()
    if not expected:
        return False
    # Fast path: current PBKDF2 key
    if hmac.compare_digest(_hash_password(plain), expected):
        return True
    # Migration: some hashes were computed with `.signing_key` before the
    # PBKDF2 key was separated.  Try the legacy salt; if it matches,
    # transparently upgrade so the next login uses the fast path.
    legacy_salt = _signing_key()
    current_salt = _pbkdf2_key()
    if legacy_salt != current_salt:
        if hmac.compare_digest(_hash_password(plain, salt=legacy_salt), expected):
            from app.domain.config import save_settings

            save_settings({'_set_password': plain})
            # Password re-hashed and persisted to disk using the current salt.
            # Cache invalidation is handled by fix 2/3 (#2192) which adds the
            # _invalidate_password_hash_cache() call inside save_settings().
            return True
    return False


def create_session(*, user_id: str = 'legacy', role: str = 'admin') -> str:
    """Create a new auth session. Returns signed cookie value."""
    token = secrets.token_hex(32)
    entry = {
        'exp': time.time() + _resolve_session_ttl(),
        'user_id': user_id,
        'role': role,
    }
    _persist_session(token, entry)
    sig = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def _prune_expired_sessions():
    """Remove all expired session entries to prevent unbounded memory growth."""
    now = time.time()
    with _SESSIONS_LOCK:
        expired = [
            t for t, entry in _sessions.items()
            if (exp := _session_expiry(entry)) is None or now > exp
        ]
        for token in expired:
            _sessions.pop(token, None)
    if expired:
        try:
            _sessions_repository().cleanup_expired(now=now)
        except Exception as exc:
            logger.debug("Failed to prune webui_sessions: %s", exc)
            _save_sessions(_sessions)
    elif not expired:
        try:
            _sessions_repository().cleanup_expired(now=now)
        except Exception:
            pass


def verify_session(cookie_value: str) -> bool:
    """Verify a signed session cookie. Returns True if valid and not expired."""
    if not cookie_value or '.' not in cookie_value:
        return False
    _prune_expired_sessions()  # lazy cleanup on every verification attempt
    token, sig = cookie_value.rsplit('.', 1)
    full_sig = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()
    # Accept both new (64-char) and legacy (32-char truncated) signatures so
    # existing sessions survive the upgrade without a forced global logout.
    # The legacy branch can be removed once session TTLs have expired (~30 days).
    valid = hmac.compare_digest(sig, full_sig) or (
        len(sig) == 32 and hmac.compare_digest(sig, full_sig[:32])
    )
    if not valid:
        return False
    entry = _lookup_session(token)
    expiry = _session_expiry(entry)
    if expiry is None or time.time() > expiry:
        _remove_session(token)
        return False
    if isinstance(entry, dict):
        normalized = _normalize_session_entry(entry)
        if normalized is not None and normalized != entry:
            _persist_session(token, normalized)
    return True


def get_session_info(cookie_value: str) -> dict | None:
    """Return session metadata (user_id, role, exp) for a valid cookie."""
    if not cookie_value or '.' not in cookie_value:
        return None
    token = _session_token_from_cookie_value(cookie_value)
    if not token:
        return None
    entry = _lookup_session(token)
    if entry is None:
        return None
    normalized = _normalize_session_entry(entry)
    if normalized is None:
        return None
    return normalized


def _session_token_from_cookie_value(cookie_value: str) -> str | None:
    """Return the raw server-side session token from a signed cookie value."""
    if not cookie_value or '.' not in cookie_value:
        return None
    token, _sig = cookie_value.rsplit('.', 1)
    return token or None


def csrf_token_for_session(cookie_value: str) -> str | None:
    """Return the CSRF token bound to an authenticated WebUI session.

    The browser can read this token from the authenticated shell and echoes it
    in ``X-Hermes-CSRF-Token`` on unsafe API requests. The token is derived
    from the HttpOnly session cookie's server-side token, so it automatically
    rotates on login and is invalidated when the auth session expires or logs
    out. Callers must still verify the auth session before trusting it.
    """
    token = _session_token_from_cookie_value(cookie_value)
    if not token:
        return None
    return hmac.new(_signing_key(), f"csrf:{token}".encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(cookie_value: str, csrf_token: str) -> bool:
    """Verify a submitted CSRF token against the authenticated session."""
    if not cookie_value or not csrf_token or not verify_session(cookie_value):
        return False
    expected = csrf_token_for_session(cookie_value)
    return bool(expected and hmac.compare_digest(str(csrf_token), expected))


def csrf_token_response_field(cookie_value: str | None) -> dict[str, str]:
    """Return ``csrf_token`` for auth JSON when the session cookie is valid."""
    if not cookie_value or not verify_session(cookie_value):
        return {}
    token = csrf_token_for_session(cookie_value)
    if not token:
        return {}
    return {"csrf_token": token}


def invalidate_session(cookie_value) -> None:
    """Remove a session token."""
    if cookie_value and '.' in cookie_value:
        token = cookie_value.rsplit('.', 1)[0]
        if token:
            _remove_session(token)


def get_session_entry(token: str | None) -> dict | None:
    """Return normalized session metadata for a raw opaque token."""
    if not token:
        return None
    return _lookup_session(token)


def parse_cookie(handler) -> str | None:
    """Extract the auth cookie from the request headers."""
    cookie_header = handler.headers.get('Cookie', '')
    if not cookie_header:
        return None
    return parse_cookie_value(cookie_header)


def parse_cookie_value(cookie_header: str) -> str | None:
    """Extract the auth cookie value from a raw Cookie header string."""
    if not cookie_header:
        return None
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(cookie_header)
    except http.cookies.CookieError:
        return None
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else None


def parse_bearer_authorization(authorization: str | None) -> str | None:
    """Extract the signed session token from an Authorization: Bearer header."""
    if not authorization:
        return None
    match = _BEARER_AUTH_RE.match(str(authorization).strip())
    if not match:
        return None
    return match.group(1) or None


def resolve_session_credential(
    *,
    cookie_header: str = "",
    authorization: str | None = None,
    cookie_value: str | None = None,
    query_token: str | None = None,
) -> str | None:
    """Return a valid signed session from cookie, Bearer Authorization, or query token."""
    candidates: list[str] = []
    if cookie_value:
        candidates.append(cookie_value)
    elif cookie_header:
        parsed = parse_cookie_value(cookie_header)
        if parsed:
            candidates.append(parsed)
    bearer = parse_bearer_authorization(authorization)
    if bearer:
        candidates.append(bearer)
    raw_query = str(query_token or "").strip()
    if raw_query:
        candidates.append(raw_query)
    for credential in candidates:
        if verify_session(credential):
            return credential
    return None


def resolve_session_credential_from_request(request) -> str | None:
    """Resolve an authenticated session credential from a Starlette/FastAPI request."""
    query_token = None
    try:
        query_params = getattr(request, "query_params", None)
        if query_params is not None:
            query_token = query_params.get("access_token") or query_params.get("token")
    except Exception:
        query_token = None
    return resolve_session_credential(
        cookie_value=request.cookies.get(COOKIE_NAME),
        cookie_header=request.headers.get("cookie", ""),
        authorization=request.headers.get("authorization"),
        query_token=query_token,
    )


def resolve_session_credential_from_handler(handler) -> str | None:
    """Resolve an authenticated session credential from a legacy handler shim."""
    return resolve_session_credential(
        cookie_header=handler.headers.get("Cookie", ""),
        authorization=handler.headers.get("Authorization"),
    )


def access_token_response_field(cookie_value: str | None) -> dict[str, str]:
    """Return bearer token fields for auth JSON when the session is valid."""
    if not cookie_value or not verify_session(cookie_value):
        return {}
    return {"access_token": cookie_value, "token_type": "bearer"}


def _live_role_for_session(user_id: str | None, session_role: str | None) -> str | None:
    """Prefer the current ``webui_users.role`` over stale session metadata."""
    from app.domain.users import LEGACY_ADMIN_USER_ID, get_user, is_multi_user_enabled

    if not user_id or user_id == LEGACY_ADMIN_USER_ID:
        return session_role or "admin"
    if not is_multi_user_enabled():
        return session_role
    record = get_user(str(user_id))
    if record is not None and record.role:
        return str(record.role).strip().lower()
    return session_role


def get_auth_status_payload(cookie_value: str | None = None) -> dict:
    """Return the JSON payload for GET /api/auth/status."""
    from app.domain.passkeys import registered_credentials
    from app.domain.users import is_multi_user_enabled

    logged_in = False
    user_id = None
    role = None
    auth_enabled = is_auth_enabled()
    if auth_enabled:
        logged_in = bool(cookie_value and verify_session(cookie_value))
        if logged_in:
            info = get_session_info(cookie_value or '')
            if info:
                user_id = info.get('user_id')
                role = info.get('role')
    passkey_flag = _passkey_feature_flag_enabled()
    passkeys = registered_credentials() if passkey_flag else []
    password_auth_enabled = get_password_hash() is not None
    multi_user = is_multi_user_enabled()
    if multi_user:
        password_auth_enabled = True
    payload = {
        "auth_enabled": auth_enabled,
        "logged_in": logged_in,
        "user_id": user_id,
        "role": role,
        "multi_user": multi_user,
        "password_auth_enabled": password_auth_enabled,
        "passwordless_enabled": bool(passkeys) and not password_auth_enabled,
        "passkeys_enabled": bool(passkeys),
        "passkeys_count": len(passkeys),
        "passkey_feature_flag": passkey_flag,
    }
    if logged_in:
        payload.update(csrf_token_response_field(cookie_value))
        if user_id:
            payload["email"] = user_id if user_id != "legacy" else None
        if multi_user and user_id and user_id != "legacy":
            from app.domain.users import get_user

            record = get_user(user_id)
            if record is not None:
                payload["email"] = record.email
                payload["role"] = _live_role_for_session(user_id, role)
                role = payload["role"]
                payload["profile_name"] = record.profile_name
                names = record.assigned_profile_names()
                if names:
                    payload["profile_names"] = list(names)
                if record.display_name:
                    payload["display_name"] = record.display_name
                if record.department:
                    payload["department"] = record.department
                if record.position:
                    payload["position"] = record.position
    if logged_in and role:
        from app.domain.roles import resolve_role_permissions

        payload["role"] = role
        payload["permissions"] = resolve_role_permissions(str(role))
    return payload


def check_auth(handler, parsed) -> bool:
    """Check if request is authorized. Returns True if OK.
    If not authorized, sends 401 (API) or 302 redirect (page) and returns False."""
    if not is_auth_enabled():
        return True
    # Public paths don't require auth
    if (
        parsed.path in PUBLIC_PATHS
        or parsed.path.startswith('/static/')
        or parsed.path.startswith('/session/static/')
        or parsed.path.startswith('/assets/')
        or parsed.path.startswith('/session/assets/')
    ):
        return True
    session_cred = resolve_session_credential_from_handler(handler)
    if session_cred:
        return True
    # Not authorized
    if parsed.path.startswith('/api/'):
        body = b'{"error":"Authentication required"}'
        handler.send_response(401)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    else:
        handler.send_response(302)
        # Pass the original path as ?next= so login.js redirects back after auth.
        # SECURITY/CORRECTNESS: the inner `?` and `&` MUST be percent-encoded
        # when stuffed into the outer `?next=` parameter, otherwise:
        #   (a) multi-param query strings get truncated at the first inner `&`
        #       (e.g. `/api/sessions?limit=50&offset=0` would round-trip as
        #       just `/api/sessions?limit=50` after the browser parses the
        #       outer URL — `offset=0` becomes a separate top-level query
        #       parameter that the login page ignores).
        #   (b) attacker-controlled paths could inject a second `next=`
        #       parameter; per RFC 3986 the duplicate behaviour is undefined
        #       and parsers diverge (Python's parse_qs returns last-match,
        #       URLSearchParams returns first-match), opening a query-pollution
        #       footgun even though _safeNextPath() rejects most malicious
        #       shapes downstream.
        # Encoding the entire `path?query` blob with quote(safe='/') turns
        # `?` → `%3F` and `&` → `%26`, so the outer parameter holds exactly
        # one path-with-query string and `searchParams.get('next')` returns
        # the full original URL (the browser auto-decodes once).
        # (Opus pre-release advisor finding for v0.50.258.)
        import urllib.parse as _urlparse
        _path_with_query = parsed.path or '/'
        if parsed.query:
            _path_with_query += '?' + parsed.query
        # safe='/' keeps path separators readable; everything else (including
        # `?`, `&`, `=`) gets percent-encoded.
        from app.core.security import spa_login_redirect_url

        handler.send_header('Location', spa_login_redirect_url(_path_with_query))
        handler.send_header('Content-Length', '0')
        handler.end_headers()
    return False


def _is_secure_context(handler=None) -> bool:
    """Return True if cookies should carry the Secure flag.

    Behaviour is overridable via HERMES_WEBUI_SECURE env var for
    reverse-proxy setups where TLS terminates at a frontend proxy
    (nginx, Cloudflare, etc.) and Python only sees plain HTTP.
    1/true/yes → force Secure on; 0/false/no → force Secure off.
    When unset, fall back to heuristics: direct TLS socket (getpeercert)
    or X-Forwarded-Proto header from the request.

    .. warning::
       The ``X-Forwarded-Proto`` header is only trustworthy when a
       reverse proxy (nginx, Cloudflare, etc.) is deployed in front
       of the application.  Without a proxy, any client can forge the
       header and cause the Secure flag to be set on plain HTTP.
    """
    env = os.getenv('HERMES_WEBUI_SECURE', '').strip().lower()
    if env in ('1', 'true', 'yes'):
        return True
    if env in ('0', 'false', 'no'):
        return False
    if handler is not None:
        req = getattr(handler, 'request', None)
        if req is not None:
            url = getattr(req, 'url', None)
            if url is not None and getattr(url, 'scheme', '') == 'http':
                return False
        if getattr(handler.request, 'getpeercert', None) is not None:
            return True
        if handler.headers.get('X-Forwarded-Proto', '') == 'https':
            return True
    return False


def set_auth_cookie(handler, cookie_value) -> None:
    """Set the auth cookie on the response."""
    cookie = http.cookies.SimpleCookie()
    cookie[COOKIE_NAME] = cookie_value
    cookie[COOKIE_NAME]['httponly'] = True
    cookie[COOKIE_NAME]['samesite'] = 'Lax'
    cookie[COOKIE_NAME]['path'] = '/'
    cookie[COOKIE_NAME]['max-age'] = str(_resolve_session_ttl())
    if _is_secure_context(handler):
        cookie[COOKIE_NAME]['secure'] = True
    handler.send_header('Set-Cookie', cookie[COOKIE_NAME].OutputString())


def clear_auth_cookie(handler) -> None:
    """Clear the auth cookie on the response."""
    cookie = http.cookies.SimpleCookie()
    cookie[COOKIE_NAME] = ''
    cookie[COOKIE_NAME]['httponly'] = True
    cookie[COOKIE_NAME]['path'] = '/'
    cookie[COOKIE_NAME]['max-age'] = '0'
    handler.send_header('Set-Cookie', cookie[COOKIE_NAME].OutputString())
