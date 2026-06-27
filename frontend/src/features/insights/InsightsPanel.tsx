import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { HermesApiError } from "@/lib/api";
import type { AuthStatus } from "@/features/auth/services/authService";
import {
  fetchInsights,
  loadInsightsLogsScopeOptions,
  type DailyTokenRow,
  type InsightsResponse,
  type InsightsLogsScopeOption,
} from "./insightsApi";
import { scopeToQuery } from "./scopeQuery";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";

type ScopeOption = InsightsLogsScopeOption;

function fmtNum(n: number): string {
  return Number(n || 0).toLocaleString();
}

function fmtTokens(n: number): string {
  const value = Number(n || 0);
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return fmtNum(value);
}

function fmtCost(c: number): string {
  const value = Number(c || 0);
  if (value <= 0) return "—";
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}

function bucketDailyTokens(rows: DailyTokenRow[]): DailyTokenRow[] {
  if (rows.length <= 30) return rows;
  const len = rows.length;
  const bucketSize = len <= 90 ? 2 : len <= 180 ? 3 : 8;
  const result: DailyTokenRow[] = [];
  for (let i = 0; i < len; i += bucketSize) {
    const slice = rows.slice(i, i + bucketSize);
    result.push({
      date: slice[0].date,
      input_tokens: slice.reduce((s, r) => s + (r.input_tokens || 0), 0),
      output_tokens: slice.reduce((s, r) => s + (r.output_tokens || 0), 0),
      sessions: slice.reduce((s, r) => s + (r.sessions || 0), 0),
      cost: slice.reduce((s, r) => s + (r.cost || 0), 0),
    });
  }
  return result;
}

interface InsightsPanelProps {
  onBack: () => void;
  authStatus: AuthStatus | null;
}

export const InsightsPanel: React.FC<InsightsPanelProps> = ({ onBack, authStatus }) => {
  const { canManageUsers } = useAuthRole();
  const [days, setDays] = useState(30);
  const [scope, setScope] = useState("");
  const [scopeOptions, setScopeOptions] = useState<ScopeOption[]>([]);
  const [data, setData] = useState<InsightsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      const result = await fetchInsights({ days, ...scopeToQuery(scope) });
      setData(result);
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load insights";
      setError(message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [days, scope]);

  useEffect(() => {
    void load();
  }, [load]);

  const chartRows = useMemo(
    () => bucketDailyTokens(data?.daily_tokens ?? []),
    [data?.daily_tokens],
  );

  const maxDaily = Math.max(
    ...chartRows.map((r) => (r.input_tokens || 0) + (r.output_tokens || 0)),
    1,
  );

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
        <BarChart3 className="h-5 w-5 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Insights</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            Usage analytics across sessions
          </p>
        </div>
        <select
          value={String(days)}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          aria-label="Period"
        >
          <option value="7">7 days</option>
          <option value="30">30 days</option>
          <option value="90">90 days</option>
          <option value="180">180 days</option>
          <option value="365">365 days</option>
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
            Loading insights…
          </div>
        ) : error ? (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-300">
            {error}
          </div>
        ) : data ? (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[
                { label: "Sessions", value: fmtNum(data.total_sessions) },
                { label: "Messages", value: fmtNum(data.total_messages) },
                { label: "Tokens", value: fmtTokens(data.total_tokens) },
                { label: "Cost", value: fmtCost(data.total_cost) },
              ].map((card) => (
                <div
                  key={card.label}
                  className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/50"
                >
                  <div className="text-xs text-zinc-500 dark:text-zinc-400">{card.label}</div>
                  <div className="mt-1 text-xl font-semibold">{card.value}</div>
                </div>
              ))}
            </div>

            {chartRows.length > 0 && (
              <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/50">
                <h2 className="mb-3 text-sm font-medium">Daily tokens</h2>
                <div className="flex h-40 items-end gap-1">
                  {chartRows.map((row) => {
                    const total = (row.input_tokens || 0) + (row.output_tokens || 0);
                    const heightPct = Math.max((total / maxDaily) * 100, total ? 4 : 0);
                    const inputPct =
                      total > 0 ? ((row.input_tokens || 0) / total) * 100 : 50;
                    return (
                      <div
                        key={row.date}
                        className="group relative flex min-w-0 flex-1 flex-col justify-end"
                        title={`${row.date}: ${fmtTokens(total)} tokens`}
                      >
                        <div
                          className="w-full overflow-hidden rounded-t bg-indigo-200 dark:bg-indigo-900/40"
                          style={{ height: `${heightPct}%` }}
                        >
                          <div
                            className="h-full bg-indigo-500 dark:bg-indigo-400"
                            style={{ height: `${inputPct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {data.models.length > 0 && (
              <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/50">
                <h2 className="border-b border-zinc-200 px-4 py-3 text-sm font-medium dark:border-zinc-800">
                  Model usage
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="text-xs text-zinc-500 dark:text-zinc-400">
                        <th className="px-4 py-2 font-medium">Model</th>
                        <th className="px-4 py-2 font-medium">Sessions</th>
                        <th className="px-4 py-2 font-medium">Tokens</th>
                        <th className="px-4 py-2 font-medium">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.models.map((row) => (
                        <tr
                          key={row.model}
                          className="border-t border-zinc-100 dark:border-zinc-800"
                        >
                          <td className="px-4 py-2 font-mono text-xs">{row.model}</td>
                          <td className="px-4 py-2">{row.sessions}</td>
                          <td className="px-4 py-2">{fmtTokens(row.total_tokens)}</td>
                          <td className="px-4 py-2">{fmtCost(row.cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
};
