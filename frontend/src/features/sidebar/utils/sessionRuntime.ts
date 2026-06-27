import type { ChatSession } from "@/types";

export type SidebarSessionRuntimeOptions = {
  activeChatId: string | null;
  /** True when the open chat pane is actively streaming (composer stop). */
  isActivePaneStreaming: boolean;
  loadingChatId?: string | null;
};

/** Server-reported live stream: requires both is_streaming and active_stream_id. */
export function sessionHasLiveStream(session: ChatSession): boolean {
  const streamId = (session.activeStreamId || "").trim();
  return session.isStreaming === true && Boolean(streamId);
}

/** Normalize stream flags for sidebar display; drop stale partial metadata. */
export function normalizeSessionStreamFlags(
  session: ChatSession,
): Pick<ChatSession, "activeStreamId" | "isStreaming"> {
  if (sessionHasLiveStream(session)) {
    return {
      activeStreamId: (session.activeStreamId || "").trim(),
      isStreaming: true,
    };
  }
  return { activeStreamId: undefined, isStreaming: false };
}

/** Prefer server stream metadata; clear stale local flags when server reports idle. */
export function reconcileSessionStreamMetadata(
  existing: ChatSession | undefined,
  fetched: ChatSession,
): Pick<ChatSession, "activeStreamId" | "isStreaming"> {
  void existing;
  const streamId = (fetched.activeStreamId || "").trim();
  if (fetched.isStreaming === true && streamId) {
    return { activeStreamId: streamId, isStreaming: true };
  }
  return { activeStreamId: undefined, isStreaming: false };
}

/** Whether a sidebar row should show the running spinner and per-session stop control. */
export function isSidebarSessionRunning(
  session: ChatSession,
  opts: SidebarSessionRuntimeOptions,
): boolean {
  if (sessionHasLiveStream(session)) return true;
  if (opts.activeChatId === session.id && opts.isActivePaneStreaming) return true;
  return false;
}

/** Stream id used for GET /api/v1/chat/cancel on a sidebar row. */
export function streamIdForSessionCancel(session: ChatSession): string {
  return (session.activeStreamId || "").trim();
}
