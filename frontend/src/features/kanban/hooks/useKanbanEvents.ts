import { useEffect, useRef } from "react";
import { createHermesEventSource } from "@/lib/sse";

export interface UseKanbanEventsOptions {
  enabled?: boolean;
  board?: string;
  since?: number;
  onBoardChanged: () => void;
}

/**
 * M35 — Subscribe to `GET /api/v1/kanban/events/stream` SSE for live board updates.
 */
export function useKanbanEvents({
  enabled = true,
  board,
  since = 0,
  onBoardChanged,
}: UseKanbanEventsOptions): void {
  const callbackRef = useRef(onBoardChanged);
  callbackRef.current = onBoardChanged;

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;

    const query: Record<string, string | number> = { since };
    if (board) query.board = board;

    const handleEvents = () => {
      callbackRef.current();
    };

    const connection = createHermesEventSource({
      path: "/kanban/events/stream",
      query,
      policy: "none",
      listeners: [
        { type: "events", handler: handleEvents },
        {
          type: "hello",
          handler: () => {
            /* connection established */
          },
        },
      ],
    });

    return () => {
      connection.close();
    };
  }, [enabled, board, since]);
}
