import { openEventSource } from "@/lib/api";
import type { ProcessStep } from "@/types";
import type { SessionContextUsage } from "@/features/chat/utils/contextUsage";
import { parseContextUsage } from "@/features/chat/utils/contextUsage";
import {
  combinedReasoningText,
} from "@/services/hermes/streamDisplay";
import type { HermesStreamChunk } from "@/services/hermes/streamChat";

type SsePayload = Record<string, unknown>;

export type LiveChatStreamCallbacks = {
  push: (chunk: HermesStreamChunk) => void;
  onSessionTitle?: (sessionId: string, title: string) => void;
  onContextUsage?: (usage: SessionContextUsage) => void;
  onStreamEnd?: () => void;
  onStreamClose?: () => void;
  onError?: (error: unknown) => void;
};

export type LiveChatStreamState = {
  assistantText: string;
  reasoningParts: string[];
  steps: ProcessStep[];
  finished: boolean;
};

const POST_STREAM_CLOSE_MS = 30_000;

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function inferToolStepType(toolName: string): ProcessStep["type"] {
  const key = toolName.trim().toLowerCase();
  if (key.includes("error") || key.includes("fail")) return "error";
  if (key === "terminal" || key === "execute_code" || key === "bash") return "command";
  if (key.includes("write") || key.includes("patch") || key.includes("edit")) return "edit";
  return "success";
}

function toolResultSnippetFromPayload(payload: SsePayload): string {
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

function makeToolStep(
  payload: SsePayload,
  status: ProcessStep["status"],
  afterTextLength: number,
): ProcessStep {
  const toolName = asString(payload.name, "tool");
  const tid = asString(payload.tid, `tool-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
  return {
    id: tid,
    type: inferToolStepType(toolName),
    title: asString(payload.preview, toolName) || toolName,
    content: toolResultSnippetFromPayload(payload) || asString(payload.preview, toolName),
    status,
    toolName,
    preview: asString(payload.preview) || undefined,
    afterTextLength,
  };
}

function upsertRunningToolStep(state: LiveChatStreamState, payload: SsePayload): void {
  if (asString(payload.name) === "clarify") return;
  const tid = asString(payload.tid);
  const existingIdx = state.steps.findIndex(
    (step) => step.id === tid || (step.status === "running" && step.toolName === payload.name),
  );
  const step = makeToolStep(payload, "running", state.assistantText.length);
  if (existingIdx >= 0) {
    state.steps[existingIdx] = { ...state.steps[existingIdx], ...step, status: "running" };
  } else {
    state.steps.push(step);
  }
}

function completeToolStep(state: LiveChatStreamState, payload: SsePayload): void {
  if (asString(payload.name) === "clarify") return;
  let idx = -1;
  for (let i = state.steps.length - 1; i >= 0; i -= 1) {
    const step = state.steps[i];
    if (step.status !== "running") continue;
    if (!payload.name || step.toolName === payload.name) {
      idx = i;
      break;
    }
  }
  const completed = makeToolStep(payload, "completed", state.steps[idx]?.afterTextLength ?? -1);
  if (idx >= 0) {
    state.steps[idx] = {
      ...state.steps[idx],
      ...completed,
      status: "completed",
      content:
        toolResultSnippetFromPayload(payload) ||
        state.steps[idx].content ||
        completed.content,
    };
  } else {
    state.steps.push({ ...completed, status: "completed" });
  }
}

function syncThinkingStep(state: LiveChatStreamState): void {
  const reasoning = combinedReasoningText(state.reasoningParts);
  if (!reasoning.trim()) return;
  const existingIdx = state.steps.findIndex((step) => step.type === "thinking");
  const thinkingStep: ProcessStep = {
    id: existingIdx >= 0 ? state.steps[existingIdx].id : `thinking-${Date.now()}`,
    type: "thinking",
    title: "Thinking",
    content: reasoning,
    status: "running",
  };
  if (existingIdx >= 0) {
    state.steps[existingIdx] = thinkingStep;
  } else {
    state.steps.unshift(thinkingStep);
  }
}

function finalizeThinkingSteps(state: LiveChatStreamState): void {
  state.steps = state.steps.map((step) =>
    step.type === "thinking" && step.status === "running"
      ? { ...step, status: "completed" as const }
      : step,
  );
}

function pushAssistantSnapshot(
  state: LiveChatStreamState,
  callbacks: LiveChatStreamCallbacks,
): void {
  finalizeThinkingSteps(state);
  if (state.steps.length > 0) {
    callbacks.push({ type: "steps", steps: [...state.steps] });
  }
}

function parsePayload(raw: string): SsePayload {
  try {
    const parsed = JSON.parse(raw || "{}");
    return parsed && typeof parsed === "object" ? (parsed as SsePayload) : {};
  } catch {
    return {};
  }
}

/** Map backend `apperror` SSE payload → assistant markdown (legacy messages.js parity). */
export function formatApperrorAssistantContent(payload: SsePayload): string {
  const errType = asString(payload.type);
  const message = asString(payload.message, "An error occurred. Check server logs.");
  const hint = asString(payload.hint).trim();

  let label = "Error";
  if (errType === "cancelled") label = "Task cancelled";
  else if (errType === "interrupted") label = "Response interrupted";
  else if (errType === "quota_exhausted") label = "Out of credits";
  else if (errType === "rate_limit") label = "Rate limit reached";
  else if (errType === "auth_mismatch") label = "Provider mismatch";
  else if (errType === "model_not_found") label = "Model not found";
  else if (errType === "no_response" || errType === "silent_failure") {
    label = "No response from provider";
  }

  const hintSuffix = hint ? `\n\n*${hint}*` : "";
  return `**${label}:** ${message}${hintSuffix}`;
}

/** Keep SSE open briefly after `stream_end` so late `title` events can arrive. */
export function schedulePostStreamEndClose(
  source: EventSource,
  onClose: () => void,
  delayMs = POST_STREAM_CLOSE_MS,
): () => void {
  const timer = window.setTimeout(() => {
    try {
      source.close();
    } catch {
      /* ignore */
    }
    onClose();
  }, delayMs);
  return () => window.clearTimeout(timer);
}

export function wireChatEventSource(options: {
  streamId: string;
  sessionId: string;
  signal?: AbortSignal;
  callbacks: LiveChatStreamCallbacks;
  state: LiveChatStreamState;
}): { close: () => void } {
  const { streamId, sessionId, signal, callbacks, state } = options;
  const source = openEventSource("/chat/stream", { stream_id: streamId });
  let cancelScheduledClose: (() => void) | null = null;
  let closed = false;

  const closeSource = () => {
    if (closed) return;
    closed = true;
    cancelScheduledClose?.();
    cancelScheduledClose = null;
    try {
      source.close();
    } catch {
      /* ignore */
    }
  };

  const handleStreamEnd = () => {
    callbacks.onStreamEnd?.();
    cancelScheduledClose = schedulePostStreamEndClose(source, () => {
      callbacks.onStreamClose?.();
    });
  };

  const handleStreamClose = () => {
    cancelScheduledClose?.();
    cancelScheduledClose = null;
    closeSource();
    callbacks.onStreamClose?.();
  };

  source.addEventListener("token", (event) => {
    const payload = parsePayload(event.data);
    const text = asString(payload.text);
    if (!text) return;
    state.assistantText += text;
    callbacks.push({ type: "text", content: text });
  });

  source.addEventListener("interim_assistant", (event) => {
    const payload = parsePayload(event.data);
    const visible = asString(payload.text).trim();
    if (!visible || payload.already_streamed) return;
    const delta = state.assistantText ? `\n\n${visible}` : visible;
    state.assistantText += delta;
    callbacks.push({ type: "text", content: delta });
  });

  source.addEventListener("reasoning", (event) => {
    const payload = parsePayload(event.data);
    const text = asString(payload.text);
    if (!text) return;
    state.reasoningParts.push(text);
    syncThinkingStep(state);
    callbacks.push({ type: "steps", steps: [...state.steps] });
  });

  source.addEventListener("tool", (event) => {
    upsertRunningToolStep(state, parsePayload(event.data));
    syncThinkingStep(state);
    callbacks.push({ type: "steps", steps: [...state.steps] });
  });

  source.addEventListener("tool_complete", (event) => {
    completeToolStep(state, parsePayload(event.data));
    callbacks.push({ type: "steps", steps: [...state.steps] });
  });

  source.addEventListener("title", (event) => {
    const payload = parsePayload(event.data);
    const sid = asString(payload.session_id, sessionId);
    const title = asString(payload.title).trim();
    if (!title || sid !== sessionId) return;
    callbacks.onSessionTitle?.(sid, title);
  });

  source.addEventListener("done", (event) => {
    const payload = parsePayload(event.data);
    const usage = parseContextUsage(payload.usage as Record<string, unknown> | undefined);
    if (usage) callbacks.onContextUsage?.(usage);
    const session = payload.session as SsePayload | undefined;
    const title = session ? asString(session.title).trim() : "";
    if (title) callbacks.onSessionTitle?.(sessionId, title);
    pushAssistantSnapshot(state, callbacks);
  });

  source.addEventListener("stream_end", () => {
    pushAssistantSnapshot(state, callbacks);
    handleStreamEnd();
  });

  source.addEventListener("stream_close", () => {
    handleStreamClose();
  });

  source.addEventListener("apperror", (event) => {
    state.finished = true;
    const payload = parsePayload((event as MessageEvent).data);
    const content = formatApperrorAssistantContent(payload);
    const delta = state.assistantText ? `\n\n${content}` : content;
    state.assistantText += delta;
    callbacks.push({ type: "text", content: delta });
    pushAssistantSnapshot(state, callbacks);
    callbacks.onStreamEnd?.();
    handleStreamClose();
  });

  source.addEventListener("error", (event) => {
    const payload = parsePayload((event as MessageEvent).data);
    callbacks.onError?.(new Error(asString(payload.error, "Stream error")));
    closeSource();
  });

  source.addEventListener("cancel", () => {
    closeSource();
  });

  source.onerror = () => {
    if (closed || state.finished) return;
    callbacks.onError?.(new Error("Chat stream connection error"));
    closeSource();
  };

  const onAbort = () => {
    closeSource();
  };
  signal?.addEventListener("abort", onAbort, { once: true });

  return {
    close: () => {
      signal?.removeEventListener("abort", onAbort);
      closeSource();
    },
  };
}

export { toolResultSnippetFromPayload, asString };
