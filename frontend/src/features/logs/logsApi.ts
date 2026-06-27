import { fetchJson } from "@/lib/api";

export type LogsQuery = {
  file?: string;
  tail?: number;
  profile?: string;
  username?: string;
};

export type LogsResponse = {
  file: string;
  tail: number;
  lines: string[];
  truncated: boolean;
  total_bytes: number;
  mtime: number | null;
  hint?: string;
  profile?: string | null;
};

export const LOG_FILE_OPTIONS = [
  { value: "agent", label: "Agent" },
  { value: "webui", label: "WebUI" },
  { value: "gateway", label: "Gateway" },
] as const;

export const LOG_TAIL_OPTIONS = [100, 200, 500, 1000] as const;

export type LogSeverityFilter = "all" | "errors" | "warnings";

export function severityForLogLine(line: string): string {
  const text = line.toUpperCase();
  if (/\b(ERROR|CRITICAL|TRACEBACK)\b/.test(text)) return "error";
  if (/\b(WARNING|WARN)\b/.test(text)) return "warning";
  if (/\b(DEBUG)\b/.test(text)) return "debug";
  if (/\b(INFO)\b/.test(text)) return "info";
  return "other";
}

export function filterLogLines(
  lines: string[],
  severity: LogSeverityFilter,
): string[] {
  if (severity === "all") return lines;
  return lines.filter((line) => {
    const sev = severityForLogLine(line);
    if (severity === "errors") return sev === "error";
    if (severity === "warnings") return sev === "warning" || sev === "error";
    return true;
  });
}

/** GET /api/v1/logs */
export async function fetchLogs(query?: LogsQuery): Promise<LogsResponse> {
  return fetchJson<LogsResponse>("/logs", {
    query: {
      file: query?.file,
      tail: query?.tail,
      profile: query?.profile,
      username: query?.username,
    },
  });
}
