# Agent-UI → Hermes API migration slices

Branch: `feat/agent-ui-migration`. One slice = one PR-sized vertical cut; **do not** edit the same files in parallel.

Legend: `Hermes` = exists on backend; `Adapter` = new `frontend/src/services/hermes/*`; `Stub` = TODO + UI disabled.

**Waves** (parallel batches should stay within one wave unless noted):

| Wave | Tag | Slices | Theme |
|------|-----|--------|-------|
| W0 | `infra` | M00 | Vite proxy, build → `static/dist`, shell bootstrap |
| W1 | `auth` | M01–M04 | Auth probe, login, passkey, CSRF |
| W2 | `settings` | M05–M07 | Settings, profiles, models |
| W3 | `sessions` | M08–M12 | Session list CRUD + history |
| W4 | `chat` | M13–M17 | Stream, cancel, title, suggestions, SSE |
| W5 | `workspace` | M18–M22 | Workspaces, files, upload |
| W6 | `composer` | M23 | Slash commands |
| W7 | `integrations` | M24–M25 | Skills, MCP |
| W8 | `projects` | M26 | Project grouping |
| W9 | `modals` | M27–M28 | Approval, clarify |
| W10 | `onboarding-admin` | M29–M30 | Onboarding, admin users |
| W11 | `langflow-removal` | M31–M32 | Remove Langflow deps |
| W12 | `shell-routes` | M33–M35 | ShellRouter extraction, Kanban panel, errors |
| W13 | `ux-polish` | M36–M38 | Scheduled jobs, terminal, memory panels |
| W14 | `reliability` | M39–M40 | Network/SSE, E2E smoke |
| W15 | `cutover` | M41–M42 | Insights/logs admin panels, Git workspace panel |

## API inventory (Agent-UI call sites → Hermes)

| Call site | Current endpoint | Hermes target | Notes |
|-----------|------------------|---------------|-------|
| `langflowService.ts` | `GET /api/v1/flows/{id}` | — | **Langflow-only** → remove; use `GET /api/v1/models` + profiles |
| `langflowService.ts` | `POST /api/v1/run/{flowId}` (stream) | `POST /api/v1/chat/start` + `GET /api/v1/chat/stream` | **Adapter** `hermesChatService.ts` |
| `langflowService.ts` | `POST /api/v1/responses` | same as chat | OpenAI-compat not on Hermes |
| `langflowService.ts` | `GET /api/v1/monitor/messages` | `GET /api/v1/sessions`, `GET /api/v1/session` | Session list + messages in session JSON |
| `langflowService.ts` | `DELETE .../monitor/messages/session/{id}` | `POST /api/v1/session/delete` | |
| `langflowService.ts` | Langflow file upload | `POST /api/v1/upload` (see `upload.py`) | Different shape |
| `fileService.ts` | `/api/v1/files/*` (Agent file API) | `GET /api/v1/list`, `/file`, `/file/raw`, workspace routes | **Adapter** — path/query differ |
| `useAgentFlows.ts` | `GET /api/v1/flows/` | `GET /api/v1/models` or providers | **Adapter** |
| `useAgentModels.ts` | `GET /api/v1/flows/` | `GET /api/v1/models` | **Adapter** |
| `useLangflowConfig.ts` | localStorage + Langflow health | `GET /api/v1/settings` | Replace with Hermes settings |
| `AuthPage.tsx` | mock delay login | `GET/POST /api/v1/auth/*` | **Adapter** `authService.ts` |
| `CachedImage.tsx` | `fetch(src)` | same / cookies | May need `/api/v1/media` |
| `App.tsx` | orchestrates langflow + localStorage | Hermes session + chat services | Split per slice below |

## Slices (M00–M42)

| ID | Wave | Title | Files (primary) | Hermes endpoints | Acceptance criteria | Status |
|----|------|-------|-----------------|------------------|---------------------|--------|
| M00 | `infra` | Infrastructure gate | `vite.config.ts`, `package.json`, `index.html`, `main.tsx`, `routes/ShellRouter.tsx` | — | `npm run build` → `static/dist`; `/api` Vite proxy → Hermes; `npm run typecheck` | **done** |
| M01 | `auth` | Auth status probe | `features/auth/services/authService.ts`, `hooks/useAuthBoot.ts` | `GET /api/v1/auth/status` | `useAuthBoot` + `isShellAuthenticated`; App boot unchanged (M33) | **done** |
| M02 | `auth` | Auth login/logout UI | `features/auth/components/AuthPage.tsx`, `Sidebar.tsx` | `POST auth/login`, `POST auth/logout` | Real login; Sidebar `authService.logout()` + CSRF | **done** |
| M03 | `auth` | Passkey auth (optional) | `PasskeyButton.tsx`, `authService.ts` | `POST auth/passkey/*` | Passkey button when `passkeys_enabled` | **done** |
| M04 | `auth` | CSRF from shell | `index.html`, `main.tsx`, `lib/api.ts` | injected `__HERMES_CONFIG__` | Mutating API calls include `X-Hermes-CSRF-Token` | **done** |
| M05 | `settings` | Settings load/save | `features/settings/**`, `hermes/settings.ts` | `GET/POST /api/v1/settings` | General tab persists theme/font to Hermes | **done** |
| M06 | `settings` | Profiles list/switch | `settings` or shell store | `GET /profiles`, `POST /profile/switch` | Profile picker in settings | **done** |
| M07 | `settings` | Models/providers picker | `useAgentModels.ts`, `ModelSelector.tsx` | `GET /models`, `GET /providers` | Replaces Langflow flows list | **done** |
| M08 | `sessions` | Sessions list | `hermes/sessions.ts`, `types/hermes/sessions.ts` | `GET /api/v1/sessions` | Typed list + `listSessions` / narrow helpers | **done** |
| M09 | `sessions` | Session create | `hermes/sessions.ts` | `POST /session/new` | `createSession` / `createSessionId` | **done** |
| M10 | `sessions` | Session delete | `hermes/sessions.ts` | `POST /session/delete` | `deleteSession` + body builder | **done** |
| M11 | `sessions` | Session rename | `hermes/sessions.ts` | `POST /session/rename` | `renameSession` + body builder | **done** |
| M12 | `sessions` | Session detail/history | `langflowService` → `hermesChatService` | `GET /session?session_id=` | Opening chat loads messages | **done** |
| M13 | `chat` | Chat stream send | `hermesChatService.ts`, `App.tsx` `handleSend` | `POST /chat/start`, SSE `/chat/stream` | Streaming assistant text in UI | **done** |
| M14 | `chat` | Chat cancel/stop | `handleStop` | `GET /chat/cancel?stream_id=` | Stop aborts stream | **done** |
| M15 | `chat` | Chat title | `renameSessionOnFirstMessage` | local or `POST session/rename` | Title from first user message | **done** |
| M16 | `chat` | Follow-up suggestions | `generateSuggestions` | **Stub** or Hermes prompt | Empty array OK with TODO | **done** |
| M17 | `chat` | Sessions SSE refresh | sidebar, `App.tsx` | `GET /sessions/events` (SSE) | List updates without full reload | **done** |
| M33 | `sessions` | Session pin + search UI | `Sidebar.tsx`, `sessions.ts` | `POST /session/pin`, `GET /sessions/search` | Pin toggle in sidebar; debounced server search | **done** |
| M34 | `chat` | Tool/reasoning traces | `ThinkingTrace.tsx`, `ToolCard.tsx`, `MessageItem.tsx` | stream `steps` | ProcessStep from SSE renders in transcript | **done** |
| M18 | `workspace` | Workspace registry | `PreviewWindow`, `hermes/workspace.ts` | `GET /workspaces`, `POST workspaces/*` | Workspace dropdown from Hermes | **done** |
| M19 | `workspace` | Workspace file tree | `useFileSystem.ts`, preview | `GET /list?path=` | Tree matches Hermes workspace | **done** |
| M20 | `workspace` | File read/preview | `fileService` adapter | `GET /file`, `/file/raw`, `/file/view` | Open file in preview panel | **done** |
| M21 | `workspace` | File save/write | preview editor | `POST /file/save` | Save writes to workspace | **done** |
| M22 | `workspace` | Upload service | `hermes/upload.ts` | `POST /upload` | `uploadFile` adapter + CSRF | **done** |
| M22-UI | `workspace` | Composer attachments | `ChatInput`, `useFileHandling`, `streamChat` | `POST /upload`, chat start | Images attach to turn via Hermes upload | **done** |
| M23 | `composer` | Slash commands | composer | `GET /commands` | `/` menu lists Hermes commands | **done** |
| M24 | `integrations` | Skills panel | `features/skills/**`, `ShellRouter.tsx` | `GET/POST /skills*`, hub search/install | List/toggle skills; hub search + install; route `/skills` | **done** |
| M25 | `integrations` | MCP tools list | `MCPServerList.tsx` | `GET /mcp/*` | Shows configured MCP servers | **done** |
| M26 | `projects` | Projects grouping | `features/projects/**`, `Sidebar.tsx` | `GET/POST /projects`, `POST /session/move` | Project filter bar; create/rename/delete; move sessions | **done** |
| M27 | `modals` | Approval modal | new component | `GET approval/pending`, SSE, `POST respond` | Tool approval UI | **done** |
| M28 | `modals` | Clarify modal | new component | `GET clarify/pending`, SSE, `POST respond` | Clarify questions UI | **done** |
| M29 | `onboarding-admin` | Onboarding gate | route + wizard | `GET /onboarding/*` | First-run redirects when incomplete | **done** |
| M30 | `onboarding-admin` | Admin users tab | `features/admin/UsersPanel.tsx`, `usersApi.ts` | `GET/POST/PATCH/DELETE /admin/users` | Admin CRUD when multi-user; tab hidden for non-admin | **done** |
| M30b | `onboarding-admin` | Admin profiles panel | `features/admin/ProfilesPanel.tsx`, `profilesApi.ts` | `GET/POST /profiles`, `/profile/create`, `/profile/delete`, `/profile/sync-from-default` | Profile CRUD + sync; hidden when multi-user non-admin | **done** |
| M31 | `langflow-removal` | Remove Langflow settings | `LangflowTab`, `useLangflowConfig`, vite proxy | — | Tabs hidden or stubbed; no Langflow proxy | **done** |
| M31-final | `langflow-removal` | Clean vite/package | `vite.config.ts`, `package.json` | — | No `GEMINI_API_KEY` define; no `@google/genai` | **done** |
| M32 | `langflow-removal` | Strip Langflow service | delete/rename `langflowService.ts` | — | No imports of Langflow paths in `App.tsx` | **done** |
| M33 | `shell-routes` | Extract routes to ShellRouter | `ShellRouter.tsx`, `App.tsx` | — | Route elements live in ShellRouter; App passes shell props | **done** |
| M33-App | `shell-routes` | App Hermes integrator | `App.tsx` | M01 + M08–M13 sessions/auth/stream | No `langflowService`/`fileService` in App; `useAuthBoot`; build passes | **done** |
| M34-shell | `shell-routes` | Global error boundary | new `ErrorBoundary.tsx` | — | Uncaught render errors show recoverable UI | **done** |
| M35 | `shell-routes` | Kanban panel | `features/kanban/**`, `ShellRouter.tsx` | `GET/POST/PATCH /kanban/*`, SSE `/kanban/events/stream` | Board columns, task CRUD, live SSE refresh; route `/kanban` | **done** |
| M36 | `ux-polish` | Scheduled jobs panel | `features/tasks/**`, `ShellRouter.tsx` | `GET/POST /crons/*` | List/create/edit/pause/resume/run/delete; route `/tasks` | **done** |
| M37 | `ux-polish` | Terminal panel | `features/terminal/**`, `ShellRouter.tsx` | `POST /terminal/*`, SSE `/terminal/output` | Workspace PTY via xterm; route `/terminal` | **done** |
| M38 | `ux-polish` | Memory / SOUL / notes panel | `features/memory/**`, `ShellRouter.tsx` | `GET/POST /memory`, `/notes/*` | My notes, User profile, Agent Soul tabs; external notes when enabled; route `/memory` | **done** |
| M39 | `settings` | Providers + plugins settings | `ProvidersTab.tsx`, `PluginsTab.tsx`, `providersSettingsApi.ts` | `GET/POST /providers`, `/plugins`, `/provider/quota` | Settings tabs; providers/plugins for all users; admin users/profiles gated | **done** |
| M39-reliability | `reliability` | Network + SSE reconnect | `useOnlineStatus.ts`, `OfflineBanner.tsx`, `useSessionEvents.ts` | SSE `/sessions/events`, `GET /health` | Exponential backoff reconnect (max 30s); offline banner | **done** |
| M40 | `reliability` | CI + Docker frontend build | `Dockerfile`, `workflows/tests.yml` | — | `npm ci && npm run build` in CI; image ships `static/dist` | **done** |
| M41 | `cutover` | Insights + Logs (admin) | `features/insights/**`, `features/logs/**`, `ShellRouter.tsx` | `GET /insights`, `GET /logs` | Admin-only routes `/insights`, `/logs`; period/tail/severity/scope controls | **done** |
| M42 | `cutover` | Git workspace panel | `features/git/**`, `ShellRouter.tsx` | `GET/POST /git/*` | Status/diff/branches; stage/commit/pull/push; route `/git` | **done** |
| M43 | `cutover` | Shell sidebar navigation | `Sidebar.tsx`, `App.tsx`, `translations.ts` | — | Sidebar links to `/tasks`, `/kanban`, `/skills`, `/terminal`, `/memory`, `/git`; admin-gated `/insights` + `/logs` via `canAccessInsightsLogs`; `renameSessionOnFirstMessage` on first user turn; Approval/Clarify modal imports fixed | **done** |

## Integration notes (M43)

- **ShellRouter** registers all panel routes: kanban, tasks, skills, terminal, memory, insights, logs, git; settings tabs (users, profiles, providers, plugins) remain under `/settings/:tab` via `SettingsView` + `useAuthRole` gating.
- **Sidebar** `shellNavItems` uses `useAuthRole` + `canAccessInsightsLogs` for Insights/Logs (hidden for non-admin in multi-user mode).
- **First-message title**: `App.tsx` `handleSend` calls `renameSessionOnFirstMessage` (M15) instead of local-only `generateChatTitle` + `renameSession`.
- Overlay panels hide the main sidebar; users return via each panel's **Back to chat** control.

**Batch A** (no `App.tsx`): M02, M04, M05, M06, M07, M31  
**Batch B** (services only): M08–M12 via `hermes/sessions.ts` + `hermesChatService.ts` then single `App.tsx` integrator M13–M14  
**Batch C** (preview): M18–M21 (M18–M19 done)  
**Batch D** (advanced): M23–M30  
**Batch E** (post-cutover): M33–M42  

## Assumptions

- SPA served from `static/dist` (`HERMES_WEBUI_UI` unset, dist present).
- Auth uses cookie `hermes_session`; CSRF from shell injection in production.
- Vite dev: `HERMES_WEBUI_PORT` (default `8787`) proxies `/api` to Hermes; optional `VITE_HERMES_CSRF_TOKEN` for mutating calls in dev.

## Audit summary (2026-05-29)

Branch `feat/agent-ui-migration`: **42 of 42 slices complete** (M00–M42).

| Status | Slices | Notes |
|--------|--------|-------|
| **done** | M00–M42 | Hermes adapters wired; Langflow removed; CI/Docker build `frontend/` → `static/dist/`; global `ErrorBoundary` wraps App in `main.tsx`; M39-reliability SSE backoff + offline banner |

All acceptance criteria in the slice table are met.
