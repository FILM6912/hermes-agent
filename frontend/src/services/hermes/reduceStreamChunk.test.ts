import { describe, expect, it } from "vitest";
import type { ChatSession } from "@/types";
import {
  createStreamChunkReduceState,
  reduceStreamChunk,
} from "@/services/hermes/reduceStreamChunk";

const baseSession = (messages: ChatSession["messages"] = []): ChatSession => ({
  id: "s1",
  title: "Test",
  messages,
  updatedAt: 0,
});

describe("reduceStreamChunk", () => {
  it("replaces accumulated text when isFullText is set", () => {
    let state = createStreamChunkReduceState();
    const assistantId = "a1";

    const first = reduceStreamChunk(
      baseSession(),
      { type: "text", content: "Hello" },
      { assistantMsgId: assistantId },
      state,
    );
    state = first.state;

    const second = reduceStreamChunk(
      first.session,
      { type: "text", content: "Hi", isFullText: true },
      { assistantMsgId: assistantId },
      state,
    );

    const assistant = second.session.messages.find((m) => m.id === assistantId);
    expect(assistant?.content).toBe("Hi");
  });

  it("inserts clarify echo as a user message before continuing the stream", () => {
    const session = baseSession([
      {
        id: "a-live",
        role: "assistant",
        content: "",
        timestamp: 1,
      },
    ]);
    const state = createStreamChunkReduceState("", "a-live");

    const result = reduceStreamChunk(
      session,
      { type: "clarify_echo", content: "Q: Name?\nA: Film" },
      { assistantMsgId: "a-live", targetMessageId: "a-live" },
      state,
    );

    expect(result.session.messages.map((m) => m.role)).toEqual([
      "user",
      "assistant",
    ]);
    expect(result.session.messages[0].content).toBe("Q: Name?\nA: Film");
  });
});
