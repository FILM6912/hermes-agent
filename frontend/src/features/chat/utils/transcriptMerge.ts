import type { Message } from "@/types";
import { stripAttachedFilesMarker } from "@/services/hermes/attachments";

export { stripAttachedFilesMarker };

export function messageComparableText(message: Message): string {
  return (message.content || "").trim();
}

/** Legacy parity: sessions.js `_sameTranscriptMessage`. */
/**
 * Legacy parity: `sessions.js` `_mergePendingSessionMessage` — trailing assistant
 * with no finalized prose is the in-progress stream bubble.
 */
export function findLiveAssistantIndex(messages: Message[]): number {
  if (messages.length === 0) return -1;
  const last = messages[messages.length - 1];
  if (last.role !== "assistant") return -1;
  const content = messageComparableText(last);
  if (!content) return messages.length - 1;
  if ((last.steps?.length ?? 0) > 0 || (last.blocks?.length ?? 0) > 0) {
    return messages.length - 1;
  }
  return -1;
}

/** Insert optimistic pending user turn before a live assistant bubble when streaming. */
export function insertPendingUserIntoTranscript(
  messages: Message[],
  pendingUser: Message,
  activeStreamId?: string,
): Message[] {
  if (messages.some((m) => sameTranscriptMessage(m, pendingUser))) {
    return messages;
  }
  const next = [...messages];
  const liveAssistantIdx = activeStreamId?.trim()
    ? findLiveAssistantIndex(next)
    : -1;
  if (liveAssistantIdx >= 0) {
    next.splice(liveAssistantIdx, 0, pendingUser);
  } else {
    next.push(pendingUser);
  }
  return next;
}

function appendUnconsumedLocalMessage(merged: Message[], localMsg: Message): void {
  if (localMsg.role === "user") {
    const liveIdx = findLiveAssistantIndex(merged);
    if (liveIdx >= 0) {
      merged.splice(liveIdx, 0, localMsg);
      return;
    }
  }
  merged.push(localMsg);
}

export function sameTranscriptMessage(a: Message, b: Message): boolean {
  if (a.role !== b.role) return false;

  const aText = messageComparableText(a);
  const bText = messageComparableText(b);
  if (aText === bText) return true;

  if (a.role === "user") {
    return stripAttachedFilesMarker(aText) === stripAttachedFilesMarker(bText);
  }

  if (a.role === "assistant") {
    if (!aText && !bText) return true;
    if (aText && bText) {
      if (aText.startsWith(bText) || bText.startsWith(aText)) return true;
    }
  }

  return false;
}

function mergeMessagePreferringRicher(local: Message, server: Message): Message {
  const localContent = messageComparableText(local);
  const serverContent = messageComparableText(server);
  const content =
    localContent.length > serverContent.length ? local.content : server.content;
  const localSteps = local.steps?.length ?? 0;
  const serverSteps = server.steps?.length ?? 0;
  const steps = localSteps >= serverSteps ? local.steps : server.steps;
  const blocks =
    (local.blocks?.length ?? 0) >= (server.blocks?.length ?? 0)
      ? local.blocks
      : server.blocks;

  return {
    ...server,
    id: server.id,
    content: content ?? server.content ?? local.content,
    steps: steps ?? server.steps ?? local.steps,
    blocks: blocks ?? server.blocks ?? local.blocks,
    attachments: server.attachments?.length
      ? server.attachments
      : local.attachments,
    versions:
      (local.versions?.length ?? 0) > (server.versions?.length ?? 0)
        ? local.versions
        : server.versions ?? local.versions,
    currentVersionIndex: local.currentVersionIndex ?? server.currentVersionIndex,
  };
}

/**
 * Merge optimistic/local transcript rows with authoritative server history.
 * Matches legacy inflight + pending merge (content identity, not only ids).
 */
export function mergeLocalAndServerTranscript(
  localMessages: Message[],
  serverMessages: Message[],
): Message[] {
  if (serverMessages.length === 0) return localMessages;
  if (localMessages.length === 0) return serverMessages;

  const branchedLocal = localMessages.filter(
    (m) => (m.versions?.length ?? 0) > 1,
  );
  const plainLocal = localMessages.filter(
    (m) => (m.versions?.length ?? 0) <= 1,
  );

  const consumedLocal = new Set<number>();
  const merged: Message[] = [];

  for (const serverMsg of serverMessages) {
    const localById = plainLocal.findIndex((lm) => lm.id === serverMsg.id);
    if (localById >= 0) {
      consumedLocal.add(localById);
      merged.push(
        mergeMessagePreferringRicher(plainLocal[localById], serverMsg),
      );
      continue;
    }

    const localByTranscript = plainLocal.findIndex(
      (lm, idx) =>
        !consumedLocal.has(idx) && sameTranscriptMessage(lm, serverMsg),
    );
    if (localByTranscript >= 0) {
      consumedLocal.add(localByTranscript);
      merged.push(
        mergeMessagePreferringRicher(
          plainLocal[localByTranscript],
          serverMsg,
        ),
      );
      continue;
    }

    merged.push(serverMsg);
  }

  for (let i = 0; i < plainLocal.length; i += 1) {
    if (consumedLocal.has(i)) continue;
    const localMsg = plainLocal[i];
    if (merged.some((m) => sameTranscriptMessage(m, localMsg))) continue;
    appendUnconsumedLocalMessage(merged, localMsg);
  }

  for (const branched of branchedLocal) {
    if (!merged.some((m) => m.id === branched.id)) {
      merged.push(branched);
    }
  }

  return merged;
}

/** Drop adjacent duplicate rows after a merge (safety net). */
export function dedupeTranscriptMessages(messages: Message[]): Message[] {
  const out: Message[] = [];
  for (const msg of messages) {
    const window = out.slice(-Math.max(5, 3));
    if (window.some((existing) => sameTranscriptMessage(existing, msg))) {
      continue;
    }
    out.push(msg);
  }
  return out;
}
