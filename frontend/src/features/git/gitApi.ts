import { fetchJson } from "@/lib/api";

export type GitFileEntry = {
  path: string;
  status?: string;
  staged?: boolean;
  unstaged?: boolean;
  untracked?: boolean;
  ignored?: boolean;
  additions?: number;
  deletions?: number;
  old_path?: string;
};

export type GitTotals = {
  changed?: number;
  staged?: number;
  unstaged?: number;
  untracked?: number;
  conflicts?: number;
};

export type GitStatusPayload = {
  is_git: boolean;
  branch?: string;
  upstream?: string;
  ahead?: number;
  behind?: number;
  files?: GitFileEntry[];
  totals?: GitTotals;
  noise_filtering?: { active?: boolean; crlf_only?: number };
};

export type GitBranchEntry = {
  name: string;
  current?: boolean;
  remote?: boolean;
  upstream?: string;
};

export type GitBranchesPayload = {
  is_git?: boolean;
  current?: string;
  detached?: boolean;
  head?: string;
  local?: GitBranchEntry[];
  remote?: GitBranchEntry[];
  upstream?: string;
  ahead?: number;
  behind?: number;
};

export type GitStatusResponse = {
  git?: GitStatusPayload;
  error?: string;
};

export type GitBranchesResponse = {
  branches?: GitBranchesPayload;
  error?: string;
};

export type GitDiffResponse = {
  diff?: string;
  error?: string;
};

export type GitMutationResponse = {
  ok?: boolean;
  git?: GitStatusPayload;
  message?: string;
  error?: string;
};

export type GitCommitMessageResponse = {
  message?: string;
  error?: string;
};

function sessionQuery(sessionId: string): Record<string, string> {
  return { session_id: sessionId };
}

/** GET /api/v1/git/status */
export async function fetchGitStatus(sessionId: string): Promise<GitStatusResponse> {
  return fetchJson<GitStatusResponse>("/git/status", { query: sessionQuery(sessionId) });
}

/** GET /api/v1/git/branches */
export async function fetchGitBranches(sessionId: string): Promise<GitBranchesResponse> {
  return fetchJson<GitBranchesResponse>("/git/branches", { query: sessionQuery(sessionId) });
}

/** GET /api/v1/git/diff */
export async function fetchGitDiff(
  sessionId: string,
  path: string,
  kind: "unstaged" | "staged" = "unstaged",
): Promise<GitDiffResponse> {
  return fetchJson<GitDiffResponse>("/git/diff", {
    query: { ...sessionQuery(sessionId), path, kind },
  });
}

/** POST /api/v1/git/stage */
export async function gitStage(sessionId: string, paths: string[]): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/stage", {
    method: "POST",
    body: { session_id: sessionId, paths },
  });
}

/** POST /api/v1/git/unstage */
export async function gitUnstage(sessionId: string, paths: string[]): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/unstage", {
    method: "POST",
    body: { session_id: sessionId, paths },
  });
}

/** POST /api/v1/git/discard */
export async function gitDiscard(
  sessionId: string,
  paths: string[],
  deleteUntracked = false,
): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/discard", {
    method: "POST",
    body: { session_id: sessionId, paths, delete_untracked: deleteUntracked },
  });
}

/** POST /api/v1/git/commit-message */
export async function gitCommitMessage(sessionId: string): Promise<GitCommitMessageResponse> {
  return fetchJson<GitCommitMessageResponse>("/git/commit-message", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** POST /api/v1/git/commit */
export async function gitCommit(
  sessionId: string,
  message: string,
): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/commit", {
    method: "POST",
    body: { session_id: sessionId, message },
  });
}

/** POST /api/v1/git/pull */
export async function gitPull(sessionId: string): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/pull", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** POST /api/v1/git/push */
export async function gitPush(sessionId: string): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/push", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** POST /api/v1/git/fetch */
export async function gitFetch(sessionId: string): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/fetch", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

/** POST /api/v1/git/checkout */
export async function gitCheckout(
  sessionId: string,
  ref: string,
): Promise<GitMutationResponse> {
  return fetchJson<GitMutationResponse>("/git/checkout", {
    method: "POST",
    body: { session_id: sessionId, ref },
  });
}
