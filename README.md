# Hermes WebUI

A browser interface for the [Hermes agent](https://github.com/NousResearch/hermes-agent)—chat, sessions, workspace files, and provider setup in one place.

**Stack:** FastAPI backend (`app/`), React + Vite frontend ([Agent-UI](https://github.com/FILM6912/Agent-UI) in `frontend/`), REST + SSE at `/api/v1/*`.

---

## Features

- **Chat & sessions** — multi-turn conversations with streaming responses, reasoning traces, and tool activity
- **Workspace browser** — list, preview, edit, and manage files in the agent workspace
- **Profiles & models** — switch agent profiles, pick models, configure providers
- **First-run onboarding** — guided setup when Hermes is not yet configured
- **Docker-ready** — Compose with `hermes-agent` + WebUI and bind mounts for `./hermes` and `./workspace`
- **Optional auth** — password or multi-user mode for shared deployments

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Hermes agent** | Installed locally or bundled in the Docker image |
| **Python 3.11+** | Local dev and server runtime |
| **Node.js 20+** | Frontend build (`frontend/`) |
| **Docker** (optional) | Recommended for production-like runs |

---

## Quick Start

### Docker (recommended)

```bash
mkdir -p hermes workspace
cp .env.docker.example .env
# Edit UID/GID if needed (macOS: id -u / id -g)
docker compose up -d --build
```

Open **http://localhost:8787** (gateway: **http://localhost:8642**).

`docker-compose.yml` runs **hermes-agent** (gateway) and **hermes-webui** together.
Local embedding/reranker GPU passthrough is enabled on **hermes-webui** by default
(NVIDIA driver + Container Toolkit on the host). CPU-only:
`docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build`.
Hermes state lives in `./hermes` and workspace files in `./workspace` (empty scaffold
on clone — see `hermes/README.md` and `workspace/README.md`).

For split agent + WebUI layouts, see `docker-compose.two-container.yml` and `docker-compose.three-container.yml`.

### Local development

**Backend** — use isolated state unless you intend to touch real data:

```bash
HERMES_HOME=/tmp/hermes-webui-agent-home \
HERMES_WEBUI_STATE_DIR=/tmp/hermes-webui-agent-state \
HERMES_WEBUI_PORT=8789 \
python3 bootstrap.py
```

**Frontend** — Vite dev server proxies `/api` to the backend:

```bash
cd frontend && npm ci && npm run dev
```

Open **http://localhost:5173** while the backend runs on the matching port (default proxy target: `8789`; set `HERMES_WEBUI_PORT` on both sides).

**Production-like UI** (built assets served by uvicorn):

```bash
cd frontend && npm ci && npm run build
python3 bootstrap.py
```

---

## Project structure

```
hermes-ui/
├── app/
│   ├── main.py              # FastAPI entry (uvicorn app.main:app)
│   ├── api/v1/              # HTTP routes
│   └── domain/              # Business logic (streaming, config, sessions, …)
├── frontend/                # React + Vite Agent-UI source
├── static/dist/             # Production UI build (gitignored; npm run build)
├── bootstrap.py             # One-shot launcher (deps, health, browser)
├── docker-compose.yml       # Single-container setup
├── tests/                   # pytest suite
└── docs/                    # Contracts, onboarding, troubleshooting
```

Legacy vanilla UI modules remain under `static-legacy/` for reference only—new UI work belongs in `frontend/`.

---

## Configuration

Essential environment variables. Full Docker options: `.env.docker.example`.

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_HOME` | `~/.hermes` | Hermes agent state (config, sessions, skills) |
| `HERMES_WEBUI_HOST` | `0.0.0.0` | Bind address |
| `HERMES_WEBUI_PORT` | `8787` | HTTP port |
| `HERMES_WEBUI_STATE_DIR` | `./webui` | WebUI-specific state (relative to `HERMES_HOME`) |
| `HERMES_WORKSPACE` | `./workspace` | Host workspace path (Docker bind mount) |
| `HERMES_WEBUI_PASSWORD` | — | Optional single shared password |
| `HERMES_WEBUI_MULTI_USER` | — | Set `1` to enable multi-user auth |
| `UID` / `GID` | `1000` | Container user for Docker bind mounts |

Local model servers (LM Studio, Ollama) on the Docker **host** must use `host.docker.internal` in `~/.hermes/config.yaml`, not `127.0.0.1`.

---

## Development

```bash
# Backend tests
pytest tests/

# Frontend typecheck & build
cd frontend && npm run typecheck && npm run build

# Lint / hooks (if installed)
pre-commit run --all-files
```

Contributors: read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md) before opening a PR. Contract and subsystem rules live in [`docs/CONTRACTS.md`](docs/CONTRACTS.md).

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Module layout, streaming, frontend integration |
| [`TESTING.md`](TESTING.md) | Manual and automated verification |
| [`docs/onboarding.md`](docs/onboarding.md) | First-run and provider setup |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common failures and diagnostics |
| [`docs/UIUX-GUIDE.md`](docs/UIUX-GUIDE.md) | UI patterns and interaction rules |
| [`CHANGELOG.md`](CHANGELOG.md) | Release notes |

---

## License

[MIT](LICENSE) — Copyright (c) 2025 Hermes Web UI Contributors
