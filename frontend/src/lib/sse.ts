import { openEventSource } from "@/lib/api";

/** Default exponential backoff for `invalidate-only` reconnects (M39-reliability). */
export const SSE_INITIAL_BACKOFF_MS = 1_000;
export const SSE_MAX_BACKOFF_MS = 30_000;

/**
 * Sidebar / auxiliary stream reconnect strategies (c6).
 *
 * - `invalidate-only` — reconnect with exponential backoff (session list SSE).
 * - `poll-fallback` — close SSE on error and delegate to HTTP polling (clarify / approval).
 * - `journal-aware` — reserved for chat journal replay; not used by this helper yet.
 * - `none` — single connection, no adapter-driven reconnect (kanban).
 */
export type HermesSseReconnectPolicy =
  | "none"
  | "invalidate-only"
  | "poll-fallback"
  | "journal-aware";

export interface HermesSseListener {
  type: string;
  handler: (event: MessageEvent) => void;
}

export interface CreateHermesEventSourceOptions {
  path: string;
  query?: Record<string, string | number | boolean | undefined | null>;
  policy: HermesSseReconnectPolicy;
  listeners: HermesSseListener[];
  /** Invoked on EventSource `open` (resets backoff for `invalidate-only`). */
  onOpen?: () => void;
  /**
   * Named SSE event types that mark a terminal stream outcome.
   * `onTerminal` runs before the connection is closed (`journal-aware` / explicit close).
   */
  terminalEvents?: string[];
  onTerminal?: (event: MessageEvent, type: string) => void;
  /** `poll-fallback` — start HTTP polling when SSE fails or cannot open. */
  onPollFallback?: () => void;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

export interface HermesEventSourceHandle {
  close: () => void;
}

function sseBackoffDelayMs(
  attempt: number,
  initialMs: number,
  maxMs: number,
): number {
  const exp = initialMs * 2 ** attempt;
  return Math.min(maxMs, exp);
}

function effectivePolicy(policy: HermesSseReconnectPolicy): HermesSseReconnectPolicy {
  if (policy === "journal-aware") {
    return "none";
  }
  return policy;
}

/**
 * Hermes WebUI EventSource adapter — wraps `openEventSource` with shared lifecycle,
 * reconnect/backoff, poll fallback, and terminal event hooks for sidebar streams.
 */
export function createHermesEventSource(
  options: CreateHermesEventSourceOptions,
): HermesEventSourceHandle {
  const {
    path,
    query,
    policy,
    listeners,
    onOpen,
    terminalEvents = [],
    onTerminal,
    onPollFallback,
    initialBackoffMs = SSE_INITIAL_BACKOFF_MS,
    maxBackoffMs = SSE_MAX_BACKOFF_MS,
  } = options;

  const activePolicy = effectivePolicy(policy);

  if (typeof EventSource === "undefined") {
    if (activePolicy === "poll-fallback") {
      onPollFallback?.();
    }
    return { close: () => {} };
  }

  let cancelled = false;
  let source: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  let reconnectScheduled = false;
  let pollFallbackStarted = false;
  let terminal = false;

  const terminalHandlers = new Map<string, (event: MessageEvent) => void>();

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    reconnectScheduled = false;
  };

  const startPollFallback = () => {
    if (pollFallbackStarted || cancelled) return;
    pollFallbackStarted = true;
    detachSource();
    onPollFallback?.();
  };

  const detachSource = () => {
    if (!source) return;
    for (const { type, handler } of listeners) {
      source.removeEventListener(type, handler);
    }
    for (const [type, handler] of terminalHandlers) {
      source.removeEventListener(type, handler);
    }
    if (onOpen || activePolicy === "invalidate-only") {
      source.removeEventListener("open", handleOpen);
    }
    source.onerror = null;
    source.close();
    source = null;
  };

  const handleOpen = () => {
    reconnectAttempt = 0;
    onOpen?.();
  };

  const scheduleReconnect = () => {
    if (cancelled || reconnectScheduled || activePolicy !== "invalidate-only") return;
    reconnectScheduled = true;
    detachSource();

    const delayMs = sseBackoffDelayMs(
      reconnectAttempt,
      initialBackoffMs,
      maxBackoffMs,
    );
    reconnectAttempt += 1;

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      reconnectScheduled = false;
      connect();
    }, delayMs);
  };

  const handleSourceError = () => {
    if (cancelled || terminal) return;
    if (activePolicy === "poll-fallback") {
      startPollFallback();
      return;
    }
    if (activePolicy === "invalidate-only") {
      scheduleReconnect();
    }
  };

  const connect = () => {
    if (cancelled || terminal) return;
    clearReconnectTimer();
    detachSource();

    try {
      source = openEventSource(path, query);
    } catch {
      if (activePolicy === "poll-fallback") {
        startPollFallback();
      }
      return;
    }

    for (const { type, handler } of listeners) {
      source.addEventListener(type, handler);
    }

    for (const type of terminalEvents) {
      const handler = (event: MessageEvent) => {
        if (terminal) return;
        terminal = true;
        onTerminal?.(event, type);
        detachSource();
      };
      terminalHandlers.set(type, handler);
      source.addEventListener(type, handler);
    }

    if (onOpen || activePolicy === "invalidate-only") {
      source.addEventListener("open", handleOpen);
    }

    if (activePolicy === "invalidate-only" || activePolicy === "poll-fallback") {
      source.onerror = handleSourceError;
    }
  };

  if (activePolicy === "poll-fallback") {
    try {
      connect();
    } catch {
      startPollFallback();
    }
  } else {
    connect();
  }

  return {
    close: () => {
      cancelled = true;
      clearReconnectTimer();
      detachSource();
    },
  };
}
