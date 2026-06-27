import { useCallback, useEffect, useRef, useState } from "react";
import { createHermesEventSource } from "@/lib/sse";
import {
  getApprovalPending,
  respondApproval,
  type ApprovalChoice,
  type ApprovalPending,
} from "../services/approvalApi";

export interface UseApprovalStreamOptions {
  sessionId: string | null | undefined;
  /** When false, no SSE connection is opened. Default true. */
  enabled?: boolean;
}

interface ApprovalStreamPayload {
  pending: ApprovalPending | null;
  pending_count?: number;
}

function parseApprovalPayload(raw: string): ApprovalStreamPayload | null {
  try {
    return JSON.parse(raw) as ApprovalStreamPayload;
  } catch {
    return null;
  }
}

/**
 * M27 — Subscribe to `GET /api/v1/approval/stream?session_id=` SSE with HTTP fallback.
 */
export function useApprovalStream({ sessionId, enabled = true }: UseApprovalStreamOptions) {
  const [pending, setPending] = useState<ApprovalPending | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [isResponding, setIsResponding] = useState(false);

  const pendingRef = useRef<ApprovalPending | null>(null);
  pendingRef.current = pending;

  const applyPayload = useCallback((payload: ApprovalStreamPayload | null) => {
    if (!payload) return;
    if (payload.pending) {
      setPending(payload.pending);
      setPendingCount(payload.pending_count ?? 1);
    } else {
      setPending(null);
      setPendingCount(0);
    }
  }, []);

  useEffect(() => {
    if (!enabled || !sessionId || typeof EventSource === "undefined") {
      setPending(null);
      setPendingCount(0);
      return;
    }

    let closed = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const stopPoll = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const startFallbackPoll = () => {
      if (pollTimer || closed) return;
      pollTimer = setInterval(async () => {
        if (closed) return;
        try {
          const data = await getApprovalPending(sessionId);
          applyPayload(data);
        } catch {
          /* ignore poll errors */
        }
      }, 1500);
    };

    const handleEvent = (event: MessageEvent) => {
      applyPayload(parseApprovalPayload(event.data));
    };

    const connection = createHermesEventSource({
      path: "/approval/stream",
      query: { session_id: sessionId },
      policy: "poll-fallback",
      listeners: [
        { type: "initial", handler: handleEvent },
        { type: "approval", handler: handleEvent },
      ],
      onPollFallback: startFallbackPoll,
    });

    return () => {
      closed = true;
      stopPoll();
      connection.close();
    };
  }, [enabled, sessionId, applyPayload]);

  const respond = useCallback(
    async (choice: ApprovalChoice) => {
      if (!sessionId || isResponding) return;
      const approvalId = pendingRef.current?.approval_id;
      setIsResponding(true);
      setPending(null);
      setPendingCount(0);
      try {
        await respondApproval(sessionId, choice, approvalId);
      } finally {
        setIsResponding(false);
      }
    },
    [sessionId, isResponding],
  );

  return { pending, pendingCount, isResponding, respond };
}
