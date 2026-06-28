import { fetchJson } from "@/lib/api";

export type HermesSessionSummary = {
  id?: string;
  session_id?: string;
  title?: string | null;
  pinned?: boolean;
  [key: string]: unknown;
};

export type HermesSessionDetail = HermesSessionSummary & {
  messages?: unknown[];
  workspace?: string;
};

export type SessionCreateOptions = {
  workspace?: string;
  model?: string;
  modelProvider?: string;
  profile?: string;
  projectId?: string;
  prevSessionId?: string;
  worktree?: boolean;
};

function sessionIdFromRecord(session: Record<string, unknown>): string {
  const sid =
    typeof session.session_id === "string"
      ? session.session_id.trim()
      : typeof session.id === "string"
        ? session.id.trim()
        : "";
  return sid;
}

export function isSessionNotFoundError(err: unknown): boolean {
  return err instanceof Error && /not found/i.test(err.message);
}

export function pickFirstUsableSessionId(
  sessions: Array<{ id?: string; session_id?: string }>,
  rejected?: Set<string>,
): string {
  for (const session of sessions) {
    const id = String(session.id ?? session.session_id ?? "").trim();
    if (!id || rejected?.has(id)) continue;
    return id;
  }
  return "";
}

const SAFE_SESSIONS: { sessions: HermesSessionSummary[] } = { sessions: [] };

export async function listSessions() {
  try {
    return await fetchJson<{ sessions: HermesSessionSummary[] }>("/sessions");
  } catch {
    return SAFE_SESSIONS;
  }
}

export async function getSession(id: string) {
  return fetchJson<{ session: HermesSessionDetail }>("/session", {
    query: { session_id: id },
  });
}

export async function createSession(options: SessionCreateOptions = {}) {
  const body: Record<string, unknown> = {};
  if (options.workspace) body.workspace = options.workspace;
  if (options.model) body.model = options.model;
  if (options.modelProvider) body.model_provider = options.modelProvider;
  if (options.profile) body.profile = options.profile;
  if (options.projectId) body.project_id = options.projectId;
  if (options.prevSessionId) body.prev_session_id = options.prevSessionId;
  if (options.worktree) body.worktree = true;
  return fetchJson<{ session: HermesSessionDetail }>("/session/new", {
    method: "POST",
    body,
  });
}

export async function ensureServerSessionId(
  id: string | undefined,
  serverIds: Set<string>,
  options?: SessionCreateOptions,
): Promise<string> {
  const candidate = id?.trim();
  if (candidate && serverIds.has(candidate)) {
    return candidate;
  }
  const { session } = await createSession(options ?? {});
  const sessionId = sessionIdFromRecord(session as Record<string, unknown>);
  if (!sessionId) {
    throw new Error("Server did not return a session_id");
  }
  return sessionId;
}

export async function deleteSession(id: string) {
  return fetchJson("/session/delete", { method: "POST", body: { session_id: id } });
}

export async function deleteAllSessions() {
  return fetchJson("/sessions/cleanup", { method: "POST" });
}

export async function renameSessionOnFirstMessage(id: string, title: string) {
  return fetchJson("/session/rename", { method: "POST", body: { session_id: id, title } });
}

export async function pinSession(id: string, pinned: boolean) {
  return fetchJson("/session/pin", { method: "POST", body: { session_id: id, pinned } });
}

export async function searchSessions(params?: Record<string, unknown>) {
  const query = params
    ? Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))
    : undefined;
  return fetchJson<{ sessions: HermesSessionSummary[] }>("/sessions/search", { query });
}
