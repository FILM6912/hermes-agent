/**
 * Hermes profile API — list and switch active agent profiles (M06).
 */
import { fetchJson } from "@/lib/api";

export type HermesProfileSummary = {
  name: string;
  path: string;
  is_default?: boolean;
  is_active?: boolean;
  gateway_running?: boolean;
  model?: string | null;
  provider?: string | null;
  has_env?: boolean;
  skill_count?: number;
  [key: string]: unknown;
};

export type HermesProfilesResponse = {
  profiles: HermesProfileSummary[];
  active: string;
};

export type HermesProfileSwitchResponse = {
  active: string;
  default_model?: string | null;
  default_model_provider?: string | null;
  default_workspace?: string | null;
  [key: string]: unknown;
};

/** Single bound profile entry for non-admin multi-user callers. */
export function boundProfileSummaries(
  profileName: string | null | undefined,
): HermesProfileSummary[] {
  const name = profileName?.trim();
  if (!name) return [];
  return [{ name, path: "", is_active: true }];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function narrowProfile(value: unknown): HermesProfileSummary | null {
  if (!isRecord(value) || typeof value.name !== "string" || typeof value.path !== "string") {
    return null;
  }
  return {
    ...value,
    name: value.name,
    path: value.path,
    is_default: typeof value.is_default === "boolean" ? value.is_default : undefined,
    is_active: typeof value.is_active === "boolean" ? value.is_active : undefined,
    gateway_running:
      typeof value.gateway_running === "boolean" ? value.gateway_running : undefined,
    model: typeof value.model === "string" ? value.model : value.model === null ? null : undefined,
    provider:
      typeof value.provider === "string" ? value.provider : value.provider === null ? null : undefined,
    has_env: typeof value.has_env === "boolean" ? value.has_env : undefined,
    skill_count: typeof value.skill_count === "number" ? value.skill_count : undefined,
  };
}

function dedupeProfiles(profiles: HermesProfileSummary[]): HermesProfileSummary[] {
  const rank = (profile: HermesProfileSummary): number =>
    (profile.is_default ? 2 : 0) + (profile.is_active ? 1 : 0);
  const bestByName = new Map<string, HermesProfileSummary>();
  const order: string[] = [];
  for (const profile of profiles) {
    const name = profile.name.trim();
    if (!name) continue;
    const existing = bestByName.get(name);
    if (!existing) {
      bestByName.set(name, profile);
      order.push(name);
      continue;
    }
    if (rank(profile) > rank(existing)) {
      bestByName.set(name, profile);
    }
  }
  return order.map((name) => bestByName.get(name)!);
}

function narrowProfilesResponse(value: unknown): HermesProfilesResponse {
  if (!isRecord(value) || !Array.isArray(value.profiles)) {
    return { profiles: [], active: "" };
  }
  const profiles = dedupeProfiles(
    value.profiles
      .map(narrowProfile)
      .filter((profile): profile is HermesProfileSummary => profile !== null),
  );
  return {
    profiles,
    active: typeof value.active === "string" ? value.active : profiles.find((p) => p.is_active)?.name ?? "",
  };
}

/** Resolve active profile name from GET /api/v1/profiles. */
export async function resolveActiveProfileName(): Promise<string> {
  try {
    const data = await listProfiles();
    return data.active || data.profiles.find((p) => p.is_active)?.name || "default";
  } catch {
    return "default";
  }
}

/** GET /api/v1/profiles — list profiles and active profile name. */
export async function listProfiles(): Promise<HermesProfilesResponse> {
  const raw = await fetchJson<unknown>("/profiles");
  return narrowProfilesResponse(raw);
}

/** POST /api/v1/profile/switch — set active profile cookie for this client. */
export async function switchProfile(name: string): Promise<HermesProfileSwitchResponse> {
  const raw = await fetchJson<unknown>("/profile/switch", {
    method: "POST",
    body: { name },
  });
  if (!isRecord(raw) || typeof raw.active !== "string") {
    throw new Error("Invalid profile switch response");
  }
  return raw as HermesProfileSwitchResponse;
}

export { useActiveProfile, ActiveProfileProvider } from "@/hooks/useActiveProfile";
export type { ActiveProfileContextValue } from "@/hooks/useActiveProfile";
