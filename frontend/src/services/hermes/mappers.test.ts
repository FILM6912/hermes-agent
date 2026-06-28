import { describe, expect, it } from "vitest";
import {
  extractHermesMessageContent,
  extractHermesMessageReasoning,
  mapHermesMessagesToMessages,
} from "@/services/hermes/mappers";

describe("mapHermesMessagesToMessages reasoning", () => {
  it("maps top-level reasoning into a completed thinking step on reload", () => {
    const [msg] = mapHermesMessagesToMessages([
      {
        role: "assistant",
        content: "สวัสดีครับ ฟิล์ม! 👋 มีอะไรให้ช่วยไหมครับ?",
        reasoning:
          'The user said "สวัสกี" which seems to be a typo of "สวัสดี" (sawasdee) - Thai greeting. I should respond naturally in Thai.',
      },
    ]);

    expect(msg.steps).toHaveLength(1);
    expect(msg.steps?.[0]).toMatchObject({
      type: "thinking",
      status: "completed",
      content: expect.stringContaining("สวัสกี"),
    });
  });

  it("does not duplicate thinking when steps already include reasoning", () => {
    const [msg] = mapHermesMessagesToMessages([
      {
        role: "assistant",
        content: "Answer",
        reasoning: "Hidden plan",
        steps: [{ id: "t1", type: "thinking", title: "Thinking", content: "Hidden plan", status: "completed" }],
      },
    ]);

    expect(msg.steps).toHaveLength(1);
    expect(msg.steps?.[0]?.id).toBe("t1");
  });

  it("extracts reasoning blocks from structured content arrays", () => {
    const reasoning = extractHermesMessageReasoning(
      {
        content: [
          { type: "reasoning", text: "Plan A" },
          { type: "text", text: "Visible answer" },
        ],
      },
      "Visible answer",
    );
    expect(reasoning).toBe("Plan A");
    expect(extractHermesMessageContent({ content: [{ type: "text", text: "Visible answer" }] })).toBe(
      "Visible answer",
    );
  });
});
