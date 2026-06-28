import { describe, expect, it } from "vitest";
import {
  combinedReasoningText,
  isDistinctThinking,
  stripThinkingFromAssistantStream,
} from "@/services/hermes/streamDisplay";

describe("stripThinkingFromAssistantStream", () => {
  it("hides redacted_thinking blocks from the visible assistant bubble", () => {
    const raw =
      "<think>Plan in Thai</think>\n\nสวัสดีครับ";
    expect(stripThinkingFromAssistantStream(raw)).toBe("สวัสดีครับ");
  });

  it("returns empty string while an opening thinking tag is still streaming", () => {
    expect(stripThinkingFromAssistantStream("<think>still")).toBe("");
  });
});

describe("combinedReasoningText", () => {
  it("joins committed reasoning segments with blank lines", () => {
    expect(
      combinedReasoningText(["segment one", "segment two"], "live tail"),
    ).toBe("segment one\n\nsegment two\n\nlive tail");
  });

  it("skips empty committed and live segments", () => {
    expect(combinedReasoningText(["hello", ""], "")).toBe("hello");
  });
});

describe("isDistinctThinking", () => {
  it("treats identical normalized text as duplicate of answer", () => {
    expect(isDistinctThinking("Hello", "hello")).toBe(false);
  });

  it("keeps reasoning when it differs from visible answer", () => {
    expect(isDistinctThinking("Plan in Thai", "สวัสดีครับ")).toBe(true);
  });

  it("ignores placeholder thinking labels", () => {
    expect(isDistinctThinking("thinking...", "answer")).toBe(false);
    expect(isDistinctThinking("กำลังคิด...", "answer")).toBe(false);
  });

  it("treats answer-prefixed reasoning as duplicate", () => {
    expect(isDistinctThinking("Hello world", "Hello")).toBe(false);
  });
});
