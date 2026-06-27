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

export async function listSessions() {
  return fetchJson<{ sessions: HermesSessionSummary[] }>("/sessions");
}

export async function getSession(id: string) {
  return fetchJson<HermesSessionDetail>(`/sessions/${encodeURIComponent(id)}`);
}

export async function deleteSession(id: string) {
  return fetchJson("/sessions/delete", { method: "POST", body: { id } });
}

export async function deleteAllSessions() {
  return fetchJson("/sessions/delete-all", { method: "POST" });
}

export async function renameSessionOnFirstMessage(id: string, title: string) {
  return fetchJson("/sessions/rename", { method: "POST", body: { id, title } });
}

export async function ensureServerSessionId(id: string) {
  return id;
}

export async function pinSession(id: string, pinned: boolean) {
  return fetchJson("/sessions/pin", { method: "POST", body: { id, pinned } });
}

export async function searchSessions(params?: Record<string, unknown>) {
  const query = params ? Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, String(v)]),
  ) : undefined;
  return fetchJson<{ sessions: HermesSessionSummary[] }>("/sessions/search", { query });
}
