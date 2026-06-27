import { fetchJson } from "@/lib/api";

export interface ClarifyPending {
  clarify_id?: string;
  question?: string;
  description?: string;
  choices_offered?: string[];
  choices?: string[];
  session_id?: string;
  expires_at?: number;
  requested_at?: number;
  timeout_seconds?: number;
}

export interface ClarifyPendingResponse {
  pending: ClarifyPending | null;
  pending_count?: number;
}

export interface ClarifyRespondResponse {
  ok: boolean;
  response?: string;
  error?: string;
  stale?: boolean;
}

export async function getClarifyPending(sessionId: string): Promise<ClarifyPendingResponse> {
  return fetchJson<ClarifyPendingResponse>("/clarify/pending", {
    query: { session_id: sessionId },
  });
}

export async function respondClarify(
  sessionId: string,
  response: string,
  clarifyId?: string,
): Promise<ClarifyRespondResponse> {
  return fetchJson<ClarifyRespondResponse>("/clarify/respond", {
    method: "POST",
    body: {
      session_id: sessionId,
      response,
      clarify_id: clarifyId ?? "",
    },
  });
}
