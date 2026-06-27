import type { ChatSession } from "@/types";

export type SessionMap = Record<string, ChatSession>;

/** Merge or replace one session in the map. */
export function upsertSessionInMap(
  prev: SessionMap,
  id: string,
  session: ChatSession,
): SessionMap {
  return { ...prev, [id]: session };
}

/** Update one session when it exists; otherwise return prev unchanged. */
export function updateSessionInMap(
  prev: SessionMap,
  id: string,
  updater: (session: ChatSession) => ChatSession,
): SessionMap {
  const existing = prev[id];
  if (!existing) return prev;
  return { ...prev, [id]: updater(existing) };
}

/** Remove one session from the map when present. */
export function removeSessionFromMap(prev: SessionMap, id: string): SessionMap {
  if (!prev[id]) return prev;
  const next = { ...prev };
  delete next[id];
  return next;
}

export function addConfirmedSessionId(prev: Set<string>, id: string): Set<string> {
  if (prev.has(id)) return prev;
  const next = new Set(prev);
  next.add(id);
  return next;
}

export function removeConfirmedSessionId(prev: Set<string>, id: string): Set<string> {
  if (!prev.has(id)) return prev;
  const next = new Set(prev);
  next.delete(id);
  return next;
}
