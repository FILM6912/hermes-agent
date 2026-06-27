# RFC: WebUI User / Admin System

- **Status:** Accepted
- **Author:** @FILM6912
- **Created:** 2026-05-29
- **Related:** `app/domain/auth.py`, `app/domain/passkeys.py`, `app/domain/profiles.py`,
  `app/middleware/security.py`

## Problem

Hermes WebUI today supports **one shared gate** for the whole instance: a single
`password_hash` in `settings.json`, optional installation-wide passkeys in
`passkeys.json`, and anonymous session cookies that do not identify a person.
Any authenticated browser can switch to any Hermes profile via the
`hermes_profile` cookie and see that profile's sessions, workspace, settings,
and provider credentials.

FILM needs a **multi-user WebUI account layer** on top of the existing
multi-profile Hermes Agent layout:

- **Admin** accounts can see and manage all profiles, all users, and all data.
- **Regular user** accounts are bound to **exactly one** Hermes profile
  (1 user : 1 profile). They must not switch into another user's profile or read
  another user's WebUI-scoped data.

This RFC defines the data model. Authorization rules live in Section 3;
implementation slices should not land without maintainer confirmation per
[`docs/rfcs/README.md`](README.md).

## Goals

- Introduce durable WebUI user records with `admin | user` roles.
- Enforce a strict 1:1 binding between `role=user` accounts and Hermes profile
  names at the storage layer.
- Preserve today's single-password behaviour when multi-user mode is off.
- Migrate existing installs without forcing a password reset on first boot.
- Reuse existing crypto, atomic-write, and session-cookie patterns from
  `app/domain/auth.py` and `app/domain/passkeys.py`.

## Non-goals

- Replacing Hermes Agent profile storage (`hermes_cli.profiles`, per-profile
  `config.yaml`, per-profile **`auth.json`** — provider OAuth/API keys).
- Per-user provider credential pools inside `{profile_home}/auth.json`.
- External identity providers (OAuth login, LDAP, SSO).
- Fine-grained RBAC beyond `admin | user`.

---

## 1. Current state

### WebUI login (instance gate)

| Artifact | Path | Purpose |
|---|---|---|
| `settings.json` | `{STATE_DIR}/settings.json` | UI prefs + optional `password_hash` (PBKDF2-SHA256, 600k iter) |
| `passkeys.json` | `{STATE_DIR}/passkeys.json` | WebAuthn credentials for passwordless login |
| `.sessions.json` | `{STATE_DIR}/.sessions.json` | Opaque session token → expiry timestamp |
| `.pbkdf2_key`, `.signing_key` | `{STATE_DIR}/` | Per-installation secrets for hashing + cookie signing |

`STATE_DIR` resolves from `HERMES_WEBUI_STATE_DIR` (default
`{HERMES_HOME}/webui`). See `app/domain/config.py` lines 79–86.

Auth flow today:

1. `AuthGateMiddleware` (`app/middleware/security.py`) calls
   `check_auth_request()` before API/page handlers run.
2. `POST /api/v1/auth/login` accepts `{ "password": "..." }` only — no username.
3. Successful login sets HttpOnly `hermes_session` cookie; CSRF token is derived
   from the session token (`csrf_token_for_session()` in `app/domain/auth.py`).
4. When `password_hash` is absent and no passkeys are registered, auth is fully
   disabled (`is_auth_enabled()` returns False).

Passkeys are **installation-wide**, not tied to a user identity. Any registered
passkey unlocks the same global gate.

### Profile context (Hermes Agent scope)

| Mechanism | Location | Purpose |
|---|---|---|
| Profile list | `hermes_cli.profiles` via `app/domain/profiles.py` | Named Hermes homes under `{HERMES_HOME}/profiles/<name>/` or root layout |
| Active profile cookie | `hermes_profile` | Per-browser profile selection |
| Request context | `ProfileContextMiddleware` + `contextvars` | Propagates profile into sync FastAPI handlers |

There is **no linkage** between WebUI login identity and profile choice. After
login, any user can POST `/api/v1/profile/switch` to any known profile.

### `auth.json` (do not confuse with WebUI login)

Per-profile **`auth.json`** lives at `{profile_hermes_home}/auth.json` and
stores **provider credentials** (OAuth tokens, API keys, `credential_pool`).
Example shape used in tests:

```json
{
  "providers": {},
  "credential_pool": {
    "openai-codex": [{ "...": "..." }]
  }
}
```

WebUI user accounts are **not** stored here. The user/admin system adds a new
store under `STATE_DIR`; it does not relocate or merge with provider
`auth.json`.

### Extension feasibility

Multi-user fits naturally:

- User records → new `{STATE_DIR}/users.json` (same durability patterns as
  `passkeys.json`).
- Session cookies → extend `.sessions.json` values with `user_id`, `role`, and
  `profile_name`.
- Profile middleware → override or validate `hermes_profile` against the
  logged-in user's binding (Section 3).

Legacy mode remains when `users.json` is absent and
`HERMES_WEBUI_MULTI_USER` is not enabled.

---

## 2. Data model

### 2.1 Design decision: storage location

**Chosen:** `{STATE_DIR}/users.json`

| Option | Verdict |
|---|---|
| `{STATE_DIR}/users.json` | **Selected.** WebUI auth artifacts already live here (`settings.json`, `passkeys.json`, `.sessions.json`). User accounts are an instance-level concern, not per Hermes profile. |
| `{HERMES_HOME}/users.json` | Rejected. Blurs WebUI identity with agent runtime home; breaks when `HERMES_HOME` and `HERMES_WEBUI_STATE_DIR` diverge (Docker, isolated trials). |
| Per-profile file | Rejected. Admins must enumerate all users from one place; 1:1 binding is a cross-profile constraint. |

Directory layout after multi-user enable:

```text
{STATE_DIR}/
  settings.json          # UI prefs (password_hash deprecated in multi-user mode)
  users.json             # NEW — WebUI user registry
  passkeys.json          # extended with user_id on each credential
  .sessions.json         # extended session payload (see §2.4)
  .pbkdf2_key            # unchanged — still used for password hashing
  .signing_key           # unchanged — still used for cookie + CSRF signing
  sessions/              # WebUI chat session sidecars (scoped by profile at runtime)
```

### 2.2 Top-level `users.json` schema

Atomic write pattern matches `app/domain/passkeys.py::_atomic_write_json`
(temp file + `os.chmod(0o600)` + `os.replace`).

```json
{
  "version": 1,
  "updated_at": 1748486400.0,
  "users": [],
  "profile_bindings": {}
}
```

| Field | Type | Description |
|---|---|---|
| `version` | `int` | Schema version. Start at `1`. Bump only on breaking on-disk changes. |
| `updated_at` | `float` | Unix epoch seconds of last successful write. |
| `users` | `User[]` | Ordered list of user records (source of truth). |
| `profile_bindings` | `object` | Denormalized index: `{ "<profile_name>": "<user_id>" }` for O(1) 1:1 enforcement. Maintained atomically with every user CRUD op. |

**Invariants (repository must enforce):**

1. `username` is unique case-insensitively across `users`.
2. For `role == "user"`: `profile_name` is required, must match
   `^[a-z0-9][a-z0-9_-]{0,63}$` (same rule as `app/domain/profiles.py`), and
   must exist in `hermes_cli.list_profiles()` at creation time.
3. For `role == "admin"`: `profile_name` must be `null`. Admins are not bound
   to a single profile.
4. `profile_bindings` contains exactly one entry per `role=user` account, and
   no profile name appears twice.
5. At most one admin bootstrap path may create the initial admin when the file
   is first materialized (see §2.6).

### 2.3 `User` record

**Shipped v1** uses `username` as the map key in `users.json` (no separate UUID
column). Future versions may add `id` if audit or federation requires it.

```json
{
  "username": "film",
  "password_hash": "a1b2c3…",
  "role": "user",
  "profile_name": "user1",
  "created_at": 1748486400.0,
  "updated_at": 1748486400.0
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | `string` | yes | Primary key and login identifier. 3–32 chars; `[a-z][a-z0-9_-]{2,31}` (`app/schemas/users.py`). |
| `password_hash` | `string \| null` | no* | Hex PBKDF2-SHA256 digest using installation `.pbkdf2_key` — **same algorithm and format** as `settings.json` today (`app/domain/auth.py::_hash_password`). `null` when the account is passkey-only. |
| `role` | `"admin" \| "user"` | yes | Authorization tier (Section 3). |
| `profile_name` | `string \| null` | conditional | Required non-null for `role=user`. Must be `null` for `role=admin`. |
| `created_at` | `float` | yes | Unix epoch seconds. |
| `updated_at` | `float` | yes | Unix epoch seconds; bump on any mutation. |

\* `password_hash` is required at account creation in v1. Per-user passkeys and
`disabled_at` soft-disable are deferred (see §2.10, §4).

**Password hashing:** Reuse `_hash_password()` from `app/domain/auth.py`. Do not
introduce a second hash format. Migration from `settings.json` copies the
existing hex digest verbatim — no re-hash required.

**Passkey references:** Credentials remain in `passkeys.json` (public key
material stays co-located). Each credential gains a `user_id` field:

```json
[
  {
    "id": "cred-id-base64url",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "label": "MacBook Touch ID",
    "public_key_pem": "-----BEGIN PUBLIC KEY-----…",
    "sign_count": 0,
    "created_at": 1748486400.0,
    "last_used_at": null
  }
]
```

`User.passkey_ids` is the canonical membership list; credential lookup verifies
`credential.user_id == user.id` to prevent orphaned cross-user login.

### 2.4 Session payload extension (`.sessions.json`)

**Today** (`app/domain/auth.py`):

```json
{
  "a1b2c3…tokenhex64": 1748486400.0
}
```

**Multi-user mode** — values are objects; legacy float values remain valid
during rollout:

```json
{
  "a1b2c3…tokenhex64": {
    "exp": 1748486400.0,
    "user_id": "film",
    "role": "user"
  }
}
```

| Field | Description |
|---|---|
| `exp` | Expiry unix timestamp (replaces bare float). |
| `user_id` | **Username** (map key in `users.json`). |
| `role` | `admin` or `user`. |

`profile_name` is resolved from `users.json` via `{STATE_DIR}/.session_users.json`
(token → username), not stored in `.sessions.json` in v1.

`create_session(user_id=..., role=...)` persists the object above.
`get_session_info()` returns `{exp, user_id, role}` for `/api/v1/auth/status`.
`CurrentUser` in `app/core/security.py` loads `profile_name` through
`resolve_request_user_access()`.

**Legacy session interpretation:** If value is a bare float (no `user_id`), treat
as an implicit **legacy admin** session only while `users.json` is absent.
Once `users.json` exists, bare-float sessions should be rejected (forced
re-login) to avoid privilege ambiguity.

### 2.5 Mode detection

```python
def is_multi_user_enabled() -> bool:
    # 1. Explicit env opt-in
    if env_flag("HERMES_WEBUI_MULTI_USER"):
        return True
    # 2. Materialized user store
    if (STATE_DIR / "users.json").exists():
        return True
    return False
```

| Mode | Condition | Behaviour |
|---|---|---|
| **Legacy** | `not is_multi_user_enabled()` | Identical to today: `settings.json` `password_hash`, global passkeys, no username, no profile binding enforcement. |
| **Multi-user** | `is_multi_user_enabled()` | Login requires username (+ password or passkey). Authorization uses session `role` + `profile_name`. `settings.json` `password_hash` is ignored for login (may remain on disk until admin removes it). |

### 2.6 Migration from single-password auth

Migration runs **once**, idempotently, when multi-user mode activates and
`users.json` is missing.

```text
┌─────────────────────────────────────────────────────────────────┐
│ First boot with HERMES_WEBUI_MULTI_USER=1 OR admin runs promote │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
                    users.json exists?
                         /        \
                       yes         no
                        │           │
                   skip mig.        ▼
                          ┌─────────────────────┐
                          │ Create bootstrap     │
                          │ admin user record    │
                          └─────────┬───────────┘
                                    ▼
              ┌─────────────────────────────────────────────┐
              │ Source priority for bootstrap admin:         │
              │ 1. HERMES_WEBUI_ADMIN_USER +                 │
              │    HERMES_WEBUI_ADMIN_PASSWORD (env)         │
              │ 2. Else existing settings.json password_hash │
              │    → username "admin", hash copied verbatim  │
              │ 3. Else existing passkeys only → admin with│
              │    passkey_ids migrated, password_hash null  │
              └─────────────────────┬───────────────────────┘
                                    ▼
              ┌─────────────────────────────────────────────┐
              │ Move passkeys.json credentials → set user_id │
              │ on bootstrap admin; populate passkey_ids   │
              └─────────────────────┬───────────────────────┘
                                    ▼
              ┌─────────────────────────────────────────────┐
              │ Write users.json (0600), log username only   │
              │ (never log password or hash)                 │
              └─────────────────────┬───────────────────────┘
                                    ▼
              Optional: POST /api/v1/admin/users to create
              role=user accounts with profile_name bindings
```

**Bootstrap admin defaults:**

| Env var | Default | Notes |
|---|---|---|
| `HERMES_WEBUI_MULTI_USER` | `0` | Set `1` to opt in before first `users.json`. |
| `HERMES_WEBUI_ADMIN_USER` | `admin` | Bootstrap username only when creating `users.json`. |
| `HERMES_WEBUI_ADMIN_PASSWORD` | *(required on fresh install)* | If unset and no legacy `password_hash`, startup fails closed with a clear log message. Never printed. |

**Promoting an existing install without env password:** Ship a one-shot CLI or
admin-only endpoint `POST /api/v1/admin/migrate` that performs the same steps
using the currently configured password gate — callable only when authenticated
under legacy mode.

**Regular user onboarding:** Admin creates users via admin API (§2.7). For
`role=user`, the admin supplies `username`, `password` (or defers passkey reg),
and `profile_name`. The repository rejects duplicate profile bindings before
writing.

### 2.7 API shape sketches

All paths use the canonical `/api/v1/` prefix. Shapes are illustrative; final
Pydantic models live in `app/schemas/users.py`.

#### Auth (extended)

```http
GET /api/v1/auth/status
```

```json
{
  "auth_enabled": true,
  "logged_in": true,
  "multi_user": true,
  "user_id": "film",
  "role": "user",
  "password_auth_enabled": true,
  "passkeys_enabled": false,
  "passkeys_count": 0,
  "passkey_feature_flag": false,
  "passwordless_enabled": false
}
```

When `logged_in=false`, `user_id` and `role` are null. Login success may also
return `profile_name` in the POST body; the UI reads role from status for gating.

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "username": "film", "password": "secret" }
```

Legacy mode (unchanged):

```json
{ "password": "secret" }
```

Success `200`:

```json
{
  "ok": true,
  "user_id": "film",
  "role": "user",
  "profile_name": "user1"
}
```

Sets `hermes_session` cookie as today. For `role=user`, also sets
`hermes_profile` cookie to `profile_name` on login.

Passkey login (`POST /api/v1/auth/passkey/login`) unchanged wire format; server
resolves credential → `user_id` → issues session with full payload.

#### Admin user CRUD

Requires `role=admin` session. All responses strip `password_hash`.

```http
GET /api/v1/admin/users
→ 200 { "users": [ { "username", "role", "profile_name", "created_at" } ] }
```

```http
POST /api/v1/admin/users
Content-Type: application/json

{
  "username": "bob",
  "password": "initial-secret",
  "role": "user",
  "profile_name": "user2"
}
```

→ `201` created user (no hash in response)

Errors:

| Status | Condition |
|---|---|
| `409` | Username taken, or `profile_name` already bound to another user |
| `422` | `role=user` without `profile_name`, or invalid profile name |
| `403` | Caller is not admin |

```http
GET /api/v1/admin/users/{username}
PATCH /api/v1/admin/users/{username}
DELETE /api/v1/admin/users/{username}
```

`PATCH` allowed fields: `password`, `role`, `profile_name`. Changing `role` from
`user` → `admin` clears `profile_name` and removes `profile_bindings` entry.
Changing `role` from `admin` → `user` requires explicit `profile_name`.

Per-user passkey reassignment (`POST …/passkeys/reassign`) is deferred to a
follow-up slice.

#### Profile endpoints (behaviour change, same paths)

```http
GET /api/v1/profiles
```

- **Admin:** full profile list (unchanged).
- **User:** `200 { "profiles": [ { "name": "user1", … } ] }` — singleton array
  containing only the bound profile.

```http
POST /api/v1/profile/switch
{ "profile": "other" }
```

- **Admin:** unchanged.
- **User:** `403` unless `"other" == session.profile_name`.

```http
POST /api/v1/profiles
```

- **Admin only.** Users receive `403`.

#### Data scoping (read paths)

No new endpoints required for v1; existing routes gain server-side filters:

| Endpoint family | Admin | User (`profile_name = P`) |
|---|---|---|
| `GET /api/v1/sessions` | All profiles (optional `?profile=` filter) | Sessions where `session.profile == P` only |
| Workspace / files | All profiles | Profile `P` workspace only |
| `GET /api/v1/settings` | Active or requested profile | Profile `P` only |
| Cron, kanban, memory | All profiles | Profile `P` only |

Implementation reads `SessionContext` from verified cookie rather than trusting
client-supplied profile cookies alone (Section 3).

### 2.8 Repository interface

Proposed module split (mirrors `app/repositories/auth.py`):

```python
# app/repositories/users.py
class UsersRepository:
    def load_store() -> UsersStore: ...
    def get_by_id(user_id: str) -> User | None: ...
    def get_by_username(username: str) -> User | None: ...
    def list_users() -> list[User]: ...
    def create_user(*, username, password, role, profile_name) -> User: ...
    def update_user(user_id: str, **fields) -> User: ...
    def delete_user(user_id: str) -> None: ...
    def verify_password(user: User, plain: str) -> bool: ...
    def bind_passkey(user_id: str, credential_id: str) -> None: ...
    def unbind_passkey(user_id: str, credential_id: str) -> None: ...
    def assert_profile_available(profile_name: str, except_user_id: str | None = None) -> None: ...
```

Domain helpers in `app/domain/users.py`:

- `is_multi_user_enabled()`
- `migrate_legacy_auth_if_needed()`
- `session_context_from_cookie(cookie: str) -> SessionContext | None`

### 2.9 Entity relationship summary

```text
┌─────────────────────┐         ┌──────────────────────┐
│ users.json          │         │ passkeys.json        │
│  User               │1      * │  Credential          │
│  - id               │─────────│  - id                │
│  - passkey_ids[]    │         │  - user_id (FK)      │
│  - profile_name ────┼──┐      └──────────────────────┘
└─────────────────────┘  │
           │               │  profile_bindings{}
           │               └──────────────────────────┐
           │                                          ▼
           │                              ┌───────────────────────┐
           │                              │ Hermes profile (agent) │
           │                              │  {HERMES_HOME}/…       │
           │                              │  config.yaml           │
           │                              │  auth.json (providers) │
           │                              │  workspace/<name>/     │
           │                              └───────────────────────┘
           │
           ▼
┌─────────────────────┐
│ .sessions.json      │
│  token → {          │
│    user_id, role,   │
│    profile_name, exp│
│  }                  │
└─────────────────────┘
```

### 2.10 Open questions

1. **Username vs email:** v1 uses short usernames only. Email-as-login deferred.
2. **Self-service password reset:** admin-only in v1; no mailer dependency.
3. **SQLite backend:** JSON is sufficient for homelab-scale (<100 users). Revisit
   if admin audit logs or large teams require querying.
4. **Delete user with active sessions:** v1 — soft-disable (`disabled_at`);
   hard delete admin-only and requires no active sessions.

---

## 3. Authorization

Authorization defines **what an authenticated principal may do** after
`AuthGateMiddleware` has verified the `hermes_session` cookie. Authentication
(password, passkey, session validity) stays in `app/domain/auth.py`.
Authorization is enforced at three layers:

1. **Middleware** — cheap cross-cutting gates (session context attachment,
   profile cookie validation against session binding).
2. **FastAPI `Depends()`** — route-level role and resource checks on native
   `/api/v1/*` handlers.
3. **Service/repository guards** — final enforcement before filesystem or state
   mutation (defense in depth for legacy bridges).

When `is_multi_user_enabled()` is false, all authorization checks are no-ops
(legacy single-operator behaviour). When auth is fully disabled
(`is_auth_enabled() == False`), middleware and Depends stubs skip as today.

### 3.1 Architecture decision: session cookie extension, not JWT

Section 2.4 already extends `.sessions.json` with `{user_id, role, profile_name,
exp}`. This section **confirms that choice** for browser authorization and
defers JWT/bearer tokens.

| Approach | Verdict |
|---|---|
| **Extend server-side session cookie** | **Selected.** Reuses `hermes_session` HttpOnly cookie, `.sessions.json` revocation, and `csrf_token_for_session()` HMAC binding (`app/domain/auth.py`). Login rotates token → CSRF rotates automatically. |
| **JWT in `Authorization` header** | **Rejected for v1 browser UI.** Would need parallel CSRF strategy, complicate logout/revocation, and duplicate the session store the shell already depends on. |
| **JWT for MCP/automation clients** | **Deferred.** A follow-up RFC may add per-user opaque API keys or short-lived tokens for non-browser callers. Out of scope here. |

CSRF (`CsrfMiddleware`, `app/domain/routes.py::_check_csrf`) is **unchanged**:
session-bound `X-Hermes-CSRF-Token` continues to derive from the raw session
token, independent of `user_id` or `role`. Role elevation requires a new login
(new token → new CSRF).

### 3.2 Permission matrix: admin vs user

Legend: **All** = unrestricted within the deployment; **Own** = scoped to the
user's bound profile `P = session.profile_name`; **None** = denied (`403`);
**Read/Write** as labeled.

| Surface | Admin | Regular user (`role=user`, profile `P`) | Notes |
|---|---|---|---|
| **Profiles — list** (`GET /api/v1/profiles`) | All profiles | Singleton `[P]` only | User must not enumerate other profile names. |
| **Profiles — switch** (`POST /api/v1/profile/switch`, `hermes_profile` cookie) | Any profile | `P` only; `403` otherwise | Login auto-sets cookie to `P` (§2.7). Middleware rejects foreign cookies. |
| **Profiles — create/delete/sync** | Write (all) | None | Admin-only (§2.7). |
| **Sessions — list/read** | All profiles; optional `?profile=` filter | `session.profile == P` only | Server-side filter; ignore `?all_profiles=1` for users (#1611 lesson). |
| **Sessions — mutate** (rename, delete, move, chat, stream) | All profiles | Profile `P` only | Stream workers must pin `profile=P` (#2762). |
| **Workspace files** (list, read, write, upload, reveal) | Active profile tree (any switch) | Profile `P` workspace only | `safe_resolve()` under profile home unchanged. |
| **Settings — personal UI prefs** | Write | Write (own account) | Stored per-user in WebUI state, not per Hermes profile. |
| **Settings — profile/agent config** (`config.yaml`, models, providers, `.env`) | Write any profile | Write profile `P` only | Provider secrets stay in `{profile_home}/auth.json`. |
| **Settings — auth / users / passkeys admin** | Write | None (own passkey register/login only) | User cannot create accounts or change roles. |
| **Settings — system** (shutdown, session TTL, feature flags) | Write | None | `/api/v1/system/shutdown` admin-only. |
| **Cron jobs** | All profiles | Profile `P` only | Grant check before `cron_profile_context()` env swap. |
| **Skills / memory / kanban / notes / projects** | Active profile scope | Profile `P` only | Same rule as workspace. |
| **Other users' data** (user list, grants, foreign sessions) | Read/write via admin API | None | `GET/POST/PATCH/DELETE /api/v1/admin/users*` admin-only. |
| **Onboarding / OAuth** | Any profile | Profile `P` only | Token persistence stays profile-scoped. |
| **SSE / session events** | All (optional profile filter) | Profile `P` only | Event bus payload should include `profile` for client-side filter (#2637). |

**Admin profile switching:** Admins may set `hermes_profile` to any known profile.
Authorization reads **session role**, not the cookie alone — a user cannot
escalate by forging a cookie if middleware validates against
`session.profile_name`.

**Default profile (`default`):** Users access it only when explicitly bound
to `default` in `users.json`. No implicit grant.

### 3.3 Integration points

#### 3.3.1 `AuthGateMiddleware` (`app/middleware/security.py`)

**Today:** `check_auth_request()` → valid `hermes_session` or 401/redirect.

**Multi-user extension:**

1. After `verify_session()`, load structured session payload via
   `session_context_from_cookie()` (`app/domain/users.py`, §2.8).
2. Attach `SessionContext` to `request.state.session`.
3. If `users.json` exists and payload is legacy bare-float, reject session
   (forced re-login per §2.4).
4. If user record has `disabled_at`, reject session (401, clear cookie).

Do **not** enforce profile scope here — profile checks need the
`hermes_profile` cookie parsed in the next middleware.

#### 3.3.2 `ProfileContextMiddleware` (`app/middleware/security.py`)

**Today:** `get_profile_cookie()` → `set_request_profile(name)` in ContextVar.

**Multi-user extension:**

```python
profile = get_profile_cookie(request)
session = getattr(request.state, "session", None)

if is_multi_user_enabled() and session is not None:
    if session.role == "user":
        # Fail closed: user sessions are pinned to profile_name
        if profile and profile != session.profile_name:
            return 403  # /api/* JSON; clear cookie on page routes
        profile = session.profile_name  # ignore client cookie drift
    elif session.role == "admin":
        # Admin: cookie selects active profile; validate name exists
        if profile and not profile_exists(profile):
            return 403

if profile:
    set_request_profile(profile)
```

Middleware stack order in `app/main.py` (LIFO): `AuthGateMiddleware` is
registered after `ProfileContextMiddleware`, so **auth runs before profile
context** — keep this order.

ContextVar propagation (`app/domain/profiles.py`) is unchanged; only the
**allowed profile set** becomes role-dependent.

#### 3.3.3 CSRF (`CsrfMiddleware`, `_check_csrf`)

No mechanism change. Implications:

- CSRF token remains bound to session token, not username.
- Exempt paths (`/api/auth/login`, `/api/csp-report`) unchanged.
- Non-browser callers without Origin/Referer continue to bypass token check.

#### 3.3.4 Cookie session (`app/domain/auth.py`)

| Function | Multi-user change |
|---|---|
| `create_session(user: User \| None)` | When multi-user: persist §2.4 object. Legacy: bare float expiry. |
| `verify_session()` | Accept both shapes during rollout. |
| `get_session_context(token)` | New — returns `SessionContext \| None`. |
| `csrf_token_for_session()` | Unchanged — uses raw token only. |
| `logout()` | Unchanged — delete token entry. |

Typed context (shared with §2.8):

```python
@dataclass(frozen=True)
class SessionContext:
    token: str
    exp: float
    user_id: str | None      # None in legacy mode
    username: str | None
    role: Literal["admin", "user"] | None
    profile_name: str | None  # None for admin
```

#### 3.3.5 FastAPI `Depends()` pattern (`app/api/dependencies.py`)

**Implemented** in `app/core/security.py` and wired through
`app/api/dependencies.py` (`CurrentUserDep`, `AdminUserDep`). Legacy
`app/domain/routes.py` handlers should call the same helpers until
decommissioned.

```python
# app/api/dependencies.py (reference — see app/core/security.py for source)

@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    username: str
    role: Literal["admin", "user"]
    profile_name: str | None

async def get_session_context(request: Request) -> SessionContext | None:
    """Read request.state.session set by AuthGateMiddleware."""
    ...

async def require_user(
    session: Annotated[SessionContext | None, Depends(get_session_context)],
) -> CurrentUser:
    """401 when multi-user enabled and no valid user session."""
    if not is_multi_user_enabled():
        raise _LegacyOperator()  # sentinel: authorization no-op downstream
    if session is None or session.user_id is None:
        raise HTTPException(401, "Authentication required")
    return CurrentUser(...)

async def require_admin(
    user: Annotated[CurrentUser, Depends(require_user)],
) -> CurrentUser:
    if not is_multi_user_enabled():
        return user  # legacy: single operator is implicit admin
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user

async def require_profile_access(
    user: Annotated[CurrentUser, Depends(require_user)],
) -> str:
    """Return authorized active profile name; 403 if user cannot access it."""
    active = get_active_profile_name()  # ContextVar from middleware
    if is_multi_user_enabled() and user.role == "user":
        if active != user.profile_name:
            raise HTTPException(403, "Profile access denied")
    return active

# Type aliases for route signatures
AdminUser = Annotated[CurrentUser, Depends(require_admin)]
AuthenticatedUser = Annotated[CurrentUser, Depends(require_user)]
AuthorizedProfile = Annotated[str, Depends(require_profile_access)]
```

**Route examples** (align with §2.7):

```python
@router.get("/profiles")
def list_profiles(user: AuthenticatedUser) -> ProfileListResponse:
    return _service.list_profiles_for_user(user)

@router.post("/profile/switch")
def switch_profile(user: AuthenticatedUser, body: ProfileSwitchRequest) -> ...:
    _service.assert_can_switch(user, body.name)  # 403 for user ≠ bound profile
    ...

@router.get("/admin/users")
def list_users(_: AdminUser) -> UserListResponse:
    ...
```

**Legacy bridge:** `app/domain/authorization.py` (new) exports
`assert_admin(ctx)`, `assert_profile_access(ctx, profile)`, and
`list_profiles_for_session(ctx)` for sync handlers in `app/domain/routes.py`.
Same rules as `Depends()` — no duplicated matrix.

**Exception mapping:** reuse `HTTPException` handler in `app/main.py` →
`{"error": "...", "detail": "..."}`.

#### 3.3.6 Service layer guards

| Module | Guard |
|---|---|
| `ProfileService` | Filter list; block create/delete/sync for non-admin. |
| `SessionService` | Filter by `profile_name`; strip `all_profiles` for users. |
| `WorkspaceService` / file ops | Assert active profile authorized. |
| `SettingsService` | Split system vs personal vs profile-scoped keys. |
| `CronService` | Grant check inside `cron_profile_context()`. |
| `UserService` | Admin-only CRUD; enforce `profile_bindings` invariants (§2.2). |

### 3.4 Request flow (multi-user, authenticated)

```text
Browser request
  │
  ├─ Cookies: hermes_session, hermes_profile
  │
  ▼
AuthGateMiddleware
  ├─ verify_session(hermes_session)
  ├─ load SessionContext → request.state.session
  ├─ reject disabled user / legacy float when users.json exists
  └─ 401 if auth enabled and invalid
  │
  ▼
ProfileContextMiddleware
  ├─ parse hermes_profile cookie
  ├─ role=user → force profile = session.profile_name
  ├─ role=admin → accept cookie if profile exists
  ├─ set_request_profile(name) in ContextVar
  └─ 403 if profile not authorized
  │
  ▼
CsrfMiddleware (POST/PUT/PATCH/DELETE on /api/*)
  └─ verify X-Hermes-CSRF-Token vs session token
  │
  ▼
FastAPI route
  ├─ Depends(require_user | require_admin | require_profile_access)
  └─ Service guard before filesystem / DB mutation
  │
  ▼
Response
```

### 3.5 Error semantics

| Condition | Status | Body |
|---|---|---|
| Auth enabled, no session | 401 | `{"error": "Authentication required"}` |
| Valid session, insufficient role | 403 | `{"error": "Admin access required"}` |
| Valid session, profile not granted | 403 | `{"error": "Profile access denied"}` |
| Disabled user | 401 | `{"error": "Account disabled"}` |
| Legacy mode / auth disabled | — | Authorization skipped |

Frontend gates: hide admin panels when `GET /api/v1/auth/status` reports
`role != "admin"`. Profile switcher for users is read-only (shows bound
profile only).

### 3.6 Non-goals (authorization slice)

- OAuth/OIDC / LDAP / SSO federation.
- Fine-grained RBAC beyond `admin | user`.
- Row-level session sharing across users.
- JWT access tokens for browser UI.
- Client-side-only authorization (server always enforces).

### 3.7 Open questions

1. **Admin impersonation:** Should admin "view as user" be explicit (audit log)
   or only via profile switch? **Recommendation:** profile switch only; no
   silent impersonation in v1.
2. **Concurrent admin + user sessions:** Same browser, two tabs — session is
   one; profile cookie is per-browser. No change from today.
3. **MCP bearer auth:** Defer; MCP today assumes shared instance gate.

### 3.8 Rollout plan (authorization slice)

1. Add `app/domain/authorization.py` + unit tests for matrix rows.
2. Extend `create_session()` / `verify_session()` payload (§2.4).
3. Wire `AuthGateMiddleware` + `ProfileContextMiddleware` extensions.
4. Expand `app/api/dependencies.py`; protect native v1 routes by category.
5. Bridge legacy handlers via shared assert helpers.
6. Extend `/auth/status` + frontend admin gates.
7. Regression tests: user A cannot list/switch/read user B profile; admin can;
   legacy + CSRF modes unchanged.

---

## 4. Implementation status (2026-05-29)

| Slice | Status | Notes |
|---|---|---|
| `users.json` storage + CRUD | **Shipped** | `app/domain/users.py`, `app/repositories/users.py`, `app/services/users.py` |
| `/api/v1/admin/users*` | **Shipped** | `app/api/v1/endpoints/admin.py`; path param is `username` |
| Session `user_id` + `role` | **Shipped** | `.sessions.json` objects; `.session_users.json` sidecar |
| `GET /api/v1/auth/status` fields | **Shipped** | Flat `user_id`, `role`, `multi_user` (`app/schemas/auth.py`) |
| `CurrentUser` / `AdminUserDep` | **Shipped** | `app/core/security.py`, `app/api/dependencies.py` |
| Profile switch/list scoping | **In progress** | See workers / `app/services/profiles.py` |
| Session + workspace data scoping | **In progress** | Admin sees all; user sees bound profile only |
| Admin UI (Users panel) | **In progress** | `static/panels.js` |
| Bootstrap admin on first start | **In progress** | `HERMES_WEBUI_ADMIN_*`, `app/core/startup.py`, `scripts/promote_multi_user_admin.py` |
| Per-user passkeys, `disabled_at` | **Deferred** | Installation-wide passkeys unchanged in v1 |

Public contract index: [`docs/CONTRACTS.md`](../CONTRACTS.md) (multi-user
section). Contributor routing for this feature: read this RFC before editing
auth, profiles, sessions, or admin routes.

