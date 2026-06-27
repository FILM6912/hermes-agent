import { fetchJson, openEventSource } from "@/lib/api";

export interface TerminalStartResponse {
  ok: boolean;
  session_id: string;
  workspace: string;
  running: boolean;
}

export interface TerminalCloseResponse {
  ok: boolean;
  closed: boolean;
}

/** POST /api/v1/terminal/start */
export async function startTerminal(params: {
  session_id: string;
  rows?: number;
  cols?: number;
  restart?: boolean;
}): Promise<TerminalStartResponse> {
  return fetchJson<TerminalStartResponse>("/terminal/start", {
    method: "POST",
    body: params,
  });
}

/** POST /api/v1/terminal/input */
export async function sendTerminalInput(
  sessionId: string,
  data: string,
): Promise<{ ok: boolean }> {
  return fetchJson("/terminal/input", {
    method: "POST",
    body: { session_id: sessionId, data },
  });
}

/** POST /api/v1/terminal/resize */
export async function resizeTerminal(params: {
  session_id: string;
  rows: number;
  cols: number;
}): Promise<{ ok: boolean }> {
  return fetchJson("/terminal/resize", {
    method: "POST",
    body: params,
  });
}

/** POST /api/v1/terminal/close */
export async function closeTerminal(sessionId: string): Promise<TerminalCloseResponse> {
  return fetchJson<TerminalCloseResponse>("/terminal/close", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** GET /api/v1/terminal/output — SSE stream for PTY output. */
export function openTerminalOutput(sessionId: string): EventSource {
  return openEventSource("/terminal/output", { session_id: sessionId });
}
