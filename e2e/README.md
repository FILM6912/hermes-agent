# Hermes WebUI — Playwright e2e (Agent-UI shell)

Browser smoke tests for login and post-auth shell visibility against a running
Hermes server on **port 8787** (default `http://127.0.0.1:8787`). Tests use
**stable selectors** shared by the legacy HTML UI and the React Agent-UI shell.

## Prerequisites

1. **Running Hermes server** (Playwright does not boot the app):

   ```bash
   HERMES_HOME=/tmp/hermes-webui-agent-home \
   HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
   HERMES_WEBUI_PORT=8787 \
   python3 bootstrap.py
   ```

   Or Docker / `python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787`.

2. **Health check:** `curl -fsS http://127.0.0.1:8787/health` → `{"status":"ok"}`.

3. **When auth is enabled**, set credentials (see `.env.example`):

   - `HERMES_E2E_PASSWORD` — required
   - `HERMES_E2E_USERNAME` — required for multi-user (`HERMES_WEBUI_MULTI_USER=1`)

4. **Optional:** `HERMES_E2E_BASE_URL` (default `http://127.0.0.1:8787`).

### UI bundle

| Mode | How to run UI | Notes |
|------|----------------|-------|
| Legacy shell | Hermes serves `static/index.html` | Tests use `#login-form`, `.sidebar`, `#composerWrap`. Agent-UI class cases skip automatically. |
| Agent-UI React | `cd frontend && npm run build` then Hermes serves `static/dist/` (or `npm run dev` with API on 8787) | `data-testid` hooks below; class contract in `fixtures/agentClasses.ts`. |

## Install and run

```bash
cd e2e
npm install
npm run install:browsers
export HERMES_E2E_PASSWORD=changeme   # when auth enabled
export HERMES_E2E_USERNAME=admin      # multi-user only
npm test
```

Headed / UI mode: `npm run test:headed`, `npm run test:ui`.

## Tests

| Spec | What it checks |
|------|----------------|
| `tests/agent-ui.smoke.spec.ts` | **Login:** `/login` form visible; with auth + env creds, login succeeds and leaves `/login`; React login exposes Agent-UI auth classes. **Shell:** after login (or `/` when auth off), main shell chrome is visible; React shell exposes Agent-UI layout classes (`hermes-shell-page`, `shell-layout`, …). |

Auth-disabled installs skip the credential-dependent cases automatically.

## React shell selector contract

Implement these on Agent-UI routes so e2e stays stable:

| `data-testid` | Element |
|---------------|---------|
| `login-form` | Sign-in `<form>` |
| `login-username` | Username field (multi-user) |
| `login-password` | Password field |
| `login-submit` | Primary submit control |
| `hermes-shell` | Root layout wrapping sidebar + main + composer |

Legacy IDs (`#login-form`, `#pw`, `.sidebar`, `#composerWrap`) remain supported during migration.

### Agent-UI class contract (React only)

When the React bundle is served, smoke tests also assert these classes (see `fixtures/agentClasses.ts`):

| Area | Classes / markers |
|------|-------------------|
| Login form | `data-testid="login-form"`, `#login-title` |
| Login page enter | `.animate-auth-page-enter` on the auth screen root |
| Shell page | `hermes-shell-page`, `hermes-app` (`data-testid="hermes-shell-page"`) |
| Shell regions | `hermes-shell-page__rail`, `hermes-shell-page__main` |
| Chat layout | `shell-layout`, `shell-layout--enter`, `hermes-app`, `hermes-shell`, `shell-layout__inner` (`data-testid="hermes-shell"`) |

Legacy HTML UI skips React-only class cases automatically. React `/assets/*` bundles are served without authentication so `/login` can hydrate before sign-in.
