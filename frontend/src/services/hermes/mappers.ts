import type { ChatSession, Message, ProcessStep } from "@/types";
import { asString } from "@/services/hermes/chat";
import { isDistinctThinking } from "@/services/hermes/streamDisplay";

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

function messageTimestamp(raw: Record<string, unknown>): number {
  if (typeof raw.timestamp === "number") return raw.timestamp;
  if (typeof raw._ts === "number") return raw._ts * 1000;
  return Date.now();
}

/** Visible assistant text from string or structured content[] (legacy ui.js parity). */
export function extractHermesMessageContent(raw: Record<string, unknown>): string {
  const content = raw.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part): part is Record<string, unknown> => !!part && typeof part === "object")
    .filter((part) => {
      const type = asString(part.type).toLowerCase();
      return type === "text" || (!type && (part.text || part.content));
    })
    .map((part) => asString(part.text) || asString(part.content))
    .filter(Boolean)
    .join("\n");
}

/** Reasoning trace from API `reasoning` or structured content[] blocks. */
export function extractHermesMessageReasoning(
  raw: Record<string, unknown>,
  visibleContent: string,
): string {
  const topLevel =
    asString(raw.reasoning).trim() || asString(raw.reasoning_content).trim();
  if (topLevel) return topLevel;

  const content = raw.content;
  if (!Array.isArray(content)) return "";

  return content
    .filter((part): part is Record<string, unknown> => !!part && typeof part === "object")
    .filter((part) => {
      const type = asString(part.type).toLowerCase();
      return type === "thinking" || type === "reasoning";
    })
    .map(
      (part) =>
        asString(part.thinking) ||
        asString(part.reasoning) ||
        asString(part.text),
    )
    .filter(Boolean)
    .join("\n");
}

function thinkingStepFromReasoning(reasoning: string, index: number): ProcessStep {
  return {
    id: `thinking-hist-${index}`,
    type: "thinking",
    title: "Thinking",
    content: reasoning,
    status: "completed",
  };
}

function mergeHistoryThinkingStep(
  rawSteps: unknown,
  reasoning: string,
  index: number,
): ProcessStep[] | undefined {
  const steps = Array.isArray(rawSteps) ? (rawSteps as ProcessStep[]) : [];
  if (steps.some((step) => step.type === "thinking")) return steps.length ? steps : undefined;
  return [thinkingStepFromReasoning(reasoning, index), ...steps];
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
    const role = raw.role === "user" ? "user" : "assistant";
    const content = extractHermesMessageContent(raw);
    let steps = Array.isArray(raw.steps) ? (raw.steps as ProcessStep[]) : undefined;

    if (role === "assistant") {
      const reasoning = extractHermesMessageReasoning(raw, content);
      if (reasoning && isDistinctThinking(reasoning, content)) {
        steps = mergeHistoryThinkingStep(steps, reasoning, i);
      }
    }

    return {
      id: typeof raw.id === "string" ? raw.id : `msg-${i}`,
      role,
      content,
      timestamp: messageTimestamp(raw),
      steps,
    } as Message;
  });
}

export function shouldShowChatSessionInSidebar(): boolean {
  return true;
}
