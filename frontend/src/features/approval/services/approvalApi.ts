import { fetchJson } from "@/lib/api";

export type ApprovalChoice = "once" | "session" | "always" | "deny";

export interface ApprovalPending {
  approval_id?: string;
  command?: string;
  description?: string;
  pattern_key?: string;
  pattern_keys?: string[];
  session_id?: string;
}

export interface ApprovalPendingResponse {
  pending: ApprovalPending | null;
  pending_count?: number;
}

export interface ApprovalRespondResponse {
  ok: boolean;
  choice: string;
  error?: string;
}

export async function getApprovalPending(sessionId: string): Promise<ApprovalPendingResponse> {
  return fetchJson<ApprovalPendingResponse>("/approval/pending", {
    query: { session_id: sessionId },
  });
}

export async function respondApproval(
  sessionId: string,
  choice: ApprovalChoice,
  approvalId?: string,
): Promise<ApprovalRespondResponse> {
  return fetchJson<ApprovalRespondResponse>("/approval/respond", {
    method: "POST",
    body: {
      session_id: sessionId,
      choice,
      approval_id: approvalId ?? "",
    },
  });
}
