import { fetchJson } from "@/lib/api";

export type HermesProfileSummary = {
  name: string;
  display_name?: string | null;
  is_active?: boolean;
  is_default?: boolean;
  [key: string]: unknown;
};

export type HermesProfilesResponse = {
  active?: string;
  profiles: HermesProfileSummary[];
};

export type HermesProfileSwitchResponse = {
  active: string;
};

export function boundProfileSummaries(activeName?: string | null): HermesProfileSummary[] {
  const name = activeName?.trim() || "default";
  return [{ name, is_active: true, is_default: name === "default" }];
}

const SAFE_PROFILES: HermesProfilesResponse = { profiles: [], active: "" };

export async function listProfiles(): Promise<HermesProfilesResponse> {
  try {
    return await fetchJson<HermesProfilesResponse>("/profiles");
  } catch {
    return SAFE_PROFILES;
  }
}

export async function switchProfile(name: string): Promise<HermesProfileSwitchResponse> {
  return fetchJson<HermesProfileSwitchResponse>("/profile/switch", {
    method: "POST",
    body: { name },
  });
}
