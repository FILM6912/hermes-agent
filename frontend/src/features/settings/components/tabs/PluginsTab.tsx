import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Puzzle, RefreshCw } from "lucide-react";
import {
  fetchPlugins,
  type PluginEntry,
} from "../../services/pluginsSettingsApi";

function activationLabel(plugin: PluginEntry): { text: string; tone: string } {
  const activation =
    typeof plugin.activation === "string"
      ? plugin.activation
      : plugin.enabled === false
        ? "disabled"
        : "enabled";

  if (activation === "exclusive" || activation === "provider") {
    return { text: "Active provider", tone: "bg-violet-500/15 text-violet-700 dark:text-violet-300" };
  }
  if (activation === "enabled") {
    return { text: "Enabled", tone: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" };
  }
  return { text: "Disabled", tone: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400" };
}

function PluginCard({ plugin }: { plugin: PluginEntry }) {
  const badge = activationLabel(plugin);
  const hooks = Array.isArray(plugin.hooks) ? plugin.hooks : [];
  const isProvider =
    plugin.activation === "exclusive" || plugin.activation === "provider";

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
            {plugin.name || plugin.key || "Unnamed plugin"}
          </div>
          <div className="text-xs text-zinc-500">
            {plugin.key}
            {plugin.version ? ` · v${plugin.version}` : ""}
          </div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs ${badge.tone}`}>{badge.text}</span>
      </div>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        {plugin.description || "No description provided."}
      </p>
      <div className="mt-3">
        <div className="text-xs font-medium text-zinc-500">Registered hooks</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {hooks.length > 0 ? (
            hooks.map((hook) => (
              <span
                key={hook}
                className="rounded-md bg-zinc-100 px-2 py-0.5 font-mono text-xs dark:bg-zinc-800"
              >
                {hook}
              </span>
            ))
          ) : (
            <span className="text-xs text-zinc-500">
              {isProvider
                ? "Provider plugins register category-specific hooks not shown here."
                : "No registered lifecycle hooks."}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export const PluginsTab: React.FC = () => {
  const [plugins, setPlugins] = useState<PluginEntry[]>([]);
  const [supportedHooks, setSupportedHooks] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPlugins();
      setPlugins(data.plugins ?? []);
      setSupportedHooks(data.supported_hooks ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          View installed Hermes plugins and the lifecycle hooks they register. Read-only.
        </p>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh plugins"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {supportedHooks.length > 0 && (
        <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900/40 dark:text-zinc-400">
          Supported agent hooks: {supportedHooks.join(", ")}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {loading && plugins.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading plugins…
        </div>
      ) : plugins.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-zinc-500">
          <Puzzle className="h-8 w-8 opacity-40" />
          No Hermes plugins are currently visible.
        </div>
      ) : (
        <div className="space-y-3">
          {plugins.map((plugin) => (
            <PluginCard key={plugin.key || plugin.name} plugin={plugin} />
          ))}
        </div>
      )}
    </div>
  );
};
