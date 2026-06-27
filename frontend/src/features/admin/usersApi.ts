import { fetchJson } from "@/lib/api";

export type UserRole = string;

export type UserWorkspaceEntry = {
  name: string;
  path: string;
};

export type UserProfileEntry = {
  name: string;
  path: string;
};

export type UserSummary = {
  email: string;
  role: UserRole;
  profile_name?: string | null;
  profile_names?: string[];
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
  workspace_path?: string | null;
  workspaces?: UserWorkspaceEntry[];
  available_workspaces?: UserWorkspaceEntry[];
  assigned_profiles?: UserProfileEntry[];
  enabled?: boolean;
  created_at?: number | null;
  updated_at?: number | null;
  created_by?: string | null;
  updated_by?: string | null;
};

export type UserSessionSummary = {
  total: number;
  active: number;
  archived: number;
};

export type UserDetail = UserSummary & {
  profile?: { name: string } | null;
  session_summary?: UserSessionSummary;
};

export type UserListResponse = {
  users: UserSummary[];
};

export type UserDetailResponse = UserDetail;

export type UserMutationResponse = {
  ok?: boolean;
  user: UserSummary;
};

export type CreateUserPayload = {
  email: string;
  password: string;
  role: UserRole;
  profile_name?: string | null;
  profile_names?: string[] | null;
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
};

export type UpdateUserPayload = {
  email?: string;
  role?: UserRole;
  profile_name?: string | null;
  profile_names?: string[] | null;
  workspace_paths?: string[] | null;
  password?: string;
  display_name?: string | null;
  department?: string | null;
  position?: string | null;
  enabled?: boolean;
};

export type UserEditForm = {
  email: string;
  role: UserRole;
  profile_name: string;
  profile_names: string[];
  workspace_paths: string[];
  display_name: string;
  department: string;
  position: string;
  enabled: boolean;
};

export type AdminWorkspaceEntry = {
  name: string;
  path: string;
  disk_path?: string;
};

/** PATCH body with only fields the admin actually changed. */
export function buildUserUpdatePatch(
  original: UserSummary,
  edit: UserEditForm,
  roleRequiresProfile: (roleId: string) => boolean = (roleId) => roleId !== "admin",
): UpdateUserPayload {
  const payload: UpdateUserPayload = {};
  const origEmail = original.email.trim().toLowerCase();
  const nextEmail = edit.email.trim().toLowerCase();
  if (nextEmail && nextEmail !== origEmail) {
    payload.email = nextEmail;
  }
  if (edit.role !== original.role) {
    payload.role = edit.role;
  }
  const origProfile = (original.profile_name ?? "").trim();
  const nextProfile = edit.profile_name.trim();
  const origNames = (original.profile_names ?? (origProfile ? [origProfile] : []))
    .map((n) => n.trim())
    .filter(Boolean);
  const nextNames = edit.profile_names.map((n) => n.trim()).filter(Boolean);
  const namesChanged =
    nextNames.length !== origNames.length ||
    nextNames.some((n, i) => n !== origNames[i]);
  if (roleRequiresProfile(edit.role) && (nextProfile !== origProfile || namesChanged)) {
    payload.profile_name = nextProfile || nextNames[0] || null;
    payload.profile_names = nextNames;
  }
  if (!roleRequiresProfile(edit.role) && roleRequiresProfile(original.role)) {
    payload.profile_name = null;
    payload.profile_names = [];
  }
  const norm = (value: string | null | undefined) => (value ?? "").trim() || null;
  if (norm(edit.display_name) !== norm(original.display_name)) {
    payload.display_name = norm(edit.display_name);
  }
  if (norm(edit.department) !== norm(original.department)) {
    payload.department = norm(edit.department);
  }
  if (norm(edit.position) !== norm(original.position)) {
    payload.position = norm(edit.position);
  }
  if (edit.enabled !== (original.enabled ?? true)) {
    payload.enabled = edit.enabled;
  }
  if (roleRequiresProfile(edit.role)) {
    const origPaths = (original.workspaces ?? []).map((ws) => ws.path.trim()).filter(Boolean);
    const nextPaths = edit.workspace_paths.map((p) => p.trim()).filter(Boolean);
    const pathsChanged =
      nextPaths.length !== origPaths.length ||
      nextPaths.some((p, i) => p !== origPaths[i]);
    if (pathsChanged) {
      payload.workspace_paths = nextPaths;
    }
  }
  return payload;
}

/** GET /api/v1/admin/workspaces */
export async function listAdminWorkspaces(): Promise<{ workspaces: AdminWorkspaceEntry[] }> {
  return fetchJson<{ workspaces: AdminWorkspaceEntry[] }>("/admin/workspaces");
}

/** POST /api/v1/admin/workspaces */
export async function createAdminWorkspace(
  name: string,
): Promise<{ workspaces: AdminWorkspaceEntry[] }> {
  return fetchJson<{ workspaces: AdminWorkspaceEntry[] }>("/admin/workspaces", {
    method: "POST",
    body: { name },
  });
}

/** PATCH /api/v1/admin/workspaces — rename folder */
export async function renameAdminWorkspace(
  path: string,
  name: string,
): Promise<{ workspaces: AdminWorkspaceEntry[] }> {
  return fetchJson<{ workspaces: AdminWorkspaceEntry[] }>("/admin/workspaces", {
    method: "PATCH",
    body: { path, name },
  });
}

/** DELETE /api/v1/admin/workspaces — remove folder */
export async function deleteAdminWorkspace(
  path: string,
): Promise<{ workspaces: AdminWorkspaceEntry[] }> {
  return fetchJson<{ workspaces: AdminWorkspaceEntry[] }>("/admin/workspaces", {
    method: "DELETE",
    body: { path },
  });
}

/** GET /api/v1/admin/profiles — all assignable profile ids (admin only). */
export async function listAssignableProfiles(): Promise<{ profiles: string[] }> {
  return fetchJson<{ profiles: string[] }>("/admin/profiles");
}

/** GET /api/v1/admin/users */
export async function listUsers(): Promise<UserListResponse> {
  return fetchJson<UserListResponse>("/admin/users");
}

/** GET /api/v1/admin/users/{email} */
export async function getUser(email: string): Promise<UserDetailResponse> {
  return fetchJson<UserDetailResponse>(`/admin/users/${encodeURIComponent(email)}`);
}

/** POST /api/v1/admin/users */
export async function createUser(payload: CreateUserPayload): Promise<UserMutationResponse> {
  return fetchJson<UserMutationResponse>("/admin/users", {
    method: "POST",
    body: payload,
  });
}

/** PATCH /api/v1/admin/users/{email} */
export async function updateUser(
  email: string,
  payload: UpdateUserPayload,
): Promise<UserMutationResponse> {
  return fetchJson<UserMutationResponse>(`/admin/users/${encodeURIComponent(email)}`, {
    method: "PATCH",
    body: payload,
  });
}

/** DELETE /api/v1/admin/users/{email} */
export async function deleteUser(email: string): Promise<void> {
  await fetchJson<unknown>(`/admin/users/${encodeURIComponent(email)}`, {
    method: "DELETE",
  });
}
