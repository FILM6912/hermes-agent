import React, { useCallback, useEffect, useState } from "react";
import { ChevronDown, Loader2, RefreshCw, KeyRound } from "lucide-react";
import {
  fetchProviderQuota,
  fetchProviders,
  removeProviderKey,
  setProviderKey,
  type ProviderEntry,
  type ProviderQuotaStatus,
} from "../../services/providersSettingsApi";

function formatPercent(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
}

function QuotaCard({
  quota,
  onRefresh,
  refreshing,
}: {
  quota: ProviderQuotaStatus | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  if (!quota) return null;
  const windows = Array.isArray(quota.account_limits?.windows)
    ? (quota.account_limits?.windows as Record<string, unknown>[])
    : [];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">Provider quota</div>
          <div className="text-xs text-zinc-500">
            {quota.display_name || quota.provider || "Active provider"}
          </div>
          {quota.client_fetched_at && (
            <div className="mt-1 text-xs text-zinc-400">
              Last checked {new Date(quota.client_fetched_at).toLocaleString()}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
            {quota.status || "unknown"}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs dark:border-zinc-700"
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {windows.length > 0 ? (
          windows.map((window, idx) => (
            <div key={idx} className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-900/50">
              <div className="text-xs text-zinc-500">
                {String(window.label || `Window ${idx + 1}`)}
              </div>
              <div className="text-lg font-semibold">
                {formatPercent(window.remaining_percent)}
              </div>
            </div>
          ))
        ) : (
          <div className="col-span-full text-sm text-zinc-500">
            {quota.message || "Quota details unavailable for this provider."}
          </div>
        )}
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  onSaved,
}: {
  provider: ProviderEntry;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const id = provider.id || provider.provider || "";
  const displayName = provider.display_name || id;
  const modelCount =
    (Number.isFinite(provider.models_total) ? provider.models_total : undefined) ??
    (Array.isArray(provider.models) ? provider.models.length : 0);
  const isOauth = provider.is_oauth === true;

  const handleSave = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await setProviderKey(id, apiKey);
      if (res.ok === false) throw new Error(res.error || "Failed to save key");
      setApiKey("");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  const handleRemove = async () => {
    if (!window.confirm(`Remove API key for ${displayName}?`)) return;
    setPending(true);
    setError(null);
    try {
      const res = await removeProviderKey(id);
      if (res.ok === false) throw new Error(res.error || "Failed to remove key");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900/40"
      >
        <KeyRound className="h-4 w-4 shrink-0 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{displayName}</div>
          <div className="truncate text-xs text-zinc-500">
            {modelCount > 0 ? `${modelCount} models · ` : ""}
            {provider.has_key ? "Configured" : "Not configured"}
          </div>
        </div>
        {provider.has_key && (
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-300">
            active
          </span>
        )}
        <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="border-t border-zinc-200 px-4 py-4 dark:border-zinc-800">
          {isOauth ? (
            <p className="text-sm text-zinc-500">
              {provider.auth_error ||
                (provider.has_key
                  ? "OAuth provider — manage credentials via hermes auth or config.yaml."
                  : "Not authenticated. Run hermes auth in the terminal.")}
            </p>
          ) : provider.configurable ? (
            <div className="space-y-3">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">API key</span>
                <div className="flex flex-wrap gap-2">
                  <input
                    type={showKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={provider.has_key ? "Replace existing key…" : "Enter API key…"}
                    className="min-w-[200px] flex-1 rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    className="rounded-lg border border-zinc-200 px-3 py-2 text-xs dark:border-zinc-700"
                  >
                    {showKey ? "Hide" : "Show"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleSave()}
                    disabled={pending || !apiKey.trim()}
                    className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                  >
                    Save
                  </button>
                  {provider.has_key && (
                    <button
                      type="button"
                      onClick={() => void handleRemove()}
                      disabled={pending}
                      className="rounded-lg border border-rose-500/40 px-3 py-2 text-xs text-rose-600 dark:text-rose-400"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </label>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">
              {provider.is_custom
                ? "Custom provider — edit via config.yaml or the Hermes CLI."
                : "Provider is managed outside the WebUI."}
            </p>
          )}
          {error && <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{error}</p>}
        </div>
      )}
    </div>
  );
}

export const ProvidersTab: React.FC = () => {
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [quota, setQuota] = useState<ProviderQuotaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [quotaRefreshing, setQuotaRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [providerData, quotaData] = await Promise.all([
        fetchProviders(),
        fetchProviderQuota(false).catch(() => null),
      ]);
      const visible = (providerData.providers ?? []).filter(
        (p) => p.configurable || p.is_oauth || p.is_custom,
      );
      setProviders(visible);
      setQuota(quotaData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshQuota = async () => {
    setQuotaRefreshing(true);
    try {
      const next = await fetchProviderQuota(true);
      setQuota(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setQuotaRefreshing(false);
    }
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Configure provider API keys and view quota usage.
        </p>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh providers"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      <QuotaCard quota={quota} onRefresh={() => void refreshQuota()} refreshing={quotaRefreshing} />

      {loading && providers.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading providers…
        </div>
      ) : providers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-300 py-16 text-center text-sm text-zinc-500 dark:border-zinc-700">
          No configurable providers found.
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((provider) => (
            <ProviderCard
              key={provider.id || provider.provider}
              provider={provider}
              onSaved={() => void load()}
            />
          ))}
        </div>
      )}
    </div>
  );
};
