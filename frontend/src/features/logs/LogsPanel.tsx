import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Loader2,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { HermesApiError } from "@/lib/api";
import type { AuthStatus } from "@/features/auth/services/authService";
import {
  loadInsightsLogsScopeOptions,
  type InsightsLogsScopeOption,
} from "@/features/insights/insightsApi";
import { scopeToQuery } from "@/features/insights/scopeQuery";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";
import {
  fetchLogs,
  filterLogLines,
  LOG_FILE_OPTIONS,
  LOG_TAIL_OPTIONS,
  severityForLogLine,
  type LogSeverityFilter,
  type LogsResponse,
} from "./logsApi";

type ScopeOption = InsightsLogsScopeOption;

function logLineClass(line: string): string {
  const sev = severityForLogLine(line);
  if (sev === "error") return "text-rose-600 dark:text-rose-400";
  if (sev === "warning") return "text-amber-600 dark:text-amber-400";
  if (sev === "debug") return "text-zinc-500 dark:text-zinc-500";
  if (sev === "info") return "text-sky-600 dark:text-sky-400";
  return "text-zinc-700 dark:text-zinc-300";
}

interface LogsPanelProps {
  onBack: () => void;
  authStatus: AuthStatus | null;
}

export const LogsPanel: React.FC<LogsPanelProps> = ({ onBack, authStatus }) => {
  const { canManageUsers } = useAuthRole();
  const [file, setFile] = useState("agent");
  const [tail, setTail] = useState<number>(200);
  const [severity, setSeverity] = useState<LogSeverityFilter>("all");
  const [scope, setScope] = useState("");
  const [scopeOptions, setScopeOptions] = useState<ScopeOption[]>([]);
  const [data, setData] = useState<LogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wrap, setWrap] = useState(true);

  const showScope = !!(authStatus?.multi_user);

  useEffect(() => {
    if (!showScope) return;
    void loadInsightsLogsScopeOptions(authStatus, canManageUsers).then((options) => {
      setScopeOptions(options);
      if (!canManageUsers && options.length === 1) {
        setScope(options[0].value);
      }
    });
  }, [authStatus, canManageUsers, showScope]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchLogs({ file, tail, ...scopeToQuery(scope) });
      setData(result);
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load logs";
      setError(message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [file, tail, scope]);

  useEffect(() => {
    void load();
  }, [load]);

  const displayLines = useMemo(
    () => filterLogLines(data?.lines ?? [], severity),
    [data?.lines, severity],
  );

  const statusText = data
    ? `${displayLines.length} / ${data.lines.length} lines · ${data.total_bytes.toLocaleString()} bytes${
        data.mtime ? ` · ${new Date(data.mtime * 1000).toLocaleString()}` : ""
      }`
    : "";

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <ScrollText className="h-5 w-5 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Logs</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{statusText}</p>
        </div>
        <select
          value={file}
          onChange={(e) => setFile(e.target.value)}
          className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          aria-label="Log file"
        >
          {LOG_FILE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={String(tail)}
          onChange={(e) => setTail(Number(e.target.value))}
          className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          aria-label="Tail lines"
        >
          {LOG_TAIL_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} lines
            </option>
          ))}
        </select>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as LogSeverityFilter)}
          className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          aria-label="Severity filter"
        >
          <option value="all">All severities</option>
          <option value="warnings">Warnings+</option>
          <option value="errors">Errors only</option>
        </select>
        {showScope && (
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="max-w-[180px] rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            aria-label="User scope"
          >
            <option value="">{canManageUsers ? "All users (combined)" : "My scope"}</option>
            {scopeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={wrap}
            onChange={(e) => setWrap(e.target.checked)}
            className="rounded"
          />
          Wrap
        </label>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading && !data ? (
          <div className="flex items-center justify-center py-16 text-zinc-500">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Loading logs…
          </div>
        ) : error ? (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
            {error}
          </div>
        ) : (
          <div className="rounded-xl border border-zinc-200 bg-zinc-950 p-3 font-mono text-xs dark:border-zinc-800">
            {data?.hint ? (
              <div className="mb-2 text-amber-400">{data.hint}</div>
            ) : null}
            {data?.truncated ? (
              <div className="mb-2 text-amber-400">Log file truncated to recent bytes.</div>
            ) : null}
            {severity !== "all" && data?.lines.length ? (
              <div className="mb-2 text-zinc-500">
                Showing {displayLines.length} of {data.lines.length} lines (filtered)
              </div>
            ) : null}
            {displayLines.length === 0 ? (
              <div className="text-zinc-500">No log lines to display.</div>
            ) : (
              displayLines.map((line, idx) => (
                <div
                  key={`${idx}-${line.slice(0, 24)}`}
                  className={`py-0.5 ${logLineClass(line)} ${wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre overflow-x-auto"}`}
                >
                  {line}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
};
