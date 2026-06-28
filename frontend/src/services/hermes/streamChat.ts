import { fetchJson } from "@/lib/api";
import type { Attachment, ModelConfig, ProcessStep } from "@/types";
import type { SessionContextUsage } from "@/features/chat/utils/contextUsage";
import type { HermesChatStartResult } from "@/types/hermes/chat";
import { finalizeRunningProcessSteps } from "@/features/chat/utils/finalizeRunningProcessSteps";
import { modelProviderForHermes } from "@/services/hermes/models";
import {
  wireChatEventSource,
  type LiveChatStreamState,
} from "@/services/hermes/chat";

export type HermesStreamChunk =
  | { type: "text"; content: string }
  | { type: "steps"; steps: ProcessStep[] }
  | { type: "turn_end" };

export type StreamHermesChatOptions = {
  sessionId: string;
  message: string;
  modelConfig: ModelConfig;
  workspace?: string;
  profile?: string;
  attachments?: Attachment[];
  signal?: AbortSignal;
  onChatStart?: (start: HermesChatStartResult) => void;
  onSessionTitle?: (sessionId: string, title: string) => void;
  onContextUsage?: (usage: SessionContextUsage) => void;
};

export type ReattachHermesChatStreamOptions = {
  streamId: string;
  sessionId: string;
  signal?: AbortSignal;
  onSessionTitle?: (sessionId: string, title: string) => void;
  onContextUsage?: (usage: SessionContextUsage) => void;
};

type ChatStartBody = {
  session_id: string;
  message: string;
  model: string;
  workspace?: string;
  model_provider?: string | null;
  profile?: string;
  attachments?: Array<{ name: string; path: string }>;
};

function chatStartBody(options: StreamHermesChatOptions): ChatStartBody {
  const modelProvider = modelProviderForHermes(options.modelConfig);
  const body: ChatStartBody = {
    session_id: options.sessionId,
    message: options.message,
    model: options.modelConfig.modelId,
    profile: options.profile || "default",
    model_provider: modelProvider ?? null,
  };
  if (options.workspace) body.workspace = options.workspace;
  const attachments = (options.attachments ?? [])
    .map((attachment) => {
      const path = (attachment.path || attachment.content || "").trim();
      if (!path) return null;
      return { name: attachment.name, path };
    })
    .filter(Boolean) as Array<{ name: string; path: string }>;
  if (attachments.length > 0) body.attachments = attachments;
  return body;
}

function createChunkQueue() {
  const pending: HermesStreamChunk[] = [];
  let notify: (() => void) | null = null;
  let done = false;
  let failure: unknown = null;

  const wake = () => {
    notify?.();
    notify = null;
  };

  return {
    push(chunk: HermesStreamChunk) {
      pending.push(chunk);
      wake();
    },
    finish() {
      done = true;
      wake();
    },
    fail(error: unknown) {
      failure = error;
      done = true;
      wake();
    },
    async *iterate(): AsyncGenerator<HermesStreamChunk, void, unknown> {
      while (true) {
        while (pending.length > 0) {
          yield pending.shift()!;
        }
        if (done) {
          if (failure) throw failure;
          return;
        }
        await new Promise<void>((resolve) => {
          notify = resolve;
        });
      }
    },
  };
}

function finalizeLiveToolCallsForCancel(steps: ProcessStep[]): ProcessStep[] {
  return finalizeRunningProcessSteps(steps) ?? steps;
}

function finalizeStreamStateForCancel(
  state: LiveChatStreamState,
): HermesStreamChunk[] {
  const steps = finalizeLiveToolCallsForCancel(state.steps);
  const chunks: HermesStreamChunk[] = [];
  if (steps.length > 0) {
    chunks.push({ type: "steps", steps });
  }
  chunks.push({ type: "turn_end" });
  return chunks;
}

async function* iterLiveChatStream(options: {
  streamId: string;
  sessionId: string;
  signal?: AbortSignal;
  onSessionTitle?: (sessionId: string, title: string) => void;
  onContextUsage?: (usage: SessionContextUsage) => void;
}): AsyncGenerator<HermesStreamChunk, void, unknown> {
  const queue = createChunkQueue();
  const state: LiveChatStreamState = {
    assistantText: "",
    reasoningParts: [],
    steps: [],
    finished: false,
  };

  let connection: { close: () => void } | null = null;

  const abortIfNeeded = () => {
    if (!options.signal?.aborted) return false;
    for (const chunk of finalizeStreamStateForCancel(state)) {
      queue.push(chunk);
    }
    connection?.close();
    queue.finish();
    return true;
  };

  connection = wireChatEventSource({
    streamId: options.streamId,
    sessionId: options.sessionId,
    signal: options.signal,
    state,
    callbacks: {
      push: (chunk) => {
        if (abortIfNeeded()) return;
        queue.push(chunk);
      },
      onSessionTitle: options.onSessionTitle,
      onContextUsage: options.onContextUsage,
      onStreamEnd: () => {
        if (abortIfNeeded()) return;
        queue.push({ type: "turn_end" });
      },
      onStreamClose: () => {
        state.finished = true;
        connection?.close();
        queue.finish();
      },
      onError: (error) => {
        if (options.signal?.aborted) {
          abortIfNeeded();
          return;
        }
        queue.fail(error);
      },
    },
  });

  options.signal?.addEventListener(
    "abort",
    () => {
      for (const chunk of finalizeStreamStateForCancel(state)) {
        queue.push(chunk);
      }
      connection?.close();
      queue.finish();
    },
    { once: true },
  );

  try {
    yield* queue.iterate();
  } finally {
    connection?.close();
  }
}

export function streamHermesChat(
  options: StreamHermesChatOptions,
): AsyncGenerator<HermesStreamChunk, void, unknown> {
  return (async function* () {
    const start = await fetchJson<HermesChatStartResult>("/chat/start", {
      method: "POST",
      body: chatStartBody(options),
      signal: options.signal,
    });

    options.onChatStart?.(start);

    const streamId = typeof start.stream_id === "string" ? start.stream_id.trim() : "";
    if (!streamId) {
      throw new Error("Server did not return stream_id");
    }

    if (start.title) {
      options.onSessionTitle?.(options.sessionId, start.title);
    }

    yield* iterLiveChatStream({
      streamId,
      sessionId: options.sessionId,
      signal: options.signal,
      onSessionTitle: options.onSessionTitle,
      onContextUsage: options.onContextUsage,
    });
  })();
}

export function reattachHermesChatStream(
  options: ReattachHermesChatStreamOptions,
): AsyncGenerator<HermesStreamChunk, void, unknown> {
  return iterLiveChatStream({
    streamId: options.streamId,
    sessionId: options.sessionId,
    signal: options.signal,
    onSessionTitle: options.onSessionTitle,
    onContextUsage: options.onContextUsage,
  });
}

export async function cancelChatStream(streamId: string): Promise<void> {
  const id = streamId.trim();
  if (!id) return;
  await fetchJson("/chat/cancel", { query: { stream_id: id } });
}

export type { HermesChatStartResult };
