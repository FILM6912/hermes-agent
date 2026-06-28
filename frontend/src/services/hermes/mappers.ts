import type { ChatSession, Message, ProcessStep } from "@/types";
import { formatClarifyEchoMessage } from "@/features/clarify/utils/formatClarifyEcho";
import { displayVirtualPathsInToolArgs } from "@/services/hermes/displayVirtualPaths";
import {
  combinedReasoningText,
  isDistinctThinking,
} from "@/services/hermes/streamDisplay";

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function parseJsonObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

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

export type HermesLiveToolCall = {
  id: string;
  name: string;
  preview?: string;
  args?: unknown;
  snippet?: string;
  done: boolean;
  cancelled?: boolean;
  isError?: boolean;
  duration?: number;
  afterTextLength?: number;
};

/** Mark incomplete live tool calls as cancelled (stream abort / user stop). */
export function finalizeLiveToolCallsForCancel(
  tools: HermesLiveToolCall[],
): HermesLiveToolCall[] {
  return tools.map((tool) =>
    tool.done ? tool : { ...tool, done: true, cancelled: true },
  );
}

function liveToolStatus(tool: HermesLiveToolCall): ProcessStep["status"] {
  if (!tool.done) return "running";
  if (tool.cancelled) return "cancelled";
  return tool.isError ? "completed" : "completed";
}

function formatToolArgs(args: unknown): string {
  const displayed = displayVirtualPathsInToolArgs(args);
  if (typeof displayed === "string") return displayed;
  if (displayed === undefined || displayed === null) return "";
  try {
    return JSON.stringify(displayed, null, 2);
  } catch {
    return String(displayed);
  }
}

function liveToolCallToProcessStep(tool: HermesLiveToolCall): ProcessStep {
  const argsText = formatToolArgs(tool.args);
  const snippet = asString(tool.snippet) || asString(tool.preview);
  const duration =
    typeof tool.duration === "number" && Number.isFinite(tool.duration)
      ? `${tool.duration}s`
      : undefined;

  return {
    id: tool.id,
    type: tool.isError ? "error" : "command",
    title: tool.name,
    toolName: tool.name,
    preview: tool.preview,
    content: `${argsText ? `Input:\n\`\`\`json\n${argsText}\n\`\`\`` : ""}${snippet ? `\n\nOutput:\n${snippet}` : ""}`,
    duration,
    status: liveToolStatus(tool),
    isExpanded: false,
    afterTextLength: tool.afterTextLength,
  };
}

export function reasoningTextToProcessStep(
  text: string,
  options?: { id?: string; status?: ProcessStep["status"] },
): ProcessStep | null {
  const content = text.trim();
  if (!content) return null;
  return {
    id: options?.id ?? "reasoning-live",
    type: "thinking",
    title: "Reasoning",
    content,
    status: options?.status ?? "running",
    isExpanded: false,
  };
}

/** Build ProcessStep[] from live SSE tool + reasoning state. */
export function buildLiveStreamProcessSteps(options: {
  reasoningText?: string;
  committedReasoning?: string[];
  tools?: HermesLiveToolCall[];
}): ProcessStep[] {
  const steps: ProcessStep[] = [];
  const combined = combinedReasoningText(
    options.committedReasoning ?? [],
    options.reasoningText ?? "",
  );
  const liveTail = (options.reasoningText ?? "").trim();
  const reasoning = reasoningTextToProcessStep(combined, {
    id: "reasoning-live",
    status: liveTail ? "running" : "completed",
  });
  if (reasoning) steps.push(reasoning);

  for (const tool of options.tools ?? []) {
    if (tool.name === "clarify") continue;
    steps.push(liveToolCallToProcessStep(tool));
  }
  return steps;
}

/** Apply an SSE `tool` event to the live tool-call list. */
export function applyStreamToolEvent(
  tools: HermesLiveToolCall[],
  payload: Record<string, unknown>,
  options?: { afterTextLength?: number },
): HermesLiveToolCall[] {
  const name = asString(payload.name, "tool");
  if (name === "clarify") return tools;

  const resultSnippet = toolResultSnippetFromPayload(payload);
  const next: HermesLiveToolCall = {
    id: asString(payload.tid, `live-${name}-${tools.length}`),
    name,
    preview: asString(payload.preview) || undefined,
    args: payload.args ?? {},
    snippet: resultSnippet || undefined,
    done: false,
    afterTextLength: options?.afterTextLength,
  };
  return [...tools, next];
}

/** Apply an SSE `tool_complete` event to the live tool-call list. */
export function applyStreamToolCompleteEvent(
  tools: HermesLiveToolCall[],
  payload: Record<string, unknown>,
  options?: { afterTextLength?: number },
): HermesLiveToolCall[] {
  const name = asString(payload.name, "tool");
  if (name === "clarify") return tools;

  const next = [...tools];
  let target: HermesLiveToolCall | null = null;
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const current = next[i];
    if (!current.done && (!name || current.name === name)) {
      target = current;
      break;
    }
  }

  const resultSnippet = toolResultSnippetFromPayload(
    payload,
    target?.snippet ?? target?.preview ?? "",
  );

  if (!target) {
    next.push({
      id: asString(payload.tid, `live-${name}-${next.length}`),
      name,
      preview: asString(payload.preview) || undefined,
      args: payload.args ?? {},
      snippet: resultSnippet || undefined,
      done: true,
      isError: Boolean(payload.is_error),
      duration: typeof payload.duration === "number" ? payload.duration : undefined,
      afterTextLength: options?.afterTextLength,
    });
    return next;
  }

  const idx = next.indexOf(target);
  next[idx] = {
    ...target,
    preview: asString(payload.preview, target.preview ?? "") || undefined,
    args: payload.args ?? target.args,
    snippet: resultSnippet || undefined,
    done: true,
    isError: Boolean(payload.is_error),
    duration: typeof payload.duration === "number" ? payload.duration : undefined,
  };
  return next;
}

/** Parse clarify tool_complete SSE / snippet JSON into a transcript line. */
export function clarifyEchoContentFromStreamPayload(
  payload: Record<string, unknown>,
): string | null {
  if (asString(payload.name) !== "clarify") return null;
  const parsed =
    parseJsonObject(payload.preview) ??
    parseJsonObject(payload.snippet) ??
    parseJsonObject(payload.args);
  if (!parsed) return null;

  const answer = asString(parsed.user_response).trim();
  if (!answer) return null;

  const question = asString(parsed.question).trim();
  return formatClarifyEchoMessage(question, answer);
}
