import { fetchJson } from "@/lib/api";

/** Hermes skills_hub source id for https://skills.sh (not browse.sh). */
export const DEFAULT_SKILLS_HUB_SOURCE = "skills-sh";
import type {
  SkillContentResponse,
  SkillMutationResponse,
  SkillsHubPreviewResponse,
  SkillsHubSearchResponse,
  SkillsListResponse,
} from "../types";

/** GET /api/v1/skills */
export async function listSkills(category?: string): Promise<SkillsListResponse> {
  return fetchJson<SkillsListResponse>("/skills", {
    query: category ? { category } : undefined,
  });
}

/** GET /api/v1/skills/content */
export async function fetchSkillContent(
  name: string,
  file?: string,
): Promise<SkillContentResponse> {
  return fetchJson<SkillContentResponse>("/skills/content", {
    query: { name, ...(file ? { file } : {}) },
  });
}

/** POST /api/v1/skills/toggle */
export async function toggleSkill(
  name: string,
  enabled: boolean,
): Promise<SkillMutationResponse> {
  return fetchJson<SkillMutationResponse>("/skills/toggle", {
    method: "POST",
    body: { name, enabled },
  });
}

/** POST /api/v1/skills/save */
export async function saveSkill(payload: {
  name: string;
  content: string;
  category?: string;
}): Promise<SkillMutationResponse> {
  return fetchJson<SkillMutationResponse>("/skills/save", {
    method: "POST",
    body: payload,
  });
}

/** POST /api/v1/skills/delete */
export async function deleteSkill(name: string): Promise<SkillMutationResponse> {
  return fetchJson<SkillMutationResponse>("/skills/delete", {
    method: "POST",
    body: { name },
  });
}

/** GET /api/v1/skills/hub/preview */
export async function fetchSkillsHubPreview(
  identifier: string,
): Promise<SkillsHubPreviewResponse> {
  return fetchJson<SkillsHubPreviewResponse>("/skills/hub/preview", {
    query: { identifier },
  });
}

const REPO_HUB_QUERY_RE = /^[^/\s]+\/[^/\s]+$/;

function hubSearchLimit(q: string, requested = 12): number {
  const trimmed = q.trim();
  if (REPO_HUB_QUERY_RE.test(trimmed)) return 50;
  return requested;
}

/** GET /api/v1/skills/hub/search */
export async function searchSkillsHub(
  q: string,
  options?: { source?: string; limit?: number },
): Promise<SkillsHubSearchResponse> {
  const limit = hubSearchLimit(q, options?.limit ?? 12);
  return fetchJson<SkillsHubSearchResponse>("/skills/hub/search", {
    query: {
      q,
      source: options?.source ?? DEFAULT_SKILLS_HUB_SOURCE,
      limit,
    },
  });
}

/** POST /api/v1/skills/install */
export async function installSkillFromHub(
  identifier: string,
  options?: { category?: string; force?: boolean },
): Promise<SkillMutationResponse> {
  return fetchJson<SkillMutationResponse>("/skills/install", {
    method: "POST",
    body: {
      identifier,
      category: options?.category,
      force: options?.force,
    },
  });
}
