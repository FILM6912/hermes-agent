import React from "react";
import { WifiOff } from "lucide-react";
import { useOnlineStatus } from "@/hooks/useOnlineStatus";

export interface OfflineBannerProps {
  /** When false, no banner or probes run. Default true. */
  enabled?: boolean;
  /** While true, suppress Hermes-unreachable banner during active chat streams. */
  streamingActive?: boolean;
}

/**
 * M39-reliability — fixed banner when the browser is offline or Hermes is unreachable.
 */
export function OfflineBanner({
  enabled = true,
  streamingActive = false,
}: OfflineBannerProps): React.ReactElement | null {
  const { isOffline, browserOnline, apiReachable, retryProbe } = useOnlineStatus(
    enabled,
    { suppressWhileStreaming: streamingActive },
  );

  if (!enabled || !isOffline) {
    return null;
  }

  const message = !browserOnline
    ? "You are offline. Check your network connection."
    : !apiReachable
      ? "Cannot reach Hermes. The server may be down or restarting."
      : "Connection unavailable.";

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-0 top-0 z-[10000] flex items-center justify-center gap-2 border-b border-amber-300/80 bg-amber-100 px-4 py-2 text-sm text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/90 dark:text-amber-100"
    >
      <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
      <span className="text-center">{message}</span>
      {browserOnline && !apiReachable ? (
        <button
          type="button"
          onClick={retryProbe}
          className="ml-2 shrink-0 rounded-md border border-amber-400/80 bg-amber-50 px-2 py-0.5 text-xs font-medium hover:bg-amber-200 dark:border-amber-600 dark:bg-amber-900/50 dark:hover:bg-amber-900"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
