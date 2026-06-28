import type { ChatSession, Message, ProcessStep } from "@/types";
import { insertClarifyEchoIntoMessages } from "@/features/clarify/utils/formatClarifyEcho";
import { applyStreamChunkToMessage } from "@/features/chat/utils/messageBlocks";
import type { HermesStreamChunk } from "@/services/hermes/streamChat";
import { generateUUID } from "@/lib/utils";

export type StreamChunkReduceContext = {
  assistantMsgId: string;
  targetMessageId?: string;
};

export type StreamChunkReduceState = {
  accumulatedContent: string;
  messageInitialized: boolean;
  steps: ProcessStep[];
};

export function createStreamChunkReduceState(
  initialAccumulatedContent = "",
  targetMessageId?: string,
): StreamChunkReduceState {
  return {
    accumulatedContent: initialAccumulatedContent,
    messageInitialized: !!targetMessageId,
    steps: [],
  };
}

function findAssistantMessageIndex(
  messages: Message[],
  assistantMsgId: string,
  targetMessageId?: string,
): number {
  if (targetMessageId) {
    const idx = messages.findIndex((m) => m.id === targetMessageId);
    if (idx >= 0) return idx;
  }
  const idx = messages.findIndex((m) => m.id === assistantMsgId);
  if (idx >= 0) return idx;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "assistant") return i;
  }
  return -1;
}

function placeholderAssistantMessage(assistantMsgId: string): Message {
  return {
    id: assistantMsgId,
    role: "assistant",
    content: "",
    timestamp: Date.now(),
    steps: [],
    blocks: [],
  };
}

export function reduceStreamChunk(
  session: ChatSession,
  chunk: HermesStreamChunk,
  ctx: StreamChunkReduceContext,
  state: StreamChunkReduceState,
): { session: ChatSession; state: StreamChunkReduceState } {
  if (chunk.type === "turn_end") {
    return { session, state };
  }

  let nextState: StreamChunkReduceState = { ...state, steps: [...state.steps] };
  const messages = [...session.messages];

  if (chunk.type === "text") {
    nextState.accumulatedContent = `${state.accumulatedContent}${chunk.content ?? ""}`;
  }

  if (chunk.type === "steps" && chunk.steps?.length) {
    nextState.steps = chunk.steps;
  }

  let assistantIdx = findAssistantMessageIndex(
    messages,
    ctx.assistantMsgId,
    ctx.targetMessageId,
  );

  if (assistantIdx < 0) {
    messages.push(placeholderAssistantMessage(ctx.assistantMsgId));
    assistantIdx = messages.length - 1;
    nextState.messageInitialized = true;
  } else {
    nextState.messageInitialized = true;
  }

  const current = messages[assistantIdx];
  const updated = applyStreamChunkToMessage(
    current,
    chunk.type === "steps"
      ? { type: "steps", steps: nextState.steps }
      : { type: "text" },
    nextState.accumulatedContent,
  );
  messages[assistantIdx] = updated;

  return {
    session: {
      ...session,
      messages,
      updatedAt: Date.now(),
    },
    state: nextState,
  };
}

/** Append clarify Q/A echo before the trailing assistant bubble. */
export function reduceClarifyEchoToSession(
  session: ChatSession,
  content: string,
): ChatSession {
  const trimmed = content.trim();
  if (!trimmed) return session;
  const echo: Message = {
    id: generateUUID(),
    role: "user",
    content: trimmed,
    timestamp: Date.now(),
  };
  return {
    ...session,
    messages: insertClarifyEchoIntoMessages(session.messages, echo),
    updatedAt: Date.now(),
  };
}
