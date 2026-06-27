import type { Message } from "@/types";
import type { HermesSessionDetail } from "@/types/hermes/sessions";
import { generateUUID } from "@/lib/utils";
import { sameTranscriptMessage } from "@/features/chat/utils/transcriptMerge";

/** Append optimistic pending user turn when server has not persisted it yet. */
export function mergePendingUserMessage(
  session: HermesSessionDetail,
  messages: Message[],
): Message | null {
  const text =
    typeof session.pending_user_message === "string"
      ? session.pending_user_message.trim()
      : "";
  if (!text) return null;

  const pendingAttachments = Array.isArray(session.pending_attachments)
    ? session.pending_attachments.filter(Boolean)
    : [];

  if (messages.some((existing) => sameTranscriptMessage(existing, {
    id: "probe",
    role: "user",
    content: text,
    timestamp: 0,
  }))) {
    return null;
  }

  return {
    id: `pending-${session.session_id}`,
    role: "user",
    content: text,
    timestamp:
      typeof session.pending_started_at === "number"
        ? session.pending_started_at * 1000
        : Date.now(),
    ...(pendingAttachments.length
      ? {
          attachments: pendingAttachments.map((att, index) => {
            const row =
              typeof att === "object" && att !== null
                ? (att as Record<string, unknown>)
                : {};
            const name =
              typeof row.name === "string" ? row.name : `attachment-${index + 1}`;
            const path = typeof row.path === "string" ? row.path : "";
            return {
              id: `pending-att-${index}`,
              name,
              type: "file" as const,
              content: path,
              path,
            };
          }),
        }
      : {}),
  };
}

export function readActiveStreamId(session: HermesSessionDetail): string {
  const raw = session.active_stream_id;
  return typeof raw === "string" ? raw.trim() : "";
}

export function resolveAssistantForReattach(messages: Message[]): {
  assistantMsgId: string;
  accumulatedContent: string;
  appendAssistant: boolean;
} {
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  if (lastAssistant) {
    return {
      assistantMsgId: lastAssistant.id,
      accumulatedContent: lastAssistant.content || "",
      appendAssistant: false,
    };
  }
  return {
    assistantMsgId: generateUUID(),
    accumulatedContent: "",
    appendAssistant: true,
  };
}
