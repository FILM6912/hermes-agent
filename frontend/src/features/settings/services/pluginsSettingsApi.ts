/**
 * Plugins visibility API (M39) — read-only panel parity with Hermes settings.
 */
import { fetchJson } from "@/lib/api";

export type PluginEntry = {
  name?: string;
  key?: string;
  version?: string;
  description?: string;
  enabled?: boolean;
  activation?: string;
  kind?: string;
  hooks?: string[];
};

export type PluginsListResponse = {
  plugins: PluginEntry[];
  supported_hooks?: string[];
  empty?: boolean;
};

/** GET /api/v1/plugins */
export async function fetchPlugins(): Promise<PluginsListResponse> {
  const raw = await fetchJson<unknown>("/plugins");
  if (typeof raw !== "object" || raw === null) {
    return { plugins: [] };
  }
  const data = raw as PluginsListResponse;
  return {
    ...data,
    plugins: Array.isArray(data.plugins) ? data.plugins : [],
  };
}
