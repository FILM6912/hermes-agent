/**
 * Hermes profile admin CRUD — create, delete, sync-from-default (M30b).
 */
import { fetchJson } from "@/lib/api";
import type { HermesProfileSummary, HermesProfilesResponse } from "@/services/hermes/profiles";
import { listProfiles } from "@/services/hermes/profiles";

export type { HermesProfileSummary, HermesProfilesResponse };

export type CreateProfilePayload = {
  name: string;
  clone_from?: string | null;
  clone_config?: boolean | null;
  base_url?: string | null;
  api_key?: string | null;
  default_model?: string | null;
  model_provider?: string | null;
};

export type ProfileCreateResponse = {
  ok?: boolean;
  profile: HermesProfileSummary;
};

export type ProfileDeleteResponse = {
  ok?: boolean;
};

export type ProfileSyncResponse = {
  ok?: boolean;
  name?: string | null;
  added?: Record<string, unknown> | null;
  skipped?: Record<string, unknown> | null;
  profiles?: Record<string, unknown>[] | null;
  error?: string | null;
};

export type ProfileUpdatePayload = {
  name: string;
  default_model?: string | null;
  model_provider?: string | null;
};

export type ProfileUpdateResponse = {
  ok?: boolean;
  profile: HermesProfileSummary;
};

export { listProfiles };

/** POST /api/v1/profile/create */
export async function createProfile(payload: CreateProfilePayload): Promise<ProfileCreateResponse> {
  return fetchJson<ProfileCreateResponse>("/profile/create", {
    method: "POST",
    body: payload,
  });
}

/** POST /api/v1/profile/delete */
export async function deleteProfile(name: string): Promise<ProfileDeleteResponse> {
  return fetchJson<ProfileDeleteResponse>("/profile/delete", {
    method: "POST",
    body: { name },
  });
}

/** POST /api/v1/profile/sync-from-default — sync one profile or all when name omitted. */
export async function syncProfileFromDefault(name?: string | null): Promise<ProfileSyncResponse> {
  return fetchJson<ProfileSyncResponse>("/profile/sync-from-default", {
    method: "POST",
    body: name ? { name } : {},
  });
}

/** POST /api/v1/profile/update — set default model/provider in profile config.yaml. */
export async function updateProfileModel(
  payload: ProfileUpdatePayload,
): Promise<ProfileUpdateResponse> {
  return fetchJson<ProfileUpdateResponse>("/profile/update", {
    method: "POST",
    body: payload,
  });
}
