import { useCallback, useEffect, useRef, useState } from "react";
import { createHermesEventSource } from "@/lib/sse";
import {
  getClarifyPending,
  respondClarify,
  type ClarifyPending,
} from "../services/clarifyApi";
import {
  clarifyQuestionFromPending,
  formatClarifyEchoMessage,
} from "../utils/formatClarifyEcho";

export interface ClarifyAnsweredPayload {
  question: string;
  answer: string;
  displayContent: string;
}

export interface UseClarifyStreamOptions {
  sessionId: string | null | undefined;
  /** When false, no SSE connection is opened. Default true. */
  enabled?: boolean;
  /** Called after the server accepts a clarify response (legacy transcript echo). */
  onAnswered?: (payload: ClarifyAnsweredPayload) => void;
}

interface ClarifyStreamPayload {
  pending: ClarifyPending | null;
  pending_count?: number;
}

function parseClarifyPayload(raw: string): ClarifyStreamPayload | null {
  try {
    return JSON.parse(raw) as ClarifyStreamPayload;
  } catch {
    return null;
  }
}

/**
 * M28 — Subscribe to `GET /api/v1/clarify/stream?session_id=` SSE with HTTP fallback.
 */
export function useClarifyStream({
  sessionId,
  enabled = true,
  onAnswered,
}: UseClarifyStreamOptions) {
  const [pending, setPending] = useState<ClarifyPending | null>(null);
  const [isResponding, setIsResponding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pendingRef = useRef<ClarifyPending | null>(null);
  pendingRef.current = pending;

  const applyPayload = useCallback((payload: ClarifyStreamPayload | null) => {
    if (!payload) return;
    if (payload.pending) {
      setPending(payload.pending);
      setError(null);
    } else {
      setPending(null);
    }
  }, []);

  useEffect(() => {
    if (!enabled || !sessionId || typeof EventSource === "undefined") {
      setPending(null);
      setError(null);
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
          const data = await getClarifyPending(sessionId);
          applyPayload(data);
        } catch {
          /* ignore poll errors */
        }
      }, 1500);
    };

    const handleEvent = (event: MessageEvent) => {
      applyPayload(parseClarifyPayload(event.data));
    };

    const connection = createHermesEventSource({
      path: "/clarify/stream",
      query: { session_id: sessionId },
      policy: "poll-fallback",
      listeners: [
        { type: "initial", handler: handleEvent },
        { type: "clarify", handler: handleEvent },
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
    async (response: string) => {
      const text = response.trim();
      if (!sessionId || !text || isResponding) return false;

      const pendingSnapshot = pendingRef.current;
      const clarifyId = pendingSnapshot?.clarify_id;
      const question = clarifyQuestionFromPending(pendingSnapshot);
      setIsResponding(true);
      setError(null);
      try {
        const result = await respondClarify(sessionId, text, clarifyId);
        if (result.ok) {
          if (pendingRef.current?.clarify_id === clarifyId) {
            setPending(null);
          }
          onAnswered?.({
            question,
            answer: text,
            displayContent: formatClarifyEchoMessage(question, text),
          });
          return true;
        }
        setError(
          result.error ??
            "Clarification response not accepted — the agent may have already proceeded.",
        );
        return false;
      } catch {
        setError("Failed to send clarification response. Please try again.");
        return false;
      } finally {
        setIsResponding(false);
      }
    },
    [sessionId, isResponding, onAnswered],
  );

  return { pending, isResponding, error, respond };
}
