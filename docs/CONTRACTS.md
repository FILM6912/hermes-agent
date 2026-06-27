# Project Contracts

This document is a contributor-facing index for existing Hermes WebUI contracts,
RFCs, design constraints, and review expectations. It does not replace the
source documents and it does not mark proposals as implemented. Follow each
linked document's status and scope.

Use this file when starting a change so the relevant public contract is visible
before code is edited. This first version focuses on documentation routing; it
does not change runtime behavior, maintainer policy, bot behavior, or CI gates.

## Start here

- [`AGENTS.md`](../AGENTS.md): repository entry point for AI assistants,
  public-safety rules, and the short redline checklist.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md): contribution style, verification,
  PR description expectations, UI evidence, and project-specific constraints.
- [`README.md`](../README.md): product overview, quick start, architecture map,
  feature inventory, and docs index.
- [`CHANGELOG.md`](../CHANGELOG.md): release-note-ready history. Update it when
  maintainers should carry the change into release notes.

## HTTP API prefix

- **Canonical:** versioned REST paths use the `/api/v1/` prefix (for example
  `/api/v1/sessions`, `/api/v1/chat/start`). The bundled UI and new integrations
  must call only `/api/v1/*`.
- **Deprecated:** unversioned `/api/*` paths (without the `v1` segment). They
  existed as migration aliases to `app.domain.routes`. With `HERMES_WEBUI_LEGACY_API` off
  (the default after the FastAPI migration — see `docs/phase5-decommission.md`),
  `app/main.py` does not register `/api/*` or `/api/v1/*` catch-alls; unmatched
  API requests return **404**. Set `HERMES_WEBUI_LEGACY_API=1` only for emergency
  rollback.
- The frontend central `api()` helper in `static/workspace.js` and direct
  fetch/EventSource callers apply the `/api/v1/` prefix automatically; do not
  change `/static/*` asset paths.

## Multi-user authentication (optional)

Hermes WebUI defaults to a **single shared gate** (one `password_hash` in
`settings.json`, optional installation-wide passkeys). When **multi-user mode**
is active, the instance also maintains per-account records in
`{HERMES_WEBUI_STATE_DIR}/users.json` with `admin | user` roles and a strict
**1 user : 1 Hermes profile** binding for `role=user`.

Mode detection (see [`docs/rfcs/user-admin-system.md`](rfcs/user-admin-system.md)):

- **Legacy:** `HERMES_WEBUI_MULTI_USER` unset/off **and** `users.json` absent —
  behaviour unchanged (no username on login; implicit admin session).
- **Multi-user:** `HERMES_WEBUI_MULTI_USER=1` **or** `users.json` exists —
  login requires `username` + password; authorization uses session role and
  profile binding.

Environment variables (also in `README.md` and `.env.docker.example`):

| Variable | Purpose |
|---|---|
| `HERMES_WEBUI_MULTI_USER` | Opt in before first `users.json` (`1` / `true`). |
| `HERMES_WEBUI_ADMIN_USER` | **First-run only:** bootstrap admin username when creating `users.json` (default `admin`). Ignored once the file exists. |
| `HERMES_WEBUI_ADMIN_PASSWORD` | **First-run only:** bootstrap admin password on fresh install (never logged). Additional users are created via admin API/UI, not env. |

### Auth session shape

Browser auth continues to use the HttpOnly `hermes_session` signed cookie and
CSRF token derived from the opaque session token (`app/domain/auth.py`).

Server-side session store (`{STATE_DIR}/.sessions.json`):

```json
{
  "<token_hex>": {
    "exp": 1748486400.0,
    "user_id": "film",
    "role": "admin"
  }
}
```

- `user_id` holds the **username** (not a separate UUID) in the shipped schema.
- Legacy entries may still be bare float expiry timestamps; they are normalized
  to `{exp, user_id: "legacy", role: "admin"}` on read.
- Multi-user mode also maintains `{STATE_DIR}/.session_users.json` mapping
  session token → username for lookup of `profile_name` and account metadata.

`GET /api/v1/auth/status` (`AuthStatusResponse`) exposes:

| Field | When set |
|---|---|
| `auth_enabled`, `logged_in` | Always |
| `multi_user` | `true` when multi-user mode is active |
| `user_id`, `role` | When `logged_in` and session is valid (`admin` or `user`) |
| `password_auth_enabled`, passkey fields | As today |

`POST /api/v1/auth/login` accepts `{ "password": "..." }` in legacy mode and
`{ "username": "...", "password": "..." }` in multi-user mode. Success may
return `user_id`, `role`, and `profile_name` in the JSON body and sets
`hermes_session`. The same response also includes `access_token` and
`token_type: "bearer"` so API clients can call `/api/v1/*` with
`Authorization: Bearer <access_token>` instead of the cookie. Cookie and
Bearer refer to the same signed session; unsafe browser POSTs still require
CSRF when using the cookie, while valid Bearer auth skips CSRF.

Authorization for native FastAPI routes uses `CurrentUser` /
`AdminUserDep` (`app/core/security.py`, `app/api/dependencies.py`):
`require_admin()` for admin-only surfaces; non-admin users are pinned to
`profile_name` for profile switch, session list, and workspace scoping.

### Admin API (`/api/v1/admin/*`)

All routes require an authenticated **admin** session (`403` otherwise).
Responses never include `password_hash`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/users` | List all WebUI user accounts |
| `GET` | `/api/v1/admin/users/{username}` | User detail, bound profile, session count summary |
| `POST` | `/api/v1/admin/users` | Create user (`username`, `password`, `role`, `profile_name` for `role=user`) |
| `PATCH` | `/api/v1/admin/users/{username}` | Update `role`, `profile_name`, and/or `password` |
| `DELETE` | `/api/v1/admin/users/{username}` | Remove user account |

Common errors: `401` unauthenticated, `403` non-admin, `404` unknown username,
`409` username or profile binding conflict, `422` validation (e.g. `role=user`
without `profile_name`).

Full data model, permission matrix, and rollout notes:
[`docs/rfcs/user-admin-system.md`](rfcs/user-admin-system.md).

## Runtime, durability, and state contracts

- [`docs/rfcs/webui-run-state-consistency-contract.md`](rfcs/webui-run-state-consistency-contract.md):
  proposed consistency rules for current WebUI streaming, recovery, replay,
  model-context reconstruction, compression, UI scene/cache, and sidebar metadata
  repairs. Start here for narrow fixes that keep the existing WebUI execution
  path.
- [`docs/rfcs/canonical-session-resolution.md`](rfcs/canonical-session-resolution.md):
  proposed contract for resolving URL routes, query parameters, localStorage,
  sidebar rows, and compression-lineage IDs to one canonical visible session
  target. Start here for session routing, boot restore, stale parent, or
  compression-tip selection changes.
- [`docs/rfcs/hermes-run-adapter-contract.md`](rfcs/hermes-run-adapter-contract.md):
  proposed event/control contract, runtime-state ownership matrix,
  acceptance-test catalog, and reversible migration gates for moving WebUI
  execution behind an adapter boundary. Use this for adapter-seam, control-plane,
  runner, sidecar, or execution-ownership work; do not treat it as authorization
  to implement those slices.
- [`docs/rfcs/turn-journal.md`](rfcs/turn-journal.md): proposed crash-safe
  write-ahead journal for browser-originated chat turns.
- [`docs/rfcs/README.md`](rfcs/README.md): RFC conventions and current RFC index.

When a change touches streaming, recovery, replay, compression, context
reconstruction, cancellation, approval/clarify, session metadata, or run state,
read the relevant RFC before editing. In the PR description, name the state layer
or event/control surface affected and include a regression test or manual
verification for the relevant invariant.

Proposed RFCs are review guardrails, not implementation authorization. Do not
implement RFC fragments unless the task or tracking issue explicitly asks for
that slice.

## UI, UX, and theme contracts

- [`DESIGN.md`](../DESIGN.md): design tokens and the current calm-console
  direction: conversation first, quiet metadata, restrained accents, and
  progressive disclosure for debugging detail.
- [`docs/UIUX-GUIDE.md`](UIUX-GUIDE.md): contributor-facing synthesis of the
  repository's UI/UX principles, sourced from existing project docs and code
  comments.
- [`docs/ui-ux/index.html`](ui-ux/index.html): message-area inventory wired to
  the real app stylesheet.
- [`docs/ui-ux/two-stage-proposal.html`](ui-ux/two-stage-proposal.html):
  existing two-stage chat UX proposal for issue #536.
- [`THEMES.md`](../THEMES.md): theme and skin guidance; the core palette
  variable contract lives in `static/style.css`.

Current appearance has a theme axis (`light`, `dark`, `system`) and a separate
skin axis (`default`, `ares`, `mono`, `slate`, `poseidon`, `sisyphus`,
`charizard`, `sienna`, `catppuccin`, `nous`, `geist-contrast`) in
`static/boot.js` and `static/style.css`. Do not follow stale `data-theme`-only theme guidance unless
the current code and tests prove that model still applies.

For UI or UX work, include before/after evidence, verify relevant responsive
states, and prefer stable class/data hooks over one-off visual behavior.

## Choosing the relevant contract

Before editing, identify which contract family the task exercises. This is a
routing check, not a request to read every document in the repository. Read the
documents that match the touched subsystem.

Use this lightweight note in an issue comment, draft PR, task note, or AI-agent
handoff when it helps clarify scope:

```markdown
## Contract Routing

Task type:
Touched areas:
Relevant public docs:
- `AGENTS.md`
- `CONTRIBUTING.md`
- `docs/CONTRACTS.md`
- <subsystem-specific documents>
Scope boundaries:
Evidence needed before claiming done:
```

For small, obvious fixes, keep this short. The goal is to avoid routing mistakes,
not to create process overhead.

## Contract changes

Changing contract documents, RFC guidance, or contract tests changes review
expectations for future contributors. A PR that intentionally changes an
existing contract should include a `Contract Change` section in its PR body with:

- the previous contract,
- the new contract,
- the affected docs and tests,
- the compatibility or migration reason.

Contract tests and corresponding docs must move together. Tests that encode
product semantics must not silently redefine the contract by asserting the
opposite behavior without updating the public docs and naming the change in the
PR body.

The static tests for this guidance are advisory coverage. They pin contributor
wording so the rule stays visible. This advisory coverage is not an automated
policy gate; static coverage is not an automated policy gate and does not enforce
PR-body content on GitHub. A future release-time or CI check could
surface contract-affecting diffs whose PR body lacks `Contract Routing`, but this
document only defines the review expectation.

Release batches should list included contract-affecting PRs explicitly so
reviewers can distinguish ordinary green-CI fixes from changes that update the
project's product or runtime guardrails.

## PR preparation checklist

Before opening or updating a PR, verify `CONTRIBUTING.md` against the actual PR
body. This checklist applies even when code and tests are already done.

Required checks:

- The PR solves one logical problem.
- The PR body contains all required sections from `CONTRIBUTING.md`:
  `Thinking Path`, `What Changed`, `Why It Matters`, `Verification`,
  `Risks / Follow-ups`, and `Model Used`.
- `Model Used` discloses provider/model and notable agent/tool use, or says
  `None -- human-authored`.
- UI/UX changes include before/after evidence and responsive-state coverage.
- Runtime/streaming changes name the state layer or invariant being changed and
  list the regression or manual invariant check.
- Contract-affecting PRs include `Contract Routing`; intentional contract
  changes also include `Contract Change`.
- Onboarding/setup validation used isolated `HERMES_HOME` and
  `HERMES_WEBUI_STATE_DIR`, unless the human operator explicitly requested real
  state.
- Docs and `CHANGELOG.md` updates are either included or explicitly not needed.
- After the GitHub write, read the PR back and verify the headings rendered as
  intended.

Green CI plus a focused diff is not sufficient if the PR description or evidence
does not match the touched subsystem.

## Setup, onboarding, and operational references

- [`TESTING.md`](../TESTING.md): automated test command and manual browser test
  plan.
- [`ARCHITECTURE.md`](../ARCHITECTURE.md): API, module layout, and design
  constraints.
- [`docs/onboarding.md`](onboarding.md): first-run wizard and provider setup.
- [`docs/onboarding-agent-checklist.md`](onboarding-agent-checklist.md): safety
  rules for assistant-led install, reinstall, bootstrap, provider setup, local
  model setup, Docker onboarding, and WSL onboarding.
- [`docs/docker.md`](docker.md): Docker compose setup, common failures, and
  bind-mount migration.
- [`docs/troubleshooting.md`](troubleshooting.md): diagnostic flows for common
  failures.
- [`docs/EXTENSIONS.md`](EXTENSIONS.md): administrator-controlled WebUI
  extension injection.
- [`docs/rfcs/user-admin-system.md`](rfcs/user-admin-system.md): multi-user
  WebUI accounts, admin vs user roles, 1:1 profile binding, session shape, and
  `/api/v1/admin/*` user management API.

## Quick redline checklist

Before opening a change for review, confirm:

- The change solves one logical problem; unrelated refactors are split out.
- `AGENTS.md`, this index, and any linked contract for the touched subsystem were
  read before editing.
- Behavior, setup, architecture, testing, or workflow changes update the relevant
  docs; release-note-ready changes update `CHANGELOG.md`.
- UI/UX changes include before/after evidence and cover relevant desktop,
  narrow, and mobile states.
- Runtime, streaming, recovery, replay, compression, or sidebar changes state
  which layer they mutate and include a regression for the invariant.
- New dependencies, build tools, frameworks, or long-lived processes are avoided
  unless the benefit and rollback story are explicit.
- Onboarding/setup validation uses isolated `HERMES_HOME` and
  `HERMES_WEBUI_STATE_DIR` unless the human operator explicitly asks to use real
  state.
- Secrets, private paths, local-only workflows, and personal notes stay out of
  tracked docs and examples.

## Future evolution

This index is not intended to make the first contract set final. Future PRs may
add, revise, split, or retire contracts when real issues, implementation changes,
RFC decisions, contributor feedback, or review experience show that guidance is
incomplete or stale.

Potential follow-up areas include session import/export, cron, extensions,
security boundaries, Docker/runtime isolation, and lightweight checks that keep
key contract links from drifting.
