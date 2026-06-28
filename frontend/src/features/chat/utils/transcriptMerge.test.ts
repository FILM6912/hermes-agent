import { describe, expect, it } from "vitest";
import type { Message } from "@/types";
import {
  findLiveAssistantIndex,
  insertPendingUserIntoTranscript,
  mergeLocalAndServerTranscript,
} from "./transcriptMerge";

const user = (content: string, id = "u1"): Message => ({
  id,
  role: "user",
  content,
  timestamp: 1,
});

const assistant = (
  content: string,
  id = "a1",
  extra: Partial<Message> = {},
): Message => ({
  id,
  role: "assistant",
  content,
  timestamp: 2,
  ...extra,
});

describe("transcriptMerge streaming order", () => {
  it("inserts pending user before a live assistant during active stream", () => {
    const server = [assistant("", "a-live", { steps: [] })];
    const pending = user("คุณทำอะไรได้", "pending");
    const merged = insertPendingUserIntoTranscript(server, pending, "stream-1");
    expect(merged.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(merged[0].content).toBe("คุณทำอะไรได้");
  });

  it("appends pending user after a completed prior turn", () => {
    const server = [user("hello"), assistant("hi there")];
    const pending = user("follow up", "pending");
    const merged = insertPendingUserIntoTranscript(server, pending, "stream-1");
    expect(merged.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
  });

  it("treats trailing assistant with tool steps as live", () => {
    const messages = [
      user("q"),
      assistant("answer", "a1"),
      assistant("", "a-live", {
        steps: [{ id: "s1", type: "tool", status: "running", title: "search" }],
      }),
    ];
    expect(findLiveAssistantIndex(messages)).toBe(2);
  });

  it("merges local user before server live assistant instead of after", () => {
    const local = [user("คุณทำอะไรได้", "local-u"), assistant("", "local-a")];
    const server = [assistant("", "server-a", { steps: [] })];
    const merged = mergeLocalAndServerTranscript(local, server);
    expect(merged.map((m) => m.content)).toEqual(["คุณทำอะไรได้", ""]);
    expect(merged.map((m) => m.role)).toEqual(["user", "assistant"]);
  });
});
