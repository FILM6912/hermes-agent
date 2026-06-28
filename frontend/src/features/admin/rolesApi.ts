import { fetchJson } from "@/lib/api";

export type PermissionCatalogEntry = {
  id: string;
  label: string;
};

export type RolePermissions = Record<string, boolean>;

export type RoleSummary = {
  id: string;
  label: string;
  description?: string | null;
  permissions: RolePermissions;
  requires_profile: boolean;
  builtin?: boolean;
  created_at?: number | null;
  updated_at?: number | null;
  created_by?: string | null;
  updated_by?: string | null;
};

export type RoleListResponse = {
  roles: RoleSummary[];
  permissions: PermissionCatalogEntry[];
};

export type CreateRolePayload = {
  id?: string;
  label: string;
  description?: string | null;
  permissions: RolePermissions;
  requires_profile?: boolean;
};

export type UpdateRolePayload = {
  label?: string;
  description?: string | null;
  permissions?: RolePermissions;
  requires_profile?: boolean;
};

export type RoleMutationResponse = {
  ok?: boolean;
  role: RoleSummary;
};

export function emptyPermissions(catalog: PermissionCatalogEntry[]): RolePermissions {
  return Object.fromEntries(catalog.map((entry) => [entry.id, false]));
}

export function permissionsForEdit(
  permissions: RolePermissions | undefined,
  catalog: PermissionCatalogEntry[],
): RolePermissions {
  if (!permissions) return emptyPermissions(catalog);
  if (permissions["*"]) {
    return Object.fromEntries(catalog.map((entry) => [entry.id, true]));
  }
  return normalizeRolePermissions(permissions, catalog);
}

export function isFullAccessPermissions(
  permissions: RolePermissions,
  catalog: PermissionCatalogEntry[],
): boolean {
  if (permissions["*"]) return true;
  return catalog.length > 0 && catalog.every((entry) => permissions[entry.id]);
}

export function diffRolePermissions(
  original: RolePermissions | undefined,
  next: RolePermissions,
  catalog: PermissionCatalogEntry[],
): RolePermissions | undefined {
  const orig = original ?? {};
  if (next["*"]) {
    return orig["*"] ? undefined : { "*": true };
  }
  const origExpanded = permissionsForEdit(orig, catalog);
  const patch: RolePermissions = {};
  for (const entry of catalog) {
    const before = Boolean(origExpanded[entry.id]);
    const after = Boolean(next[entry.id]);
    if (before !== after) patch[entry.id] = after;
  }
  return Object.keys(patch).length > 0 ? patch : undefined;
}

export function buildRoleUpdatePatch(
  original: RoleSummary,
  edit: {
    label: string;
    description: string;
    permissions: RolePermissions;
    requires_profile: boolean;
  },
  catalog: PermissionCatalogEntry[],
): UpdateRolePayload {
  const payload: UpdateRolePayload = {};
  const nextLabel = edit.label.trim();
  if (nextLabel !== original.label.trim()) payload.label = nextLabel;

  const nextDesc = edit.description.trim();
  const origDesc = (original.description ?? "").trim();
  if (nextDesc !== origDesc) payload.description = nextDesc || null;

  if (edit.requires_profile !== original.requires_profile) {
    payload.requires_profile = edit.requires_profile;
  }

  const permissions = diffRolePermissions(original.permissions, edit.permissions, catalog);
  if (permissions) payload.permissions = permissions;

  return payload;
}

export function normalizeRolePermissions(
  permissions: RolePermissions | undefined,
  catalog: PermissionCatalogEntry[],
): RolePermissions {
  if (!permissions) return emptyPermissions(catalog);
  if (permissions["*"]) return { "*": true };
  const out = emptyPermissions(catalog);
  for (const entry of catalog) {
    out[entry.id] = Boolean(permissions[entry.id]);
  }
  return out;
}

export function hasAnyPermission(permissions: RolePermissions | undefined): boolean {
  if (!permissions) return false;
  if (permissions["*"]) return true;
  return Object.values(permissions).some(Boolean);
}

export function enabledPermissionIds(permissions: RolePermissions | undefined): string[] {
  if (!permissions) return [];
  if (permissions["*"]) return ["*"];
  return Object.entries(permissions)
    .filter(([, enabled]) => enabled)
    .map(([id]) => id);
}

export function roleHasPermission(
  permissions: RolePermissions | undefined,
  permission: string,
): boolean {
  if (!permissions) return false;
  if (permissions["*"]) return true;
  return Boolean(permissions[permission]);
}

export function togglePermissionMap(
  current: RolePermissions,
  permission: string,
  checked: boolean,
  catalog: PermissionCatalogEntry[],
): RolePermissions {
  if (permission === "*") {
    return checked ? { "*": true } : emptyPermissions(catalog);
  }
  const next = normalizeRolePermissions(current, catalog);
  delete next["*"];
  next[permission] = checked;
  return next;
}

/** GET /api/v1/admin/roles */
export async function listRoles(): Promise<RoleListResponse> {
  return fetchJson<RoleListResponse>("/admin/roles");
}

/** POST /api/v1/admin/roles */
export async function createRole(payload: CreateRolePayload): Promise<RoleMutationResponse> {
  return fetchJson<RoleMutationResponse>("/admin/roles", {
    method: "POST",
    body: payload,
  });
}

/** PATCH /api/v1/admin/roles/{id} */
export async function updateRole(
  roleId: string,
  payload: UpdateRolePayload,
): Promise<RoleMutationResponse> {
  return fetchJson<RoleMutationResponse>(`/admin/roles/${encodeURIComponent(roleId)}`, {
    method: "PATCH",
    body: payload,
  });
}

/** DELETE /api/v1/admin/roles/{id} */
export async function deleteRole(roleId: string): Promise<void> {
  await fetchJson<unknown>(`/admin/roles/${encodeURIComponent(roleId)}`, {
    method: "DELETE",
  });
}
