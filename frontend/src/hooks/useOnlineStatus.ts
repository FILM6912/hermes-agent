import { useCallback, useEffect, useState } from "react";

const HEALTH_PROBE_INTERVAL_MS = 30_000;
// Avoid false "offline" during long-running streams on single-worker servers.
const HEALTH_PROBE_TIMEOUT_MS = 20_000;
const HEALTH_PROBE_FAILURES_BEFORE_OFFLINE = 2;

/** Lightweight Hermes liveness probe (`GET /health`, not under `/api/v1`). */
export async function probeHermesHealth(): Promise<boolean> {
  if (typeof window === "undefined") return true;

  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    HEALTH_PROBE_TIMEOUT_MS,
  );

  try {
    const response = await fetch("/health", {
      method: "GET",
      credentials: "include",
      signal: controller.signal,
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export interface UseOnlineStatusOptions {
  /** Skip unreachable banner/probes while a chat stream is active (avoids false alarms). */
  suppressWhileStreaming?: boolean;
}

export interface OnlineStatus {
  /** Browser `navigator.onLine` (network interface). */
  browserOnline: boolean;
  /** Last `/health` probe succeeded. */
  apiReachable: boolean;
  /** Offline when the browser or Hermes API is unreachable. */
  isOffline: boolean;
  retryProbe: () => void;
}

/**
 * M39-reliability — browser online state plus periodic Hermes `/health` probes.
 */
export function useOnlineStatus(
  enabled = true,
  options: UseOnlineStatusOptions = {},
): OnlineStatus {
  const suppressWhileStreaming = options.suppressWhileStreaming ?? false;
  const [browserOnline, setBrowserOnline] = useState(
    () => typeof navigator === "undefined" || navigator.onLine,
  );
  const [apiReachable, setApiReachable] = useState(true);
  const [, setProbeFailures] = useState(0);

  const runProbe = useCallback(async () => {
    if (!enabled || suppressWhileStreaming) return;
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      setApiReachable(false);
      setProbeFailures(HEALTH_PROBE_FAILURES_BEFORE_OFFLINE);
      return;
    }
    const ok = await probeHermesHealth();
    if (ok) {
      setProbeFailures(0);
      setApiReachable(true);
      return;
    }
    setProbeFailures((prev) => {
      const next = prev + 1;
      if (next >= HEALTH_PROBE_FAILURES_BEFORE_OFFLINE) {
        setApiReachable(false);
      }
      return next;
    });
  }, [enabled, suppressWhileStreaming]);

  useEffect(() => {
    if (!suppressWhileStreaming) return;
    setProbeFailures(0);
    setApiReachable(true);
  }, [suppressWhileStreaming]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    const handleOnline = () => {
      setBrowserOnline(true);
      setProbeFailures(0);
      void runProbe();
    };
    const handleOffline = () => {
      setBrowserOnline(false);
      setApiReachable(false);
      setProbeFailures(HEALTH_PROBE_FAILURES_BEFORE_OFFLINE);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    void runProbe();
    const intervalId = window.setInterval(
      () => void runProbe(),
      HEALTH_PROBE_INTERVAL_MS,
    );

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.clearInterval(intervalId);
    };
  }, [enabled, runProbe]);

  useEffect(() => {
    if (!enabled || suppressWhileStreaming || typeof window === "undefined") return;
    void runProbe();
  }, [enabled, suppressWhileStreaming, runProbe]);

  const hermesUnreachable =
    !suppressWhileStreaming && !apiReachable;

  return {
    browserOnline,
    apiReachable,
    isOffline: !browserOnline || hermesUnreachable,
    retryProbe: () => {
      void runProbe();
    },
  };
}
