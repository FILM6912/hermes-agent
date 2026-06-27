# FastAPI Phase 5 — Migration Decommission (COMPLETE)

Phase 5 closes the HTTP server migration from `server.py` (ThreadingHTTPServer) to
`uvicorn app.main:app`. Phases 1–4 delivered the FastAPI shell, native `/api/v1/*`
routers, frontend prefix cutover, zero `dispatch_legacy_route` bridges, and a
`HERMES_WEBUI_LEGACY_API` gate for legacy catch-alls. Phase 5 records completion,
turns the legacy bridge **off by default**, and documents rollback.

**Status: COMPLETE** (2026-05-28)

## Completion checklist

| Item | Status | Evidence |
|------|--------|----------|
| All UI traffic uses `/api/v1/` via `static/workspace.js` `api()` | done | Phase 3 cutover (`docs/phase3-cutover.md`) |
| Explicit v1 routers cover UI API surface | done | ~190 routes in `app/api/v1/endpoints/` |
| Zero `dispatch_legacy_route` in v1 endpoints | done | `rg 'dispatch_legacy_route' app/api/v1/endpoints/` → no matches |
| Zero `handle_legacy_sse` in v1 endpoints | done | Native `app/services/sse_streams.py` |
| `HERMES_WEBUI_LEGACY_API=0` → unmatched `/api/v1/*` returns **404** | done | `tests/test_fastapi_app.py` |
| `HERMES_WEBUI_LEGACY_API=0` → unmatched `/api/*` returns **404** | done | Catch-alls omitted in `app/main.py` |
| `tests/test_fastapi_app.py` passes (legacy on and off) | done | `pytest tests/test_fastapi_app.py -q` |
| Phase 4 exit criteria satisfied | done | `docs/phase4-legacy-removal.md` |
| **`HERMES_WEBUI_LEGACY_API` default off** | done | `Settings.legacy_api` default `False`; unset env → legacy catch-alls not registered |
| Public contract: `/api/v1/` canonical | done | `docs/CONTRACTS.md` |
| `CHANGELOG.md` notes migration complete | done | `[Unreleased]` |
| `server.py` retained for full rollback only | done | `AGENTS.md` |

Re-verify after any API change:

```bash
rg 'dispatch_legacy_route|handle_legacy_sse|run_legacy_dispatch_sync' app/api/v1/endpoints/
HERMES_WEBUI_LEGACY_API=0 pytest tests/test_fastapi_app.py -q
```

## Runtime defaults (post-migration)

| Variable | Default | Meaning |
|----------|---------|---------|
| `HERMES_WEBUI_LEGACY_API` | **off** (`0` / unset → `False`) | When **off**, `app/main.py` does **not** register `/api/*` or `/api/v1/*` catch-alls; unmatched API paths return **404**. SPA shell routes (`legacy_root`, `legacy_pages`) remain. |
| (set `HERMES_WEBUI_LEGACY_API=1`) | rollback | Re-enables legacy catch-alls forwarding to `handle_legacy_request` / `app.domain.routes` for unmigrated `/api/*` aliases. |

Settings: `app.core.config.Settings.legacy_api` (Pydantic bool).

Production and Docker deployments should leave legacy API **off**. Enable only
during an emergency rollback window.

## API contract (canonical)

- **Canonical:** `/api/v1/*` — all new clients and the bundled UI must use this prefix.
- **Deprecated:** `/api/*` without the `v1` segment. When legacy API is **off**, these
  paths are **not** registered and return **404**. When legacy is **on** (rollback),
  they alias legacy `app.domain.routes` handlers.
- **Static:** `/static/*` unchanged.

See `docs/CONTRACTS.md` and `docs/phase4-legacy-removal.md` for gate history.

## Rollback

1. **Short:** `HERMES_WEBUI_LEGACY_API=1`, restart uvicorn.
2. **Full:** revert FastAPI migration commits in git and run `server.py` per `AGENTS.md`.

## What remains (non-blocking)

- `app/domain/routes.py` may still contain `_handle_*` implementations shared by services;
  deleting the module is optional once no rollback path needs it.
- `app/core/legacy_handler.py` serves SPA shell and optional legacy dispatch.
- `server.py` stays in-tree until maintainers remove the ThreadingHTTPServer entry
  in a later cleanup release.

## Verification

```bash
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
pytest tests/test_fastapi_app.py -q

HERMES_WEBUI_LEGACY_API=0 pytest tests/test_fastapi_app.py -q
```

## Related docs

- `docs/phase3-cutover.md` — native service cutover
- `docs/phase4-legacy-removal.md` — legacy gate and catch-all removal
- `docs/CONTRACTS.md` — HTTP API prefix contract
- `ARCHITECTURE.md` — module layout
