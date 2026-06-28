/**
 * Helpers to ensure chat uses server-backed session ids only.
 */
import { HermesApiError } from "@/lib/api";
import type { CreateSessionOptions } from "@/types/hermes/sessions";
import { createSessionId } from "./sessions";

/** True when the API rejected a session lookup or chat/start for a missing session. */
export function isSessionNotFoundError(error: unknown): boolean {
  if (error instanceof HermesApiError && error.status === 404) {
    return true;
  }
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "";
  return /session not found/i.test(message);
}

/** Drop session ids that failed GET /session (ghost list rows). */
export function filterRejectedSessionIds(
  ids: Iterable<string>,
  rejected: ReadonlySet<string>,
): Set<string> {
  const usable = new Set<string>();
  for (const id of ids) {
    if (!rejected.has(id)) usable.add(id);
  }
  return usable;
}

/** First session summary id that is not rejected, if any. */
export function pickFirstUsableSessionId(
  sessions: ReadonlyArray<{ id: string }>,
  rejected: ReadonlySet<string>,
): string | undefined {
  return sessions.find((s) => !rejected.has(s.id))?.id;
}

/**
 * Return `candidateId` when it is known to the server; otherwise POST /session/new.
 * Mutates `knownServerIds` when a new id is created.
 */
export async function ensureServerSessionId(
  candidateId: string | undefined,
  knownServerIds: Set<string>,
  options: CreateSessionOptions = {},
): Promise<string> {
  if (candidateId && knownServerIds.has(candidateId)) {
    return candidateId;
  }
  const sessionId = await createSessionId(options);
  knownServerIds.add(sessionId);
  return sessionId;
}
