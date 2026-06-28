import type { ChatSession, Message } from "@/types";
import { asString } from "@/services/hermes/chat";

export function toolResultSnippetFromPayload(payload: Record<string, unknown>): string {
  const preview = asString(payload.preview).trim();
  if (preview) return preview;
  const args = payload.args;
  if (args && typeof args === "object") {
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return "";
    }
  }
  return "";
}

export { asString };

/**
 * Map a Hermes session detail (GET /session/:id) → ChatSession.
 * ponytail: passthrough with safe defaults; add real field mapping when backend shape diverges.
 */
export function mapSessionDetailToChatSession(value: unknown): ChatSession {
  const v = (value ?? {}) as Record<string, unknown>;
  const id = String(v.session_id ?? v.id ?? "");
  const activeStreamId =
    typeof v.active_stream_id === "string"
      ? v.active_stream_id
      : typeof v.activeStreamId === "string"
        ? v.activeStreamId
        : undefined;
  return {
    id,
    title: typeof v.title === "string" ? v.title : "Untitled",
    messages: Array.isArray(v.messages) ? mapHermesMessagesToMessages(v.messages) : [],
    updatedAt: typeof v.updated_at === "number" ? v.updated_at : Date.now(),
    pinned: Boolean(v.pinned),
    flowId: typeof v.model === "string" ? v.model : undefined,
    flowName: typeof v.model === "string" ? v.model : undefined,
    messageCount: typeof v.message_count === "number" ? v.message_count : undefined,
    activeStreamId,
    isStreaming: Boolean(activeStreamId),
    compressionAnchor: v.compression_anchor as ChatSession["compressionAnchor"],
    projectId: typeof v.project_id === "string" ? v.project_id : undefined,
  };
}

/**
 * Map Hermes session summaries (GET /sessions) → ChatSession[].
 */
export function mapSessionSummariesToChatSessions(
  summaries: unknown,
): ChatSession[] {
  if (!Array.isArray(summaries)) return [];
  return summaries.map((s) => {
    const raw = (s ?? {}) as Record<string, unknown>;
    const id = String(raw.session_id ?? raw.id ?? "");
    const activeStreamId =
      typeof raw.active_stream_id === "string" ? raw.active_stream_id : undefined;
    return {
      id,
      title: typeof raw.title === "string" ? raw.title : "Untitled",
      messages: [],
      updatedAt: typeof raw.updated_at === "number" ? raw.updated_at : Date.now(),
      pinned: Boolean(raw.pinned),
      flowId: typeof raw.model === "string" ? raw.model : undefined,
      flowName: typeof raw.model === "string" ? raw.model : undefined,
      messageCount: typeof raw.message_count === "number" ? raw.message_count : 0,
      activeStreamId,
      isStreaming: Boolean(activeStreamId),
      projectId: typeof raw.project_id === "string" ? raw.project_id : undefined,
    } satisfies ChatSession;
  });
}

/**
 * Map raw Hermes messages → Message[].
 * ponytail: minimal mapping; extend when backend adds structured tool_calls/steps.
 */
export function mapHermesMessagesToMessages(
  rawMessages: unknown,
  _toolCalls?: unknown,
): Message[] {
  if (!Array.isArray(rawMessages)) return [];
  return rawMessages.map((m, i) => {
    const raw = (m ?? {}) as Record<string, unknown>;
    return {
      id: typeof raw.id === "string" ? raw.id : `msg-${i}`,
      role: raw.role === "user" ? "user" : "assistant",
      content: typeof raw.content === "string" ? raw.content : "",
      timestamp: typeof raw.timestamp === "number" ? raw.timestamp : Date.now(),
      steps: Array.isArray(raw.steps) ? raw.steps : undefined,
    } as Message;
  });
}

export function shouldShowChatSessionInSidebar(): boolean {
  return true;
}
