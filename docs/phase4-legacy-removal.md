# FastAPI Phase 4 — Legacy API Removal

Phase 4 removes the `app/main.py` catch-all that forwards unmatched HTTP
traffic to `handle_legacy_request`, and deletes the remaining
`dispatch_legacy_route` bridges in `app/api/v1/endpoints/`.

Phases 1–3 (done): FastAPI shell, explicit v1 routers, frontend `/api/v1/`
prefix, and native services for core domains (sessions, models, providers,
auth, chat control, SSE adapters). Phase 3 exit audit is in
`docs/phase3-cutover.md`.

Phase 4 (this branch): **gate then remove** legacy dispatch — not a new
feature surface.

## Environment flag

| Variable | Default | Meaning |
|----------|---------|---------|
| `HERMES_WEBUI_LEGACY_API` | `0` (off) | When **off** (default after Phase 5), `app/main.py` does **not** register `/api/*` or `/api/v1/*` catch-alls. When **on**, catch-alls forward to `handle_legacy_request` for rollback. |

Settings: `app.core.config.Settings.legacy_api` (Pydantic bool; unset env → `False`). See `docs/phase5-decommission.md`.

Rollback: set `HERMES_WEBUI_LEGACY_API=1` and restart uvicorn. For full rollback
to `server.py`, revert the FastAPI migration commits per `AGENTS.md`.

## Audit gate (2026-05-28)

| Gate | Required for catch-all removal | Current |
|------|-------------------------------|--------:|
| `dispatch_legacy_route(` in `app/api/v1/endpoints/` | **0** | **0** |
| `handle_legacy_sse(` in endpoints (prefer native `StreamingResponse`) | 0 | **0** |
| `_handle_*` in `api/routes.py` | shrink / delete with route migration | 98 |
| Explicit v1 routers cover all UI `/api/v1/*` paths | yes | ~190 routes |

**Catch-all disabled by default (Phase 5)** — `dispatch_legacy_route` call sites in v1
endpoints are **0**. `create_app()` gates `/api/*` and `/api/v1/*` catch-alls on
`settings.legacy_api` (default off). Set `HERMES_WEBUI_LEGACY_API=1` to re-enable
legacy aliases for rollback.

Re-count after each slice:

```bash
rg -c 'dispatch_legacy_route\(' app/api/v1/endpoints/
rg -l 'dispatch_legacy_route' app/api/v1/endpoints/
rg -c 'handle_legacy_sse' app/api/v1/endpoints/
```

## `app/main.py` catch-all (planned wiring)

Today (legacy API on, default):

- `legacy_api_v1` — `/api/v1`, `/api/v1/{path}`
- `legacy_api` — `/api`, `/api/{path}`
- `legacy_root` / `legacy_pages` — static shell and non-API pages via `handle_legacy_request`

When `HERMES_WEBUI_LEGACY_API=0` **and** `dispatch_legacy_route` count is **0**:

1. Register only `root_router` and static/page handlers needed for the SPA shell.
2. Return `404` for unmatched `/api/*` and `/api/v1/*` (no silent legacy fallback).
3. Keep `legacy_pages` for non-API paths or move static serving to explicit routes.

**Current (Phase 5):** `create_app()` registers `legacy_api_v1` and `legacy_api`
catch-alls only when `settings.legacy_api` is true (`HERMES_WEBUI_LEGACY_API=1`).
`legacy_root` and `legacy_pages` stay registered for the SPA shell.

## Suggested removal order

Mirror Phase 3 traffic priority (`docs/phase3-cutover.md` top-10 table):

1. **sessions_misc** — draft, update, move, archive, import_cli.
2. **files** — read/save/list (workspace trust already in `app/services/workspace.py`).
3. **providers** — quota and mutations still on bridge.
4. **Fully legacy modules** — slice by subdomain: `crons`, `git`, `system`,
   `terminal`, `dashboard`, `onboarding`, then low-traffic admin paths.
5. **SSE bridges** — replace `handle_legacy_sse` with service-owned
   `StreamingResponse` (chat stream last).

Per slice:

- [ ] Native service + tests; remove `dispatch_legacy_route` for those paths.
- [ ] Re-run audit commands; update this doc’s gate table.
- [ ] `CHANGELOG.md` entry when behavior or rollback flags change.

## Exit criteria

- [x] `rg 'dispatch_legacy_route' app/api/v1/endpoints/` returns no matches.
- [x] `HERMES_WEBUI_LEGACY_API=0` integration test: unmatched `/api/v1/foo` → 404.
- [x] `tests/test_fastapi_app.py` passes without legacy catch-all.
- [x] `app/domain/routes.py` trimmed or limited to deprecated `/api/*` alias only (handlers remain for rollback via `HERMES_WEBUI_LEGACY_API=1`).
- [x] `CHANGELOG.md` notes catch-all removal and env flag default flip to `0` (Phase 5 — `docs/phase5-decommission.md`).

**Phase 4 exit: satisfied.** Migration decommission checklist: `docs/phase5-decommission.md`.

## Verification

```bash
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
pytest tests/test_fastapi_app.py -q
```

Optional trial with legacy off (expect failures until gate = 0):

```bash
HERMES_WEBUI_LEGACY_API=0 pytest tests/test_fastapi_app.py -q
```
