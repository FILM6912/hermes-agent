# FastAPI Phase 3 — Native Service Cutover

Phase 3 replaces `dispatch_legacy_route` / `handle_legacy_sse` bridges with
native `app/services/*` implementations, then shrinks the catch-all legacy
dispatch in `app/main.py`.

Phases 1–2 (done): FastAPI shell, explicit v1 routers, frontend `/api/v1/`
prefix, and thin native endpoints for health, profiles, settings, workspaces,
MCP, skills, and partial sessions/models/providers/auth/kanban/chat.

Phase 3 (this branch): **move business logic out of `api/routes.py` into
services**, route by route, until the catch-all is only static assets and
unmapped edge cases.

## Audit snapshot (2026-05-28, post PR #7 merge — Phase 3 native cutover)

| Metric | Count |
|--------|------:|
| Explicit `@router` routes in `app/api/v1/endpoints/*.py` | **190** |
| Routes still delegating to legacy (`_legacy_*` / `dispatch_legacy_route` / SSE bridge) | **111** |
| Routes with native service or in-handler logic | **79** |
| `dispatch_legacy_route(` call sites in `app/api/v1/endpoints/` | **36** |
| `handle_legacy_sse(` streams in endpoints | **5** |
| `_handle_*` functions remaining in `api/routes.py` | **98** |
| `app/services/*.py` modules today | **12** (auth, chat_stream, kanban, models, profiles, providers, sessions, settings, sse_streams, terminal_stream, workspace, `__init__`) |

Phase 4 (legacy catch-all removal) is tracked in `docs/phase4-legacy-removal.md`.
Catch-all wiring in `app/main.py` stays enabled until `dispatch_legacy_route` reaches zero.

### Endpoint modules by legacy share

Fully legacy (0 native service imports): `agent_actions`, `commands`, `crons`,
`dashboard`, `files`, `git`, `memory`, `notes`, `onboarding`, `personalities`,
`projects`, `rollback`, `system`, `updates`, `upload`.

Partially native (service + legacy bridge on some paths): `approval` (8),
`chat` (5), `kanban` (1), `providers` (5), `sessions_misc` (15), `terminal` (5).

Fully native: `auth` (9), `health` (1), `mcp` (7), `models` (7), `profiles` (5),
`sessions` (19), `settings` (2), `skills` (5), `workspace` (7).

### Top 10 high-traffic routes still 100% legacy

Static JS reference counts (`static/*.js`, `/api/…` paths):

| Refs | Route | Legacy handler area |
|-----:|-------|---------------------|
| 5 | `/api/reasoning` | models / session prefs |
| 5 | `/api/session/move` | sessions_misc / projects |
| 4 | `/api/chat/stream/status` | chat streaming |
| 4 | `/api/session/update` | sessions_misc |
| 4 | `/api/session/import_cli` | sessions_misc |
| 3 | `/api/provider/quota` | providers |
| 3 | `/api/file` | files |
| 3 | `/api/session/draft` | sessions_misc |
| 3 | `/api/session/archive` | sessions_misc |
| 2 | `/api/dashboard/config` | dashboard |

Prioritize these when cutting over — they dominate UI polling and user actions.

## What “native cutover” means per route

1. **Extract** handler body from `api/routes.py` (`_handle_*` or inline in
   `handle_get` / `handle_post`) into `app/services/<domain>.py`.
2. **Repository layer** (`app/repositories/*`) wraps existing `api/*.py` modules
   until file-backed state moves to dedicated repos.
3. **FastAPI endpoint** calls the service directly; remove `_legacy_get` /
   `_legacy_post` wrapper for that path.
4. **Tests** in `tests/test_fastapi_app.py` (or domain-specific tests) assert
   parity with legacy responses/status codes.
5. **Delete or stub** the matching branch in `api/routes.py` once all callers
   are native (keep legacy `/api/*` path working via v1 alias until frontend
   cutover is complete).

SSE streams (`handle_legacy_sse`) follow the same rule: service owns event
production; FastAPI returns `StreamingResponse` without calling
`api.routes` handlers.

## Catch-all shrink (`app/main.py`)

Today unmatched `/api/v1/*` and all `/api/*` fall through to
`handle_legacy_request` (see `legacy_api_v1`, `legacy_api` routes).

Phase 3 exit criteria:

- [ ] Every UI-used `/api/v1/*` path has an explicit router entry (done for
      most paths; kanban CRUD still partially native + legacy dispatch).
- [ ] No hot-path route calls `dispatch_legacy_route`.
- [ ] Catch-all limited to: static shell, deprecated `/api/*` alias, CSP report,
      and routes explicitly marked deprecated.
- [ ] `tests/test_fastapi_app.py` covers native paths without legacy bridge.
- [ ] `CHANGELOG.md` entry when catch-all is removed or gated behind env flag.

## Suggested cutover order

1. **Sessions misc** — draft, update, move, archive, import_cli (high traffic,
   isolated from streaming).
2. **Files** — read/save/list; depends on workspace trust boundaries already in
   `app/services/workspace.py`.
3. **Providers / models** — finish quota, reasoning, default-model (reads mostly
   done; mutations still legacy).
4. **Chat** — stream status + SSE native adapter (hardest; keep legacy bridge
   until streaming service exists).
5. **Crons, git, terminal, system** — large surface; slice by subdomain.
6. **Dashboard, onboarding, auth mutations** — lower frequency or already
   partially native.

## Per-PR checklist

- [ ] Read `docs/CONTRACTS.md` + relevant RFC for the subsystem.
- [ ] Add/extend `app/services/<domain>.py` and schemas.
- [ ] Wire FastAPI endpoint to service; remove legacy wrapper for those paths.
- [ ] Port or add tests; run `pytest tests/test_fastapi_app.py` (+ domain tests).
- [ ] Manual smoke: desktop + narrow viewport for touched UI flows.
- [ ] Update `CHANGELOG.md` for user-visible behavior changes.

## Verification commands

```bash
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
pytest tests/test_fastapi_app.py -q
```

```bash
# Re-count legacy vs native routes after each slice
rg -c '@router\.(get|post|put|patch|delete)' app/api/v1/endpoints/
rg -l 'dispatch_legacy_route' app/api/v1/endpoints/
rg -c '^def _handle_' api/routes.py
```
