/**
 * Provider settings API — keys, quota (M39).
 */
import { fetchJson } from "@/lib/api";
import type { HermesProviderSummary } from "@/services/hermes/models";

export type ProviderEntry = HermesProviderSummary & {
  id?: string;
  display_name?: string;
  configurable?: boolean;
  is_oauth?: boolean;
  is_custom?: boolean;
  has_key?: boolean;
  key_source?: string;
  auth_error?: string;
  models_total?: number;
  models?: unknown[];
};

export type ProvidersListResponse = {
  providers: ProviderEntry[];
  [key: string]: unknown;
};

export type ProviderQuotaStatus = {
  ok?: boolean;
  status?: string;
  provider?: string;
  display_name?: string;
  message?: string;
  quota?: Record<string, unknown> | null;
  account_limits?: Record<string, unknown> | null;
  client_fetched_at?: string;
};

/** GET /api/v1/providers */
export async function fetchProviders(): Promise<ProvidersListResponse> {
  const raw = await fetchJson<unknown>("/providers");
  if (typeof raw !== "object" || raw === null || !Array.isArray((raw as ProvidersListResponse).providers)) {
    return { providers: [] };
  }
  return raw as ProvidersListResponse;
}

/** GET /api/v1/provider/quota */
export async function fetchProviderQuota(refresh = false): Promise<ProviderQuotaStatus> {
  const raw = await fetchJson<ProviderQuotaStatus>("/provider/quota", {
    query: refresh ? { refresh: "1", ts: Date.now() } : undefined,
  });
  return { ...raw, client_fetched_at: new Date().toISOString() };
}

/** POST /api/v1/providers — set or clear API key. */
export async function setProviderKey(
  provider: string,
  apiKey?: string | null,
): Promise<{ ok?: boolean; error?: string }> {
  return fetchJson("/providers", {
    method: "POST",
    body: { provider, api_key: apiKey ?? "" },
  });
}

/** POST /api/v1/providers/delete — remove stored key. */
export async function removeProviderKey(provider: string): Promise<{ ok?: boolean; error?: string }> {
  return fetchJson("/providers/delete", {
    method: "POST",
    body: { provider },
  });
}
