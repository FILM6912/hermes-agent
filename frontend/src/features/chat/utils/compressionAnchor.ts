import type { Message, SessionCompressionAnchor } from "@/types";
import type { HermesSessionMessage } from "@/types/hermes/sessions";

export type CompressionAnchorMessageKey = {
  role: string;
  ts?: number | null;
  text?: string;
  attachments?: number;
};

export type TranscriptItem =
  | { kind: "message"; message: Message }
  | { kind: "compression"; anchor: SessionCompressionAnchor };

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function extractMessageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      const row = part as Record<string, unknown>;
      if (
        row.type === "text" ||
        row.type === "input_text" ||
        row.type === "output_text"
      ) {
        return asString(row.text ?? row.content);
      }
      return "";
    })
    .join("\n")
    .trim();
}

/** Synthetic compaction marker rows are not ordinary transcript turns. */
export function isContextCompressionMarker(
  message: HermesSessionMessage | Record<string, unknown>,
): boolean {
  const role = asString(message.role);
  if (!role || role === "tool") return false;
  const text = extractMessageText(message.content).toLowerCase().trimStart();
  return (
    text.startsWith("[context compaction") ||
    text.startsWith("context compaction") ||
    text.startsWith(
      "[your active task list was preserved across context compression]",
    )
  );
}

function messageTimestamp(message: HermesSessionMessage | Record<string, unknown>): number | null {
  const ts = message.timestamp ?? message._ts;
  return typeof ts === "number" && Number.isFinite(ts) ? ts : null;
}

/** Last compaction marker body from raw Hermes transcript rows. */
export function compressionSummaryFromHermesMessages(
  messages: HermesSessionMessage[] | undefined,
): string | undefined {
  const list = Array.isArray(messages) ? messages : [];
  for (let i = list.length - 1; i >= 0; i--) {
    if (!isContextCompressionMarker(list[i])) continue;
    const text = extractMessageText(list[i].content).trim();
    if (text) return text;
  }
  return undefined;
}

function compressionMarkerTimestampFromHermesMessages(
  messages: HermesSessionMessage[] | undefined,
): number | null {
  const list = Array.isArray(messages) ? messages : [];
  for (let i = list.length - 1; i >= 0; i--) {
    if (!isContextCompressionMarker(list[i])) continue;
    return messageTimestamp(list[i]);
  }
  return null;
}

export function compressionMessageKey(
  message: Message,
): CompressionAnchorMessageKey | null {
  const norm = message.content.replace(/\s+/g, " ").trim().slice(0, 160);
  const attachments = message.attachments?.length ?? 0;
  const ts = message.timestamp;
  if (!norm && !attachments && !ts) return null;
  return { role: message.role, ts, text: norm, attachments };
}

export function matchesCompressionMessageKey(
  message: Message,
  key: CompressionAnchorMessageKey,
): boolean {
  const candidate = compressionMessageKey(message);
  if (!candidate) return false;
  const anchorTs = String(key.ts ?? "");
  const candidateTs = String(candidate.ts ?? "");
  return (
    candidate.role === String(key.role || "") &&
    (!anchorTs || !candidateTs || candidateTs === anchorTs) &&
    String(candidate.text || "") === String(key.text || "") &&
    Number(candidate.attachments || 0) === Number(key.attachments || 0)
  );
}

/** Prefer full compaction marker body over truncated session metadata. */
export function compressionSummaryForDisplay(
  metadataSummary: string,
  messages: HermesSessionMessage[] | undefined,
): string {
  const markerSummary = compressionSummaryFromHermesMessages(messages)?.trim() || "";
  const metadata = metadataSummary.trim();
  if (markerSummary) return markerSummary;
  return metadata;
}

export function compressionAnchorFromHermesDetail(
  detail: Record<string, unknown>,
): SessionCompressionAnchor | undefined {
  const rawMessages = Array.isArray(detail.messages)
    ? (detail.messages as HermesSessionMessage[])
    : undefined;
  const summary = compressionSummaryForDisplay(
    asString(detail.compression_anchor_summary),
    rawMessages,
  );

  if (!summary) return undefined;

  const visibleIdx =
    typeof detail.compression_anchor_visible_idx === "number"
      ? detail.compression_anchor_visible_idx
      : null;

  const rawKey = detail.compression_anchor_message_key;
  const messageKey =
    rawKey && typeof rawKey === "object" && !Array.isArray(rawKey)
      ? {
          role: asString((rawKey as Record<string, unknown>).role),
          ts: (rawKey as Record<string, unknown>).ts as number | null | undefined,
          text: asString((rawKey as Record<string, unknown>).text),
          attachments:
            typeof (rawKey as Record<string, unknown>).attachments === "number"
              ? ((rawKey as Record<string, unknown>).attachments as number)
              : 0,
        }
      : null;

  const engine = asString(detail.compression_anchor_engine).trim() || null;
  const mode = asString(detail.compression_anchor_mode).trim() || null;
  const markerTimestamp = compressionMarkerTimestampFromHermesMessages(rawMessages);

  return { summary, visibleIdx, messageKey, markerTimestamp, engine, mode };
}

export function compressionCardInsertIndex(
  messages: Message[],
  anchor: SessionCompressionAnchor,
): number {
  if (!anchor.summary.trim()) return -1;

  if (anchor.messageKey) {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (matchesCompressionMessageKey(messages[i], anchor.messageKey)) {
        return i + 1;
      }
    }
    // Merged assistant turns may not keep the anchor snippet in `content`.
    const key = anchor.messageKey;
    for (let i = messages.length - 1; i >= 0; i--) {
      const candidate = compressionMessageKey(messages[i]);
      if (!candidate) continue;
      const anchorTs = String(key.ts ?? "");
      const candidateTs = String(candidate.ts ?? "");
      if (
        candidate.role === String(key.role || "") &&
        anchorTs &&
        candidateTs === anchorTs &&
        Number(candidate.attachments || 0) === Number(key.attachments || 0)
      ) {
        return i + 1;
      }
    }
  }

  if (typeof anchor.markerTimestamp === "number" && anchor.markerTimestamp >= 0) {
    for (let i = 0; i < messages.length; i++) {
      if (messages[i].timestamp > anchor.markerTimestamp) {
        return i;
      }
    }
    return messages.length;
  }

  if (typeof anchor.visibleIdx === "number" && anchor.visibleIdx >= 0) {
    return Math.min(anchor.visibleIdx + 1, messages.length);
  }

  return messages.length;
}

export function buildTranscriptItems(
  messages: Message[],
  anchor?: SessionCompressionAnchor,
): TranscriptItem[] {
  const items: TranscriptItem[] = messages.map((message) => ({
    kind: "message",
    message,
  }));
  if (!anchor?.summary?.trim()) return items;

  const insertAt = compressionCardInsertIndex(messages, anchor);
  if (insertAt < 0) return items;

  items.splice(insertAt, 0, { kind: "compression", anchor });
  return items;
}

export function compressionCopyForAnchor(
  anchor: SessionCompressionAnchor,
  t: (key: string) => string,
): { label: string; preview: string } {
  const engine = String(anchor.engine || "").trim().toLowerCase();
  const mode = String(anchor.mode || "").trim().toLowerCase();
  if (engine === "lcm" || mode === "lossless_retrieval") {
    return {
      label: t("chat.retrievalContextLabel"),
      preview: t("chat.retrievalContextPreview"),
    };
  }
  return {
    label: t("chat.contextCompactionLabel"),
    preview: t("chat.referenceOnlyLabel"),
  };
}
