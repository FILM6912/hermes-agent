# Agent-UI dev smoke test (~5 minutes)

Quick manual verification that the React Agent-UI shell talks to a local Hermes backend.
Use **isolated state** unless you intentionally want real `~/.hermes` data.

## Prerequisites

- Python 3.11+ with Hermes WebUI deps (same as `bootstrap.py` / repo `requirements`).
- Node.js 20+ and `cd frontend && npm ci` (once per clone).

## 1. Backend API smoke (~1 min)

Terminal 1 — start Hermes on **8789** with isolated dirs:

```bash
mkdir -p /tmp/hermes-webui-agent-home /tmp/hermes-webui-agent-state

cd /path/to/hermes-ui
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
HERMES_WEBUI_PRESERVE_ENV=1 \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8789 --log-level warning
```

> **Note:** `python3 bootstrap.py` may read `REPO_ROOT/.env` and override `HERMES_WEBUI_PORT`.
> Use `HERMES_WEBUI_PRESERVE_ENV=1`, pass an explicit port (`python3 bootstrap.py 8789`), or align `.env` with your port.
> `bootstrap.py` runs uvicorn from the **repo root** when `app/main.py` exists; if you still see `No module named 'app'`, use the uvicorn one-liner above from repo root.

Terminal 2 — probe health (expect HTTP 200):

```bash
curl -fsS http://127.0.0.1:8789/health
curl -fsS http://127.0.0.1:8789/api/v1/auth/status
```

Example healthy responses:

- `/health` → `{"status":"ok",...}`
- `/api/v1/auth/status` → JSON with `auth_enabled`, `logged_in`, etc.

Stop the server when done (`Ctrl+C` or `fuser -k 8789/tcp`).

## 2. Vite dev proxy (~30 s)

`frontend/vite.config.ts` proxies `/api` to:

```text
http://localhost:${HERMES_WEBUI_PORT || "8789"}
```

**Match the backend port** when starting Vite:

```bash
# Terminal 1 — backend on 8789 (see above)

# Terminal 2 — frontend
cd frontend
HERMES_WEBUI_PORT=8789 npm run dev
# open http://localhost:5173
```

If the backend stays on the default **8789**, omit `HERMES_WEBUI_PORT` on both sides or set `8789` consistently.

Optional: `VITE_HERMES_CSRF_TOKEN` / `HERMES_CSRF_TOKEN` when mutating APIs require CSRF in dev.

## 3. UI manual checklist (~3 min)

With backend + `npm run dev` running and ports aligned:

| Step | Action | Pass if |
|------|--------|---------|
| **Auth** | Open `http://localhost:5173/login`. Sign in with your dev credentials (or confirm redirect when auth is off). | Leaves `/login`; shell loads without auth errors in the network tab. |
| **New chat** | From home/sidebar, start a **new chat** (or open `/` / `/chat`). | Empty or fresh thread; composer is enabled. |
| **Send message** | Type a short prompt and send. | User bubble appears; assistant reply or streaming activity starts (no 5xx on `/api/v1/chat/*`). |
| **Settings** | Open **Settings** → `/settings/general`. Change one harmless option (e.g. theme/language) if available. | Panel renders; save or toggle does not break the shell. |
| **Panel route** | Open one shell panel, e.g. **Scheduled jobs** `/tasks`, **Memory** `/memory`, or **Git** `/git`. | Route loads panel chrome; no blank crash; API errors are surfaced, not a white screen. |

**Production-like UI** (optional): `cd frontend && npm run build`, then serve via `bootstrap.py` / uvicorn on the same port and open `http://127.0.0.1:<port>/` (built assets in `static/dist/`).

## 4. Automated follow-up

- Playwright e2e: `e2e/README.md` (`HERMES_E2E_PASSWORD`, base URL).
- Typecheck: `cd frontend && npm run typecheck`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| API 404 / connection refused from Vite | `HERMES_WEBUI_PORT` matches on backend **and** `npm run dev`. |
| `bootstrap` uses wrong port | `.env` vs shell env; use `HERMES_WEBUI_PRESERVE_ENV=1` or `bootstrap.py 8789`. |
| `ModuleNotFoundError: app` | Run uvicorn from repo root, not agent-only cwd. |
| Login loops | `curl /api/v1/auth/status`; confirm credentials and multi-user flags. |
| LM Studio / Ollama `APIConnectionError` in Docker | Base URL must not be `127.0.0.1` from inside the container; use `http://host.docker.internal:1234/v1` in `~/.hermes/config.yaml` and ensure `docker-compose.yml` `extra_hosts` is present. See `.env.docker.example`. |
