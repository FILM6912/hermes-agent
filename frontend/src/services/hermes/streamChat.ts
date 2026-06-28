/**
 * Hermes chat streaming adapter — SSE tokens + tool/reasoning steps → Agent-UI chunks.
 */
import type { Attachment, ModelConfig, ProcessStep } from "@/types";
import {
  applyStreamToolCompleteEvent,
  applyStreamToolEvent,
  buildLiveStreamProcessSteps,
  clarifyEchoContentFromStreamPayload,
  finalizeLiveToolCallsForCancel,
  type HermesLiveToolCall,
} from "./mappers";
import { finalizeRunningProcessSteps } from "@/features/chat/utils/finalizeRunningProcessSteps";
import { modelProviderForHermes } from "./models";
import {
  cancelChatStream,
  getChatStreamStatus,
  startChatTurn,
  subscribeChatStream,
} from "./chat";
import { formatChatMessageWithAttachments } from "./attachments";
import {
  combinedReasoningText,
  isDistinctThinking,
  stripThinkingFromAssistantStream,
} from "./streamDisplay";
import type { HermesChatStartResult } from "@/types/hermes/chat";
import type { HermesSubscribeChatStreamOptions } from "@/types/hermes/chat";
import {
  parseContextUsage,
  type SessionContextUsage,
} from "@/features/chat/utils/contextUsage";

export { cancelChatStream } from "./chat";

export type HermesStreamChunk = {
  type: "text" | "steps" | "clarify_echo" | "turn_end";
  content?: string;
  steps?: ProcessStep[];
  isFullText?: boolean;
};

export type StreamHermesChatOptions = {
  sessionId: string;
  message: string;
  modelConfig: ModelConfig;
  workspace?: string;
  profile?: string;
  attachments?: Attachment[];
  signal?: AbortSignal;
  /** Called after POST /chat/start succeeds (before SSE subscription). */
  onChatStart?: (result: HermesChatStartResult) => void;
  /** Called when the server publishes an LLM-generated session title (`title` SSE). */
  onSessionTitle?: (sessionId: string, title: string) => void;
  /** Called when token/context usage updates (`metering`, `done`, `compressed` SSE). */
  onContextUsage?: (usage: SessionContextUsage) => void;
};

export type ReattachHermesChatStreamOptions = {
  streamId: string;
  sessionId: string;
  signal?: AbortSignal;
  onSessionTitle?: (sessionId: string, title: string) => void;
  onContextUsage?: (usage: SessionContextUsage) => void;
};

/** Map composer attachments to Hermes chat/start upload payloads. */
function attachmentsForChatStart(attachments?: Attachment[]) {
  if (!attachments?.length) return [];
  return attachments.map((att) => ({
    name: att.name,
    path:
      att.workspace_rel?.trim() ||
      att.path?.trim() ||
      (att.content?.startsWith("blob:") ? "" : att.content?.trim()) ||
      "",
    mime: att.mimeType || "",
    is_image: att.type === "image",
    ...(att.workspace_rel?.trim()
      ? { workspace_rel: att.workspace_rel.trim() }
      : {}),
    ...(typeof att.size === "number" ? { size: att.size } : {}),
  }));
}

type StreamQueueState = {
  queue: HermesStreamChunk[];
  wake: (() => void) | null;
  finished: boolean;
  streamError: Error | null;
  closeSse: (() => void) | null;
  reasoningText: string;
  committedReasoning: string[];
  assistantRawText: string;
  lastPushedDisplayText: string;
  liveTools: HermesLiveToolCall[];
};

function createStreamQueueState(): StreamQueueState {
  return {
    queue: [],
    wake: null,
    finished: false,
    streamError: null,
    closeSse: null,
    reasoningText: "",
    committedReasoning: [],
    assistantRawText: "",
    lastPushedDisplayText: "",
    liveTools: [],
  };
}

function commitLiveReasoning(state: StreamQueueState) {
  const segment = state.reasoningText.trim();
  if (segment) {
    state.committedReasoning.push(segment);
  }
  state.reasoningText = "";
}

function pushDisplayTextFromRaw(state: StreamQueueState) {
  const display = stripThinkingFromAssistantStream(state.assistantRawText);
  const reasoning = combinedReasoningText(
    state.committedReasoning,
    state.reasoningText,
  );
  if (reasoning && !isDistinctThinking(reasoning, display)) {
    if (!display.trim()) return;
  }
  const last = state.lastPushedDisplayText ?? "";
  if (display === last) return;
  state.lastPushedDisplayText = display;
  if (display.length > last.length) {
    pushChunk(state, { type: "text", content: display.slice(last.length) });
  } else if (display.length < last.length) {
    pushChunk(state, { type: "text", content: display, isFullText: true });
  }
}

function notifyQueue(state: StreamQueueState) {
  state.wake?.();
  state.wake = null;
}

function pushChunk(state: StreamQueueState, chunk: HermesStreamChunk) {
  state.queue.push(chunk);
  notifyQueue(state);
}

function pushStepsFromState(state: StreamQueueState, finalizeCancelled = false) {
  const display = stripThinkingFromAssistantStream(state.assistantRawText);
  let steps = buildLiveStreamProcessSteps({
    reasoningText: state.reasoningText,
    committedReasoning: state.committedReasoning,
    tools: state.liveTools,
  }).filter((step) => {
    if (step.type !== "thinking") return true;
    return isDistinctThinking(step.content, display);
  });
  if (finalizeCancelled) {
    steps = finalizeRunningProcessSteps(steps) ?? steps;
  }
  if (steps.length > 0) {
    pushChunk(state, { type: "steps", steps });
  }
}

function finalizeStreamStateForCancel(state: StreamQueueState) {
  state.liveTools = finalizeLiveToolCallsForCancel(state.liveTools);
  commitLiveReasoning(state);
  pushStepsFromState(state, true);
  pushDisplayTextFromRaw(state);
}

function subscribeHermesStreamToQueue(
  state: StreamQueueState,
  streamId: string,
  sessionId: string,
  subscribeOptions: HermesSubscribeChatStreamOptions,
  onSessionTitle?: (sessionId: string, title: string) => void,
  onContextUsage?: (usage: SessionContextUsage) => void,
) {
  const emitContextUsage = (raw: Record<string, unknown> | undefined) => {
    const parsed = parseContextUsage(raw);
    if (parsed) onContextUsage?.(parsed);
  };

  state.closeSse = subscribeChatStream(
    streamId,
    {
      onTextDelta: (text) => {
        if (!text) return;
        state.assistantRawText += text;
        pushDisplayTextFromRaw(state);
      },
      onReasoningDelta: (text) => {
        if (!text) return;
        state.reasoningText += text;
        pushStepsFromState(state);
      },
      onTool: (payload) => {
        commitLiveReasoning(state);
        const afterTextLength = state.lastPushedDisplayText.length;
        state.liveTools = applyStreamToolEvent(state.liveTools, payload, {
          afterTextLength,
        });
        pushDisplayTextFromRaw(state);
        pushStepsFromState(state);
      },
      onToolComplete: (payload) => {
        const echo = clarifyEchoContentFromStreamPayload(payload);
        if (echo) {
          pushChunk(state, { type: "clarify_echo", content: echo });
        }
        const afterTextLength = state.lastPushedDisplayText.length;
        state.liveTools = applyStreamToolCompleteEvent(state.liveTools, payload, {
          afterTextLength,
        });
        pushDisplayTextFromRaw(state);
        pushStepsFromState(state);
      },
      onDone: (payload) => {
        commitLiveReasoning(state);
        pushStepsFromState(state);
        pushDisplayTextFromRaw(state);
        emitContextUsage(payload.usage);
      },
      onMetering: (payload) => {
        if ((payload.session_id || sessionId) !== sessionId) return;
        emitContextUsage(payload.usage);
      },
      onCompressed: (payload) => {
        const eventSid =
          payload.old_session_id || payload.session_id || sessionId;
        if (eventSid !== sessionId && payload.new_session_id !== sessionId) {
          return;
        }
        emitContextUsage(payload.usage);
      },
      onTitle: (payload) => {
        const sid =
          typeof payload.session_id === "string" ? payload.session_id : sessionId;
        const title =
          typeof payload.title === "string" ? payload.title.trim() : "";
        if (title) onSessionTitle?.(sid, title);
      },
      onStreamEnd: () => {
        commitLiveReasoning(state);
        pushStepsFromState(state);
        pushDisplayTextFromRaw(state);
        pushChunk(state, { type: "turn_end" });
      },
      onStreamClose: () => {
        state.finished = true;
        notifyQueue(state);
      },
      onError: (payload) => {
        const detail =
          (typeof payload.details === "string" && payload.details.trim()) ||
          (typeof payload.message === "string" && payload.message.trim()) ||
          "";
        state.streamError = new Error(detail || "Chat stream failed");
        state.finished = true;
        notifyQueue(state);
      },
    },
    subscribeOptions,
  );
}

async function* drainHermesStreamQueue(
  state: StreamQueueState,
  signal: AbortSignal | undefined,
  streamId: string | null,
): AsyncGenerator<HermesStreamChunk, void, unknown> {
  const wait = () =>
    new Promise<void>((resolve) => {
      state.wake = resolve;
    });

  const onAbort = () => {
    finalizeStreamStateForCancel(state);
    if (streamId) {
      void cancelChatStream(streamId).catch(() => undefined);
    }
    state.closeSse?.();
    state.finished = true;
    notifyQueue(state);
  };

  signal?.addEventListener("abort", onAbort);

  try {
    while (true) {
      while (state.queue.length > 0) {
        yield state.queue.shift()!;
      }

      if (signal?.aborted) {
        throw new DOMException("The user aborted a request.", "AbortError");
      }

      if (state.finished) {
        if (state.streamError) throw state.streamError;
        break;
      }

      await wait();
    }
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}

export async function* reattachHermesChatStream(
  options: ReattachHermesChatStreamOptions,
): AsyncGenerator<HermesStreamChunk, void, unknown> {
  const { streamId, sessionId, signal, onSessionTitle, onContextUsage } = options;
  const trimmedId = streamId.trim();
  if (!trimmedId) return;

  const status = await getChatStreamStatus(trimmedId);
  if (!status.active && !status.replay_available) {
    return;
  }

  const state = createStreamQueueState();
  const subscribeOptions: HermesSubscribeChatStreamOptions =
    !status.active && status.replay_available ? { replay: true } : {};

  subscribeHermesStreamToQueue(
    state,
    trimmedId,
    sessionId,
    subscribeOptions,
    onSessionTitle,
    onContextUsage,
  );

  yield* drainHermesStreamQueue(state, signal, trimmedId);
}

export async function* streamHermesChat(
  options: StreamHermesChatOptions,
): AsyncGenerator<HermesStreamChunk, void, unknown> {
  const {
    sessionId,
    message,
    modelConfig,
    workspace,
    profile,
    attachments,
    signal,
    onChatStart,
    onSessionTitle,
    onContextUsage,
  } = options;

  const state = createStreamQueueState();
  let streamId: string | null = null;

  try {
    const modelProvider = modelProviderForHermes(modelConfig);
    const start = await startChatTurn({
      session_id: sessionId,
      message: formatChatMessageWithAttachments(message, attachments),
      model: modelConfig.modelId,
      ...(workspace ? { workspace } : {}),
      ...(profile ? { profile } : {}),
      ...(modelProvider ? { model_provider: modelProvider } : {}),
      attachments: attachmentsForChatStart(attachments),
    });

    onChatStart?.(start);
    streamId = start.stream_id;

    subscribeHermesStreamToQueue(
      state,
      streamId,
      sessionId,
      {},
      onSessionTitle,
      onContextUsage,
    );

    yield* drainHermesStreamQueue(state, signal, streamId);
  } catch (error) {
    state.closeSse?.();
    throw error;
  }
}

export type { HermesChatStartResult };
