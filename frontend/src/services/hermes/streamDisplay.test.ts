import { describe, expect, it } from "vitest";
import {
  combinedReasoningText,
  isDistinctThinking,
} from "@/services/hermes/streamDisplay";

describe("combinedReasoningText", () => {
  it("concatenates SSE token chunks without inserting newlines", () => {
    expect(
      combinedReasoningText([
        "The user said ",
        '"สวัส',
        'กี" which',
        " seems",
      ]),
    ).toBe('The user said "สวัสกี" which seems');
  });

  it("skips empty chunks", () => {
    expect(combinedReasoningText(["hello", "", " world"])).toBe("hello world");
  });
});

describe("isDistinctThinking", () => {
  it("treats identical normalized text as duplicate of answer", () => {
    expect(isDistinctThinking("Hello", "hello")).toBe(false);
  });

  it("keeps reasoning when it differs from visible answer", () => {
    expect(isDistinctThinking("Plan in Thai", "สวัสดีครับ")).toBe(true);
  });
});
