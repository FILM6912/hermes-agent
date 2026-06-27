export type HermesProject = {
  project_id: string;
  name: string;
  color?: string | null;
  profile?: string;
  created_at?: number;
};

export type ProjectsListResponse = {
  projects: HermesProject[];
  all_profiles?: boolean;
  active_profile?: string;
  other_profile_count?: number;
};

export type ProjectMutationResponse = {
  ok?: boolean;
  error?: string;
  project?: HermesProject;
};

export const PROJECT_COLORS = [
  "#7cb9ff",
  "#f5c542",
  "#e94560",
  "#50c878",
  "#c084fc",
  "#fb923c",
  "#67e8f9",
  "#f472b6",
] as const;

/** Filter sentinel for sessions with no project_id. */
export const NO_PROJECT_FILTER = "__none__" as const;

export type ProjectFilter = string | null | typeof NO_PROJECT_FILTER;
