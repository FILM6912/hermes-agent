import { useEffect, useRef } from "react";
import { createHermesEventSource } from "@/lib/sse";

export interface UseSessionEventsOptions {
  /** When false, no SSE connection is opened. Default true. */
  enabled?: boolean;
  /** Invoked when the server emits `sessions_changed`. */
  onSessionListChanged: () => void;
}

/**
 * M17 — Subscribe to `GET /api/v1/sessions/events` SSE for sidebar list invalidation.
 * M33 wires this into the shell; callers supply refresh logic via `onSessionListChanged`.
 * M39-reliability — exponential backoff reconnect on EventSource errors (max 30s).
 */
export function useSessionEvents({
  enabled = true,
  onSessionListChanged,
}: UseSessionEventsOptions): void {
  const callbackRef = useRef(onSessionListChanged);
  callbackRef.current = onSessionListChanged;

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;

    const handleSessionsChanged = () => {
      callbackRef.current();
    };

    const connection = createHermesEventSource({
      path: "/sessions/events",
      policy: "invalidate-only",
      listeners: [{ type: "sessions_changed", handler: handleSessionsChanged }],
    });

    return () => {
      connection.close();
    };
  }, [enabled]);
}
