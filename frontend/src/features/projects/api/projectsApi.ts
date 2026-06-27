import { fetchJson } from "@/lib/api";
import type {
  ProjectMutationResponse,
  ProjectsListResponse,
} from "../types";

/** GET /api/v1/projects */
export async function listProjects(allProfiles = false): Promise<ProjectsListResponse> {
  return fetchJson<ProjectsListResponse>("/projects", {
    query: allProfiles ? { all_profiles: "1" } : undefined,
  });
}

/** POST /api/v1/projects/create */
export async function createProject(
  name: string,
  color?: string,
): Promise<ProjectMutationResponse> {
  return fetchJson<ProjectMutationResponse>("/projects/create", {
    method: "POST",
    body: { name: name.trim(), color },
  });
}

/** POST /api/v1/projects/rename */
export async function renameProject(
  projectId: string,
  name: string,
  color?: string | null,
): Promise<ProjectMutationResponse> {
  return fetchJson<ProjectMutationResponse>("/projects/rename", {
    method: "POST",
    body: { project_id: projectId, name: name.trim(), color },
  });
}

/** POST /api/v1/projects/delete */
export async function deleteProject(projectId: string): Promise<ProjectMutationResponse> {
  return fetchJson<ProjectMutationResponse>("/projects/delete", {
    method: "POST",
    body: { project_id: projectId },
  });
}

/** POST /api/v1/session/move */
export async function moveSessionToProject(
  sessionId: string,
  projectId: string | null,
): Promise<{ ok?: boolean; error?: string }> {
  return fetchJson("/session/move", {
    method: "POST",
    body: { session_id: sessionId, project_id: projectId },
  });
}
