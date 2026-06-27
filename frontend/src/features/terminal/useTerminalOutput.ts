import { useEffect, useRef } from "react";
import { openTerminalOutput } from "./terminalApi";

export interface UseTerminalOutputOptions {
  sessionId: string | null;
  enabled?: boolean;
  onOutput: (text: string) => void;
  onClosed?: (exitCode?: number | null) => void;
  onError?: (message: string) => void;
}

/**
 * M37 — Subscribe to `GET /api/v1/terminal/output` SSE for workspace PTY output.
 */
export function useTerminalOutput({
  sessionId,
  enabled = true,
  onOutput,
  onClosed,
  onError,
}: UseTerminalOutputOptions): void {
  const outputRef = useRef(onOutput);
  const closedRef = useRef(onClosed);
  const errorRef = useRef(onError);
  outputRef.current = onOutput;
  closedRef.current = onClosed;
  errorRef.current = onError;

  useEffect(() => {
    if (!enabled || !sessionId || typeof EventSource === "undefined") return;

    const source = openTerminalOutput(sessionId);

    const handleOutput = (ev: MessageEvent) => {
      let text = "";
      try {
        const parsed = JSON.parse(String(ev.data ?? "")) as { text?: string };
        text = parsed.text ?? "";
      } catch {
        text = String(ev.data ?? "");
      }
      if (text) outputRef.current(text);
    };

    const handleClosed = (ev: MessageEvent) => {
      let exitCode: number | null = null;
      try {
        const parsed = JSON.parse(String(ev.data ?? "")) as { exit_code?: number | null };
        exitCode = parsed.exit_code ?? null;
      } catch {
        exitCode = null;
      }
      closedRef.current?.(exitCode);
    };

    const handleError = (ev: MessageEvent) => {
      let message = "Terminal error";
      try {
        const parsed = JSON.parse(String(ev.data ?? "")) as { error?: string };
        message = parsed.error || message;
      } catch {
        message = String(ev.data ?? message);
      }
      errorRef.current?.(message);
    };

    source.addEventListener("output", handleOutput as EventListener);
    source.addEventListener("terminal_closed", handleClosed as EventListener);
    source.addEventListener("terminal_error", handleError as EventListener);

    return () => {
      source.removeEventListener("output", handleOutput as EventListener);
      source.removeEventListener("terminal_closed", handleClosed as EventListener);
      source.removeEventListener("terminal_error", handleError as EventListener);
      source.close();
    };
  }, [enabled, sessionId]);
}
