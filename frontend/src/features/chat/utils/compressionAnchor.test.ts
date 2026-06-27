import { describe, expect, it } from "vitest";
import type { Message } from "@/types";
import {
  buildTranscriptItems,
  compressionAnchorFromHermesDetail,
  compressionCardInsertIndex,
  compressionSummaryFromHermesMessages,
  isContextCompressionMarker,
  matchesCompressionMessageKey,
} from "./compressionAnchor";

describe("compressionAnchor", () => {
  it("detects context compaction marker messages", () => {
    expect(
      isContextCompressionMarker({
        role: "assistant",
        content: "[CONTEXT COMPACTION — REFERENCE ONLY] summary",
      }),
    ).toBe(true);
    expect(
      isContextCompressionMarker({
        role: "system",
        content: "[CONTEXT COMPACTION — REFERENCE ONLY] summary",
      }),
    ).toBe(true);
    expect(
      isContextCompressionMarker({
        role: "user",
        content: "normal question",
      }),
    ).toBe(false);
  });

  it("prefers full system marker over truncated metadata summary", () => {
    const fullContent =
      "[CONTEXT COMPACTION — REFERENCE ONLY] " +
      "## Active Task\nUser asked: find employee\n" +
      "x".repeat(500);
    const anchor = compressionAnchorFromHermesDetail({
      compression_anchor_summary: fullContent.replace(/\s+/g, " ").slice(0, 314) + "…",
      messages: [
        { role: "user", content: "hello", timestamp: 1 },
        {
          role: "system",
          content: fullContent,
          timestamp: 1782275001,
        },
        { role: "user", content: "follow up", timestamp: 1782275002 },
      ],
    });
    expect(anchor?.summary).toBe(fullContent);
    expect(anchor?.summary).toContain("## Active Task");
    expect(anchor?.summary.length).toBeGreaterThan(320);
  });

  it("derives compression anchor from system marker when metadata summary is absent", () => {
    const anchor = compressionAnchorFromHermesDetail({
      messages: [
        { role: "user", content: "hello", timestamp: 1 },
        {
          role: "system",
          content: "[CONTEXT COMPACTION — REFERENCE ONLY] handoff summary",
          timestamp: 1782275001,
        },
        { role: "user", content: "follow up", timestamp: 1782275002 },
      ],
    });
    expect(anchor?.summary).toContain("[CONTEXT COMPACTION");
    expect(anchor?.markerTimestamp).toBe(1782275001);
  });

  it("places compression card before messages after system marker timestamp", () => {
    const messages: Message[] = [
      {
        id: "u1",
        role: "user",
        content: "hello",
        timestamp: 1,
        versions: [{ content: "hello", timestamp: 1 }],
      },
      {
        id: "a1",
        role: "assistant",
        content: "reply",
        timestamp: 2,
        versions: [{ content: "reply", timestamp: 2 }],
      },
      {
        id: "u2",
        role: "user",
        content: "follow up",
        timestamp: 1782275002,
        versions: [{ content: "follow up", timestamp: 1782275002 }],
      },
    ];
    const items = buildTranscriptItems(messages, {
      summary: "[CONTEXT COMPACTION — REFERENCE ONLY] handoff",
      markerTimestamp: 1782275001,
    });
    expect(items[2]?.kind).toBe("compression");
    expect(items[3]?.kind).toBe("message");
    if (items[3]?.kind === "message") {
      expect(items[3].message.content).toBe("follow up");
    }
  });

  it("reads summary from raw system compaction row", () => {
    expect(
      compressionSummaryFromHermesMessages([
        {
          role: "system",
          content: "[CONTEXT COMPACTION — REFERENCE ONLY] persisted handoff",
        },
      ]),
    ).toContain("persisted handoff");
  });

  it("matches compression anchor message keys", () => {
    const message: Message = {
      id: "m1",
      role: "assistant",
      content:
        '## ผลการค้นหา — พนักงานชื่อเล่น "ฟิวส์" พบ **2 คน**',
      timestamp: 1782274870,
      versions: [{ content: "x", timestamp: 1782274870 }],
    };

    expect(
      matchesCompressionMessageKey(message, {
        role: "assistant",
        ts: 1782274870,
        text: '## ผลการค้นหา — พนักงานชื่อเล่น "ฟิวส์" พบ **2 คน**',
        attachments: 0,
      }),
    ).toBe(true);
  });

  it("inserts compression card after anchor message key", () => {
    const messages: Message[] = [
      {
        id: "u1",
        role: "user",
        content: "hello",
        timestamp: 1,
        versions: [{ content: "hello", timestamp: 1 }],
      },
      {
        id: "a1",
        role: "assistant",
        content: "anchor reply",
        timestamp: 2,
        versions: [{ content: "anchor reply", timestamp: 2 }],
      },
      {
        id: "u2",
        role: "user",
        content: "follow up",
        timestamp: 3,
        versions: [{ content: "follow up", timestamp: 3 }],
      },
    ];

    const insertAt = compressionCardInsertIndex(messages, {
      summary: "[CONTEXT COMPACTION — REFERENCE ONLY] handoff",
      messageKey: {
        role: "assistant",
        ts: 2,
        text: "anchor reply",
        attachments: 0,
      },
    });

    expect(insertAt).toBe(2);
    const items = buildTranscriptItems(messages, {
      summary: "[CONTEXT COMPACTION — REFERENCE ONLY] handoff",
      messageKey: {
        role: "assistant",
        ts: 2,
        text: "anchor reply",
        attachments: 0,
      },
    });
    expect(items[2]).toEqual({
      kind: "compression",
      anchor: {
        summary: "[CONTEXT COMPACTION — REFERENCE ONLY] handoff",
        messageKey: {
          role: "assistant",
          ts: 2,
          text: "anchor reply",
          attachments: 0,
        },
      },
    });
  });
});
