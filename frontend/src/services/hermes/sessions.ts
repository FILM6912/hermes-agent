import { fetchJson } from "@/lib/api";

export type HermesSessionSummary = {
  id: string;
  title?: string | null;
  pinned?: boolean;
  [key: string]: unknown;
};

export type HermesSessionDetail = HermesSessionSummary & {
  messages?: unknown[];
};

export function isSessionNotFoundError(err: unknown): boolean {
  return err instanceof Error && /not found/i.test(err.message);
}

export function pickFirstUsableSessionId(sessions: HermesSessionSummary[]): string {
  return sessions[0]?.id ?? "";
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
  return fetchJson<HermesSessionDetail>("/session", { query: { session_id: id } });
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

export async function ensureServerSessionId(id: string) {
  return id;
}

export async function pinSession(id: string, pinned: boolean) {
  return fetchJson("/session/pin", { method: "POST", body: { session_id: id, pinned } });
}

export async function searchSessions(params?: Record<string, unknown>) {
  const query = params ? Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ) : undefined;
  return fetchJson<{ sessions: HermesSessionSummary[] }>("/sessions/search", { query });
}
