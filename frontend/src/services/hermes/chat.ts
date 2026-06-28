import { fetchJson, openEventSource } from "@/lib/api";
import type { ChatSession } from "@/types";
import type {
  HermesChatCancelResult,
  HermesChatStreamStatusResult,
  HermesChatStartBody,
  HermesChatStartResult,
  HermesChatStreamDonePayload,
  HermesChatStreamEndPayload,
  HermesChatStreamClosePayload,
  HermesChatStreamErrorPayload,
  HermesChatStreamHandlers,
  HermesChatStreamMeteringPayload,
  HermesChatStreamCompressedPayload,
  HermesChatStreamReasoningPayload,
  HermesChatStreamTitlePayload,
  HermesChatStreamTokenPayload,
  HermesChatStreamToolPayload,
  HermesSubscribeChatStreamOptions,
} from "@/types/hermes/chat";
import { mapSessionDetailToChatSession } from "./mappers";
import { getSession } from "./sessions";

export type {
  HermesChatCancelResult,
  HermesChatStartBody,
  HermesChatStartResult,
  HermesChatStreamDonePayload,
  HermesChatStreamEndPayload,
  HermesChatStreamErrorPayload,
  HermesChatStreamHandlers,
  HermesChatStreamMeteringPayload,
  HermesChatStreamCompressedPayload,
  HermesChatStreamReasoningPayload,
  HermesChatStreamTitlePayload,
  HermesChatStreamTokenPayload,
  HermesChatStreamToolPayload,
  HermesSubscribeChatStreamOptions,
} from "@/types/hermes/chat";

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseSseData<T extends Record<string, unknown>>(raw: string, fallback: T): T {
  if (!raw) return fallback;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return isRecord(parsed) ? ({ ...fallback, ...parsed } as T) : fallback;
  } catch {
    return fallback;
  }
}

/** Map backend `apperror` SSE payload → assistant markdown (legacy messages.js parity). */
export function formatApperrorAssistantContent(payload: Record<string, unknown>): string {
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

/** Start a chat turn; returns the server-assigned `stream_id` for SSE subscription. */
export async function startChatTurn(body: HermesChatStartBody): Promise<HermesChatStartResult> {
  return fetchJson<HermesChatStartResult>("/chat/start", {
    method: "POST",
    body,
  });
}

/** Cancel an in-flight chat stream (`GET /api/v1/chat/cancel`). */
export async function cancelChatStream(streamId: string): Promise<HermesChatCancelResult> {
  return fetchJson<HermesChatCancelResult>("/chat/cancel", {
    query: { stream_id: streamId },
  });
}

/** Poll whether a stream worker is live and whether journal replay is available. */
export async function getChatStreamStatus(
  streamId: string,
): Promise<HermesChatStreamStatusResult> {
  return fetchJson<HermesChatStreamStatusResult>("/chat/stream/status", {
    query: { stream_id: streamId },
  });
}

/** Load full session detail + mapped message history for chat open. */
export async function loadChatSession(sessionId: string): Promise<ChatSession> {
  const { session } = await getSession(sessionId);
  return mapSessionDetailToChatSession(session);
}

/** Subscribe to live chat SSE for a `stream_id`. Returns a `close` function. */
export function subscribeChatStream(
  streamId: string,
  handlers: HermesChatStreamHandlers,
  options: HermesSubscribeChatStreamOptions = {},
): () => void {
  const query: Record<string, string | number | boolean | undefined | null> = {
    stream_id: streamId,
  };
  if (options.afterSeq !== undefined) {
    query.after_seq = options.afterSeq;
  }
  if (options.replay) {
    query.replay = 1;
  }

  const source = openEventSource("/chat/stream", query);
  let closed = false;
  let terminal = false;
  let streamEnded = false;
  let streamCloseNotified = false;
  let postEndCloseTimer: ReturnType<typeof setTimeout> | null = null;

  const clearPostEndCloseTimer = () => {
    if (postEndCloseTimer == null) return;
    clearTimeout(postEndCloseTimer);
    postEndCloseTimer = null;
  };

  const notifyStreamClose = (payload: HermesChatStreamClosePayload = {}) => {
    if (streamCloseNotified) return;
    streamCloseNotified = true;
    handlers.onStreamClose?.(payload);
  };

  const close = () => {
    if (closed) return;
    closed = true;
    terminal = true;
    clearPostEndCloseTimer();
    source.close();
  };

  const schedulePostStreamEndClose = () => {
    if (postEndCloseTimer != null || closed) return;
    postEndCloseTimer = setTimeout(() => {
      if (closed) return;
      notifyStreamClose();
      close();
    }, 60_000);
  };

  const turnFinished = () => terminal || streamEnded;

  const handleToken = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamTokenPayload>(event.data, {});
    const text = typeof payload.text === "string" ? payload.text : "";
    if (text) handlers.onTextDelta?.(text, payload);
  };

  const handleReasoning = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamReasoningPayload>(event.data, {});
    const text = typeof payload.text === "string" ? payload.text : "";
    if (text) handlers.onReasoningDelta?.(text, payload);
  };

  const handleTool = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamToolPayload>(event.data, {});
    if (payload.name === "clarify") return;
    handlers.onTool?.(payload);
  };

  const handleToolComplete = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamToolPayload>(event.data, {});
    handlers.onToolComplete?.({ ...payload, done: true });
  };

  const handleDone = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamDonePayload>(event.data, {});
    handlers.onDone?.(payload);
  };

  const handleMetering = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamMeteringPayload>(event.data, {});
    handlers.onMetering?.(payload);
  };

  const handleCompressed = (event: MessageEvent) => {
    if (turnFinished()) return;
    const payload = parseSseData<HermesChatStreamCompressedPayload>(event.data, {});
    handlers.onCompressed?.(payload);
  };

  const handleTitle = (event: MessageEvent) => {
    if (closed) return;
    const payload = parseSseData<HermesChatStreamTitlePayload>(event.data, {});
    handlers.onTitle?.(payload);
  };

  const handleStreamEnd = (event: MessageEvent) => {
    if (streamEnded || terminal) return;
    streamEnded = true;
    const payload = parseSseData<HermesChatStreamEndPayload>(event.data, {});
    handlers.onStreamEnd?.(payload);
    schedulePostStreamEndClose();
  };

  const handleStreamClose = (event: MessageEvent) => {
    if (closed) return;
    const payload = parseSseData<HermesChatStreamClosePayload>(event.data, {});
    notifyStreamClose(payload);
    close();
  };

  const handleAppError = (event: MessageEvent) => {
    if (terminal) return;
    terminal = true;
    const payload = parseSseData<HermesChatStreamErrorPayload>(event.data, {
      message: "An error occurred.",
    });
    handlers.onError?.(payload);
    close();
  };

  const handleNamedError = (event: MessageEvent) => {
    if (terminal) return;
    if (!event.data) return;
    handleAppError(event);
  };

  source.addEventListener("token", handleToken);
  source.addEventListener("reasoning", handleReasoning);
  source.addEventListener("tool", handleTool);
  source.addEventListener("tool_complete", handleToolComplete);
  source.addEventListener("done", handleDone);
  source.addEventListener("metering", handleMetering);
  source.addEventListener("compressed", handleCompressed);
  source.addEventListener("title", handleTitle);
  source.addEventListener("stream_end", handleStreamEnd);
  source.addEventListener("stream_close", handleStreamClose);
  source.addEventListener("apperror", handleAppError);
  source.addEventListener("error", handleNamedError);

  source.onerror = () => {
    if (closed || terminal) return;
    if (streamEnded) {
      notifyStreamClose();
      close();
      return;
    }
    terminal = true;
    handlers.onError?.({
      message: "Connection lost",
      type: "transport",
    });
    close();
  };

  return close;
}
