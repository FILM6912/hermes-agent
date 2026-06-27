export type HermesSkill = {
  name: string;
  description?: string;
  category?: string;
  disabled?: boolean;
  readonly?: boolean;
  source?: "default" | "user" | "external";
};

export type SkillsListResponse = {
  skills: HermesSkill[];
  categories?: string[];
  count?: number;
  success?: boolean;
};

export type SkillContentResponse = {
  content?: string;
  linked_files?: Record<string, string[]>;
  success?: boolean;
  error?: string;
};

export type SkillsHubPreviewResponse = {
  success?: boolean;
  error?: string;
  name?: string;
  description?: string;
  identifier?: string;
  source?: string;
  trust_level?: string;
  content?: string;
};

export type SkillsHubResult = {
  identifier: string;
  name: string;
  description?: string;
  source?: string;
  trust_level?: string;
  repo?: string;
  installs?: number;
  detail_url?: string;
  repo_url?: string;
};

export type SkillsHubGroup = {
  repo: string;
  skill_count: number;
  total_installs?: number | null;
  skills: SkillsHubResult[];
};

export type SkillsHubSearchResponse = {
  results: SkillsHubResult[];
  groups?: SkillsHubGroup[];
  query?: string;
  source?: string;
  limit?: number;
};

export type SkillMutationResponse = {
  ok?: boolean;
  error?: string;
  message?: string;
  identifier?: string;
};
