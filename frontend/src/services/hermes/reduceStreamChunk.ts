import type { ChatSession, Message, ProcessStep } from "@/types";
import { insertClarifyEchoIntoMessages } from "@/features/clarify/utils/formatClarifyEcho";
import { applyStreamChunkToMessage } from "@/features/chat/utils/messageBlocks";
import type { HermesStreamChunk } from "./streamChat";

export type StreamChunkReduceOpts = {
  assistantMsgId: string;
  targetMessageId?: string;
};

/** Mutable transcript-side state carried across SSE chunks (not stored on ChatSession). */
export type StreamChunkReduceState = {
  messageInitialized: boolean;
  accumulatedContent: string;
};

export type StreamChunkReduceResult = {
  session: ChatSession;
  state: StreamChunkReduceState;
  /** True when this chunk only initialized the assistant placeholder. */
  skippedContentApply?: boolean;
};

export function createStreamChunkReduceState(
  initialAccumulatedContent = "",
  targetMessageId?: string,
): StreamChunkReduceState {
  return {
    messageInitialized: !!targetMessageId,
    accumulatedContent: initialAccumulatedContent,
  };
}

function createEmptyAssistantMessage(assistantMsgId: string): Message {
  return {
    id: assistantMsgId,
    role: "assistant",
    content: "",
    timestamp: Date.now(),
    blocks: [],
    versions: [
      {
        content: "",
        blocks: [],
        timestamp: Date.now(),
      },
    ],
    currentVersionIndex: 0,
    needsSuggestions: true,
  };
}

function streamChunkForApply(
  chunk: HermesStreamChunk,
): { type: "text" | "steps"; steps?: ProcessStep[] } | null {
  if (chunk.type === "steps") {
    return { type: "steps", steps: chunk.steps };
  }
  if (chunk.type === "text" && chunk.content) {
    return { type: "text" };
  }
  return null;
}

function patchAssistantMessageForStream(
  msg: Message,
  streamChunk: { type: "text" | "steps"; steps?: ProcessStep[] },
  accumulatedContent: string,
): Message {
  const currentVersionIndex = msg.currentVersionIndex || 0;
  const currentMessageVersion = msg.versions?.[currentVersionIndex];

  if (
    currentMessageVersion?.aiVersions &&
    currentMessageVersion.aiVersions.length > 0
  ) {
    const currentAIIndex = currentMessageVersion.currentAIIndex || 0;
    const currentAIVersion = currentMessageVersion.aiVersions[currentAIIndex];
    const currentRegenIndex = currentAIVersion?.currentRegenIndex || 0;
    const currentRegenVersions = currentAIVersion?.regenVersions || [];

    const updatedAIVersions = [...currentMessageVersion.aiVersions];
    const updatedRegenVersions = [...currentRegenVersions];

    if (updatedRegenVersions[currentRegenIndex]) {
      const regenSeed: Message = {
        id: msg.id,
        role: "assistant",
        content: updatedRegenVersions[currentRegenIndex].content ?? "",
        timestamp: msg.timestamp,
        steps: updatedRegenVersions[currentRegenIndex].steps,
        blocks: updatedRegenVersions[currentRegenIndex].blocks,
      };
      const patchedRegen = applyStreamChunkToMessage(
        regenSeed,
        streamChunk,
        accumulatedContent,
      );
      updatedRegenVersions[currentRegenIndex] = {
        ...updatedRegenVersions[currentRegenIndex],
        content: patchedRegen.content,
        steps: patchedRegen.steps,
        blocks: patchedRegen.blocks,
      };
    }

    updatedAIVersions[currentAIIndex] = {
      ...currentAIVersion,
      regenVersions: updatedRegenVersions,
    };

    const updatedMessageVersion = {
      ...currentMessageVersion,
      aiVersions: updatedAIVersions,
    };

    const updatedVersions = [...(msg.versions || [])];
    updatedVersions[currentVersionIndex] = updatedMessageVersion;

    const patchedMsg = applyStreamChunkToMessage(
      msg,
      streamChunk,
      accumulatedContent,
    );
    return {
      ...patchedMsg,
      versions: updatedVersions,
    };
  }

  const updatedVersions = msg.versions ? [...msg.versions] : [];
  const currentIndex =
    updatedVersions.length > 0 ? updatedVersions.length - 1 : 0;

  const patchedMsg = applyStreamChunkToMessage(
    msg,
    streamChunk,
    accumulatedContent,
  );

  if (updatedVersions[currentIndex]) {
    updatedVersions[currentIndex] = {
      ...updatedVersions[currentIndex],
      content: patchedMsg.content,
      steps: patchedMsg.steps,
      blocks: patchedMsg.blocks,
    };
  }

  return {
    ...patchedMsg,
    versions: updatedVersions,
    currentVersionIndex: currentIndex,
  };
}

/** Insert a clarify Q/A user line into the transcript (single writer for echo shape). */
export function reduceClarifyEchoToSession(
  session: ChatSession,
  echoContent: string,
): ChatSession {
  const trimmed = echoContent.trim();
  if (!trimmed) return session;
  const echoMsg: Message = {
    id: `clarify-${Date.now()}`,
    role: "user",
    content: trimmed,
    timestamp: Date.now(),
  };
  return {
    ...session,
    messages: insertClarifyEchoIntoMessages(session.messages, echoMsg),
    updatedAt: Date.now(),
  };
}

/**
 * Pure reducer at the transcript seam: one Hermes stream chunk → updated session.
 * Carries `messageInitialized` and `accumulatedContent` in `state` between chunks.
 */
export function reduceStreamChunk(
  session: ChatSession,
  chunk: HermesStreamChunk,
  opts: StreamChunkReduceOpts,
  reduceState: StreamChunkReduceState,
): StreamChunkReduceResult {
  const { assistantMsgId, targetMessageId } = opts;
  let state = { ...reduceState };

  if (chunk.type === "clarify_echo" && chunk.content?.trim()) {
    return {
      session: reduceClarifyEchoToSession(session, chunk.content),
      state,
    };
  }

  if (!state.messageInitialized) {
    if (!targetMessageId) {
      let initialAssistantMsg = createEmptyAssistantMessage(assistantMsgId);

      if (chunk.type === "text" && chunk.content) {
        state.accumulatedContent += chunk.content;
        initialAssistantMsg = applyStreamChunkToMessage(
          initialAssistantMsg,
          { type: "text" },
          state.accumulatedContent,
        );
      } else if (chunk.type === "steps") {
        initialAssistantMsg = applyStreamChunkToMessage(
          initialAssistantMsg,
          { type: "steps", steps: chunk.steps },
          state.accumulatedContent,
        );
      }
      if (initialAssistantMsg.versions?.[0]) {
        initialAssistantMsg.versions[0] = {
          ...initialAssistantMsg.versions[0],
          content: initialAssistantMsg.content,
          steps: initialAssistantMsg.steps,
          blocks: initialAssistantMsg.blocks,
        };
      }

      state.messageInitialized = true;
      return {
        session: {
          ...session,
          messages: [...session.messages, initialAssistantMsg],
        },
        state,
        skippedContentApply: true,
      };
    }

    state.messageInitialized = true;
  }

  const streamChunk = streamChunkForApply(chunk);
  if (!streamChunk) {
    return { session, state };
  }

  if (chunk.type === "text" && chunk.content) {
    if (chunk.isFullText) {
      state.accumulatedContent = chunk.content;
    } else {
      state.accumulatedContent += chunk.content;
    }
  }

  const updatedMessages = session.messages.map((msg) => {
    if (msg.id !== assistantMsgId) return msg;
    return patchAssistantMessageForStream(
      msg,
      streamChunk,
      state.accumulatedContent,
    );
  });

  return {
    session: {
      ...session,
      messages: updatedMessages,
    },
    state,
  };
}
