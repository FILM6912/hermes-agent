# Agent instructions for Hermes WebUI

This file is the shared entry point for AI assistants working in this
repository. Keep it project-specific and safe to publish. Do not put personal
machine setup, private network details, credentials, tokens, or local-only
workflow notes here.

## Read first

Before making changes, read:

1. `README.md`
2. `CONTRIBUTING.md`
3. `docs/CONTRACTS.md`
4. `CHANGELOG.md`

For architecture, testing, or setup work, also read the matching reference:

- `ARCHITECTURE.md` for design constraints and current module layout. Business logic
  lives in `app/domain/` (formerly top-level `api/`).
- `TESTING.md` for local verification commands and manual test guidance
- `docs/onboarding.md` for first-run onboarding behavior
- `docs/troubleshooting.md` for diagnostic flows
- `docs/rfcs/README.md` for larger RFCs and state/durability contracts

For UI or UX work, read `docs/UIUX-GUIDE.md` and `DESIGN.md` before
changing layout, interaction flow, themes, chat rendering, or composer chrome.

For the React frontend (`frontend/`), also read `ARCHITECTURE.md` (React
frontend section) for build output paths, dev proxy workflow, and SPA serving.

## Onboarding and reinstall support

If the task involves install, reinstall, bootstrap, first-run onboarding,
provider setup, local model server setup, Docker onboarding, WSL onboarding, or
support for a failed first run, read `docs/onboarding-agent-checklist.md`
before running commands or inspecting logs.

Follow that checklist's safety rules:

- use isolated `HERMES_HOME` and `HERMES_WEBUI_STATE_DIR` for trials unless the
  human explicitly asks to use real state
- do not delete or overwrite a real `~/.hermes` directory without explicit
  approval
- do not print API keys, OAuth tokens, cookies, full `.env` files, full
  `auth.json` files, or password hashes
- collect non-secret status and log evidence before recommending a fix

## Contribution style

- Keep one logical change per PR; split unrelated refactors or cleanup.
- Read `docs/CONTRACTS.md` and the linked contract/RFC for the touched
  subsystem before editing.
- Server code stays Python + FastAPI under `app/domain/`. The browser UI is a
  **React + Vite + TypeScript** SPA in `frontend/` (Agent-UI).
  Build output lands in `static/dist/` and is served by FastAPI; do not commit
  `node_modules/` or `static/dist/`. Legacy vanilla modules may remain under
  `static-legacy/` for rollback reference only — do not extend them for new features.
- For `frontend/` changes: run `npm run build` (or `npm run typecheck`) before
  claiming the UI bundle is good; use the dev workflow below when iterating on
  UI against a live backend.
- Do not add new npm dependencies, build tools, or long-lived processes without
  clear justification and a rollback story documented in the PR.
- The HTTP server runs on FastAPI (`app.main:app` via uvicorn). Primary
  launchers: `bootstrap.py`, `docker_init.bash`, and
  `python -m uvicorn app.main:app`. Roll back via git revert or invoke
  `server.py` (deprecated thin launcher kept for compatibility).
- Business logic lives in `app/domain/`; import `app.domain.*` in new code.
- Update docs when changing setup, onboarding, runtime behavior, architecture,
  testing guidance, or user-facing workflows.
- Update `CHANGELOG.md` for user-visible behavior, setup, workflow, or
  documentation changes that should be release-note ready.
- For UI or UX changes, include before/after evidence and test relevant
  desktop, narrow, and mobile states.
- For behavior changes, add or update automated tests where practical and list
  the manual verification performed.
- For runtime, streaming, recovery, replay, compression, or sidebar metadata
  changes, name the state layer being mutated and prove the relevant invariant.

## Local state and secrets

Hermes WebUI can read and write real agent state, sessions, workspaces,
credentials, and cron data. Treat local validation as potentially destructive
unless you have confirmed the active state directories.

Prefer isolated trial state for experiments:

```bash
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
python3 bootstrap.py
```

## React frontend dev workflow

Prerequisites: Node.js 20+ and npm (Docker images already include `nodejs`/`npm` and `bun`/`bunx`).

**Production-like UI** (built assets served by uvicorn):

```bash
cd frontend && npm ci && npm run build
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
python3 bootstrap.py
# open http://127.0.0.1:8789 — requires static/dist from npm run build
```

**Fast UI iteration** (Vite dev server proxies `/api` to the backend):

```bash
# Terminal 1 — backend (pick a port; example 8789)
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
python3 bootstrap.py

# Terminal 2 — frontend (Vite default http://localhost:5173)
cd frontend && npm run dev
# Vite proxies /api -> http://localhost:8789 by default (HERMES_WEBUI_PORT).
# Match terminal 1, or set HERMES_WEBUI_PORT on both sides.
# If REPO_ROOT/.env sets a different port, use HERMES_WEBUI_PRESERVE_ENV=1 or
# `python3 bootstrap.py <port>` so shell/bootstrap port wins over .env.
```

Use isolated `HERMES_HOME` / `HERMES_WEBUI_STATE_DIR` for trials unless the human
explicitly asks to use real state.

Frontend tests (when present): `cd frontend && npm test`. E2E may require a
running server — see `TESTING.md` / Playwright config in the repo.

Do not include private machine instructions in this tracked file. Use a
git-ignored local note for personal workflow details.
