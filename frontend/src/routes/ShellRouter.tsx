import { useEffect, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Navigate, Route } from "react-router-dom";
import type { AuthStatus } from "@/features/auth/services/authService";
import { InsightsPanel, canAccessInsights, canAccessLogs } from "@/features/insights";
import { KanbanPanel } from "@/features/kanban";
import { LogsPanel } from "@/features/logs";
import { MemoryPanel } from "@/features/memory";
import { SkillsPanel } from "@/features/skills";
import { TasksPanel } from "@/features/tasks";
import { ShellTerminalPanel } from "@/features/terminal";

/**
 * Shell route registry for Agent-UI → Hermes migration.
 */
export const SHELL_ROUTE_PATHS = {
  home: "/",
  login: "/login",
  register: "/register",
  chat: "/chat",
  chatById: "/chat/:chatId",
  settings: "/settings/:tab",
  kanban: "/kanban",
  tasks: "/tasks",
  skills: "/skills",
  terminal: "/terminal",
  memory: "/memory",
  insights: "/insights",
  logs: "/logs",
} as const;

/** Future panel routes (wired in later slices). */
export const FUTURE_PANEL_ROUTE_PATHS = {
  onboarding: "/onboarding",
  admin: "/admin",
} as const;

export type ShellRoutePath =
  (typeof SHELL_ROUTE_PATHS)[keyof typeof SHELL_ROUTE_PATHS];

export type ShellPanelId =
  | "chat"
  | "settings"
  | "kanban"
  | "tasks"
  | "skills"
  | "terminal"
  | "memory"
  | "insights"
  | "logs";

export type ShellPanelRouteProps = {
  isAuthenticated: boolean;
  authStatus: AuthStatus | null;
  activeSessionId: string;
  renderAppLayout: (panel: ShellPanelId) => ReactNode;
};

/**
 * M35/M36/M37/M38 — Panel routes extracted from App.tsx shell.
 */
export function ShellPanelRoutes({
  isAuthenticated,
  authStatus,
  renderAppLayout,
}: ShellPanelRouteProps) {
  if (!isAuthenticated) {
    return (
      <>
        <Route path={SHELL_ROUTE_PATHS.kanban} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.tasks} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.skills} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.terminal} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.memory} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.insights} element={<Navigate to="/login" />} />
        <Route path={SHELL_ROUTE_PATHS.logs} element={<Navigate to="/login" />} />
        <Route path="/git" element={<Navigate to="/login" />} />
      </>
    );
  }

  const canInsights = canAccessInsights(authStatus);
  const canLogs = canAccessLogs(authStatus);

  return (
    <>
      <Route path={SHELL_ROUTE_PATHS.kanban} element={renderAppLayout("kanban")} />
      <Route path={SHELL_ROUTE_PATHS.tasks} element={renderAppLayout("tasks")} />
      <Route path={SHELL_ROUTE_PATHS.skills} element={renderAppLayout("skills")} />
      <Route path={SHELL_ROUTE_PATHS.terminal} element={renderAppLayout("terminal")} />
      <Route path={SHELL_ROUTE_PATHS.memory} element={renderAppLayout("memory")} />
      <Route
        path={SHELL_ROUTE_PATHS.insights}
        element={
          canInsights ? renderAppLayout("insights") : <Navigate to="/chat" replace />
        }
      />
      <Route
        path={SHELL_ROUTE_PATHS.logs}
        element={canLogs ? renderAppLayout("logs") : <Navigate to="/chat" replace />}
      />
      <Route path="/git" element={<Navigate to="/chat" replace />} />
    </>
  );
}

/** Standalone panel views for use inside AppLayout. */
export function ShellKanbanPanel({ onBack }: { onBack: () => void }) {
  return <KanbanPanel onBack={onBack} />;
}

export function ShellTasksPanel({ onBack }: { onBack: () => void }) {
  return <TasksPanel onBack={onBack} />;
}

export function ShellSkillsPanel({ onBack }: { onBack: () => void }) {
  return <SkillsPanel onBack={onBack} />;
}

export type EnsureComposerSessionOptions = {
  navigate?: boolean;
  activate?: boolean;
};

/** M37 — Workspace terminal; session is created on demand when a workspace is selected. */
export function ShellTerminalRoute({
  sessionId,
  workspacePath,
  ensureSession,
  onBack,
}: {
  sessionId: string;
  workspacePath?: string;
  ensureSession?: (options?: EnsureComposerSessionOptions) => Promise<string>;
  onBack: () => void;
}) {
  const [resolvedSessionId, setResolvedSessionId] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const hasWorkspace = Boolean(workspacePath?.trim());

  useEffect(() => {
    let cancelled = false;

    if (!sessionId && !hasWorkspace) {
      setResolvedSessionId(null);
      setResolveError(null);
      setResolving(false);
      return;
    }

    void (async () => {
      setResolving(true);
      setResolveError(null);
      try {
        let id = sessionId;
        if (!id) {
          if (!ensureSession) {
            throw new Error("Cannot start terminal without a session resolver");
          }
          id = await ensureSession({ navigate: false });
        }
        if (!cancelled) {
          setResolvedSessionId(id);
        }
      } catch (err) {
        if (!cancelled) {
          setResolvedSessionId(null);
          setResolveError(
            err instanceof Error ? err.message : "Failed to prepare terminal session",
          );
        }
      } finally {
        if (!cancelled) {
          setResolving(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sessionId, hasWorkspace, ensureSession]);

  if (!sessionId && !hasWorkspace) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-zinc-50 p-6 text-center dark:bg-[#09090b]">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Select a workspace to use the terminal.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
        >
          Back to chat
        </button>
      </div>
    );
  }

  if (resolving || !resolvedSessionId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-zinc-50 p-6 text-center dark:bg-[#09090b]">
        {resolveError ? (
          <>
            <p className="text-sm text-rose-600 dark:text-rose-400">{resolveError}</p>
            <button
              type="button"
              onClick={onBack}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
            >
              Back to chat
            </button>
          </>
        ) : (
          <>
            <Loader2 className="h-8 w-8 animate-spin text-emerald-500" aria-label="Preparing terminal" />
            <p className="text-sm text-zinc-600 dark:text-zinc-400">Preparing workspace terminal…</p>
          </>
        )}
      </div>
    );
  }

  return <ShellTerminalPanel sessionId={resolvedSessionId} onBack={onBack} />;
}

/** M38 — Memory / SOUL / external notes panel. */
export function ShellMemoryPanel({ onBack }: { onBack: () => void }) {
  return <MemoryPanel onBack={onBack} />;
}

export function ShellInsightsPanel({
  onBack,
  authStatus,
}: {
  onBack: () => void;
  authStatus: AuthStatus | null;
}) {
  return <InsightsPanel onBack={onBack} authStatus={authStatus} />;
}

export function ShellLogsPanel({
  onBack,
  authStatus,
}: {
  onBack: () => void;
  authStatus: AuthStatus | null;
}) {
  return <LogsPanel onBack={onBack} authStatus={authStatus} />;
}

/**
 * Scaffold wrapper — pass-through until all routes migrate out of App.tsx.
 */
export function ShellRouter({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
