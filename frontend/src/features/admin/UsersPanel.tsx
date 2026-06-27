import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { notifyAuthRefresh } from "@/features/auth/authRefresh";
import {
  ArrowLeft,
  Briefcase,
  Building2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FolderOpen,
  Layers,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  Shield,
  Star,
  Trash2,
  User,
  Users,
} from "lucide-react";
import { toastMessage, useToast } from "@/components/toast/ToastProvider";
import {
  buildUserUpdatePatch,
  createUser,
  deleteUser,
  getUser,
  listAssignableProfiles,
  listUsers,
  updateUser,
  type UserDetail,
  type UserRole,
  type UserSummary,
  type UserWorkspaceEntry,
} from "./usersApi";
import { AuditMetaCards } from "./AuditMetaCards";
import { listRoles, type RoleSummary } from "./rolesApi";
import { listDepartments, type DepartmentSummary } from "./departmentsApi";

type PanelMode = "list" | "create" | "detail";

const EMAIL_RE = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;

const inputClass =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100";

function mergedWorkspaceChoices(
  available: UserWorkspaceEntry[],
  selectedPaths: string[],
): UserWorkspaceEntry[] {
  const byPath = new Map<string, UserWorkspaceEntry>();
  for (const row of available) {
    const path = row.path.trim();
    if (path) byPath.set(path, row);
  }
  for (const path of selectedPaths) {
    const token = path.trim();
    if (token && !byPath.has(token)) {
      byPath.set(token, { name: token.split("/").pop() || token, path: token });
    }
  }
  return [...byPath.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function mergedProfileChoices(options: string[], assigned: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const name of [...assigned, ...options]) {
    const token = name.trim();
    if (!token || token === "default" || seen.has(token)) continue;
    seen.add(token);
    out.push(token);
  }
  return out.sort((a, b) => a.localeCompare(b));
}

function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim().toLowerCase());
}

function profileSlugFromEmail(email: string): string {
  const local = email.trim().toLowerCase().split("@")[0] || "user";
  let slug = local.replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!slug) slug = "user";
  if (!/^[a-z]/.test(slug)) slug = `u${slug}`;
  return slug.slice(0, 64);
}

export const UsersPanel: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const [mode, setMode] = useState<PanelMode>("list");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [selected, setSelected] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);

  const [createForm, setCreateForm] = useState({
    email: "",
    display_name: "",
    department: "",
    position: "",
    password: "",
    role: "user" as UserRole,
    profile_name: "",
    extra_profiles: [] as string[],
  });

  const [editForm, setEditForm] = useState({
    email: "",
    role: "user" as UserRole,
    profile_name: "",
    profile_names: [] as string[],
    workspace_paths: [] as string[],
    display_name: "",
    department: "",
    position: "",
    enabled: true,
  });

  const [profileOptions, setProfileOptions] = useState<string[]>([]);
  const [roleOptions, setRoleOptions] = useState<RoleSummary[]>([]);
  const [departmentOptions, setDepartmentOptions] = useState<DepartmentSummary[]>([]);
  const [workspaceOptions, setWorkspaceOptions] = useState<UserWorkspaceEntry[]>([]);
  const [workspacesExpanded, setWorkspacesExpanded] = useState(false);

  const roleRequiresProfile = useCallback(
    (roleId: string) =>
      roleOptions.find((role) => role.id === roleId)?.requires_profile ?? roleId !== "admin",
    [roleOptions],
  );

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listUsers();
      setUsers(data.users ?? []);
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  const loadProfileOptions = useCallback(async () => {
    try {
      const data = await listAssignableProfiles();
      setProfileOptions(data.profiles ?? []);
    } catch {
      setProfileOptions([]);
    }
  }, []);

  const loadRoleOptions = useCallback(async () => {
    try {
      const data = await listRoles();
      setRoleOptions(data.roles ?? []);
    } catch {
      setRoleOptions([]);
    }
  }, []);

  const loadDepartmentOptions = useCallback(async () => {
    try {
      const data = await listDepartments();
      setDepartmentOptions(data.departments ?? []);
    } catch {
      setDepartmentOptions([]);
    }
  }, []);

  useEffect(() => {
    void loadUsers();
    void loadRoleOptions();
    void loadDepartmentOptions();
  }, [loadUsers, loadRoleOptions, loadDepartmentOptions]);

  useEffect(() => {
    if (mode === "create" || mode === "detail") {
      void loadProfileOptions();
    }
  }, [mode, loadProfileOptions]);

  const openDetail = async (email: string) => {
    setLoading(true);
    try {
      const detail = await getUser(email);
      setSelected(detail);
      const workspacePaths = (detail.workspaces?.length
        ? detail.workspaces
        : detail.workspace_path
          ? [{ name: "Workspace", path: detail.workspace_path }]
          : []
      ).map((ws) => ws.path.trim()).filter(Boolean);
      setWorkspaceOptions(
        detail.available_workspaces?.length
          ? detail.available_workspaces
          : detail.workspaces ?? [],
      );
      setWorkspacesExpanded(false);
      setEditForm({
        email: detail.email,
        role: detail.role,
        profile_name: detail.profile_name ?? detail.profile?.name ?? "",
        profile_names:
          detail.profile_names?.length
            ? detail.profile_names.filter((n) => n !== "default")
            : detail.profile_name && detail.profile_name !== "default"
              ? [detail.profile_name]
              : [],
        workspace_paths: workspacePaths,
        display_name: detail.display_name ?? "",
        department: detail.department ?? "",
        position: detail.position ?? "",
        enabled: detail.enabled ?? true,
      });
      setMode("detail");
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const email = createForm.email.trim().toLowerCase();
    if (!isValidEmail(email)) {
      toast.error("Invalid email address.");
      return;
    }
    if (!createForm.password) {
      toast.error("Password is required.");
      return;
    }
    let profile_name = createForm.profile_name.trim();
    if (roleRequiresProfile(createForm.role)) {
      profile_name = profile_name || profileSlugFromEmail(email);
    }
    const profile_names = roleRequiresProfile(createForm.role)
      ? [
          profile_name,
          ...createForm.extra_profiles.filter((n) => n && n !== profile_name),
        ]
      : [];
    setActionPending(true);
    try {
      await createUser({
        email,
        password: createForm.password,
        role: createForm.role,
        profile_name: roleRequiresProfile(createForm.role) ? profile_name : null,
        profile_names: roleRequiresProfile(createForm.role) ? profile_names : null,
        display_name: createForm.display_name.trim() || null,
        department: createForm.department.trim() || null,
        position: createForm.position.trim() || null,
      });
      setCreateForm({
        email: "",
        display_name: "",
        department: "",
        position: "",
        password: "",
        role: "user",
        profile_name: "",
        extra_profiles: [],
      });
      setMode("list");
      toast.success(`User ${email} created successfully.`);
      await loadUsers();
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleSaveDetail = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    const nextEmail = editForm.email.trim().toLowerCase();
    if (!isValidEmail(nextEmail)) {
      toast.error("Invalid email address.");
      return;
    }
    if (roleRequiresProfile(editForm.role) && editForm.profile_names.length === 0) {
      toast.error("Assign at least one profile for this role.");
      return;
    }
    setActionPending(true);
    try {
      const payload = buildUserUpdatePatch(selected, editForm, roleRequiresProfile);
      if (Object.keys(payload).length === 0) {
        toast.error("No changes to save.");
        return;
      }
      const updated = await updateUser(selected.email, payload);
      const refreshed = await getUser(updated.user.email);
      setSelected(refreshed);
      const nextPaths = (refreshed.workspaces ?? []).map((ws) => ws.path.trim()).filter(Boolean);
      setWorkspaceOptions(
        refreshed.available_workspaces?.length
          ? refreshed.available_workspaces
          : refreshed.workspaces ?? [],
      );
      setEditForm({
        email: refreshed.email,
        role: refreshed.role,
        profile_name: refreshed.profile_name ?? "",
        profile_names:
          refreshed.profile_names?.length
            ? [...refreshed.profile_names]
            : refreshed.profile_name
              ? [refreshed.profile_name]
              : [],
        workspace_paths: nextPaths,
        display_name: refreshed.display_name ?? "",
        department: refreshed.department ?? "",
        position: refreshed.position ?? "",
        enabled: refreshed.enabled ?? true,
      });
      toast.success("Changes saved successfully.");
      notifyAuthRefresh();
      await loadUsers();
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!window.confirm(`Remove ${selected.email}? This cannot be undone.`)) return;
    const removedEmail = selected.email;
    setActionPending(true);
    try {
      await deleteUser(removedEmail);
      setSelected(null);
      setMode("list");
      toast.success(`User ${removedEmail} removed.`);
      await loadUsers();
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setActionPending(false);
    }
  };

  const openProfileInSettings = (profileName: string) => {
    navigate("/settings/profiles", { state: { focusProfile: profileName } });
  };

  const syncCreateProfile = (email: string) => {
    const normalized = email.trim().toLowerCase();
    setCreateForm((prev) => {
      const current = prev.profile_name.trim();
      const prevSlug = profileSlugFromEmail(prev.email.trim().toLowerCase() || "");
      if (!current || current === prevSlug) {
        return {
          ...prev,
          email: normalized,
          profile_name: normalized.includes("@") ? profileSlugFromEmail(normalized) : "",
        };
      }
      return { ...prev, email: normalized };
    });
  };

  const detailTitle =
    editForm.display_name.trim() ||
    selected?.display_name?.trim() ||
    selected?.email ||
    "User";

  return (
    <div
      className={`space-y-6 ${mode === "detail" ? "mx-auto max-w-3xl" : "max-w-5xl"}`}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Manage Hermes accounts for multi-user deployments.
        </p>
        {mode === "list" && (
          <button
            type="button"
            onClick={() => setMode("create")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
          >
            <Plus className="h-4 w-4" />
            New user
          </button>
        )}
        <button
          type="button"
          onClick={() => void loadUsers()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh users"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {mode === "list" && (
        <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]">
          {loading && users.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading users…
            </div>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-zinc-500">
              <Users className="h-8 w-8 opacity-40" />
              No users yet. Create one to enable multi-user access.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/50">
                <tr>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Display name</th>
                  <th className="px-4 py-3 font-medium">Department</th>
                  <th className="px-4 py-3 font-medium">Position</th>
                  <th className="px-4 py-3 font-medium">Role</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr
                    key={user.email}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/80"
                  >
                    <td className="px-4 py-3 font-mono text-zinc-900 dark:text-zinc-100">
                      {user.email}
                    </td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                      {user.display_name || "—"}
                    </td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                      {user.department || "—"}
                    </td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                      {user.position || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800">
                        {user.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          user.enabled === false
                            ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
                            : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                        }`}
                      >
                        {user.enabled === false ? "Disabled" : "Active"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => void openDetail(user.email)}
                        className="text-xs font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {mode === "create" && (
        <form
          onSubmit={handleCreate}
          className="space-y-4 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-[#121212]"
        >
          <button
            type="button"
            onClick={() => setMode("list")}
            className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Email</span>
              <input
                type="email"
                value={createForm.email}
                onChange={(e) => syncCreateProfile(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                autoComplete="off"
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Display name</span>
              <input
                value={createForm.display_name}
                onChange={(e) =>
                  setCreateForm((p) => ({ ...p, display_name: e.target.value }))
                }
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                autoComplete="off"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Department</span>
              <select
                value={createForm.department}
                onChange={(e) => setCreateForm((p) => ({ ...p, department: e.target.value }))}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="">— none —</option>
                {departmentOptions.map((dept) => (
                  <option key={dept.id} value={dept.id}>
                    {dept.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Position</span>
              <input
                value={createForm.position}
                onChange={(e) => setCreateForm((p) => ({ ...p, position: e.target.value }))}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                autoComplete="organization-title"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Password</span>
              <input
                type="password"
                value={createForm.password}
                onChange={(e) => setCreateForm((p) => ({ ...p, password: e.target.value }))}
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                autoComplete="new-password"
                required
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Role</span>
              <select
                value={createForm.role}
                onChange={(e) =>
                  setCreateForm((p) => ({ ...p, role: e.target.value as UserRole }))
                }
                className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                {roleOptions.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.label} ({role.id})
                  </option>
                ))}
              </select>
            </label>
            {roleRequiresProfile(createForm.role) && (
              <>
                <label className="block space-y-1.5 sm:col-span-2">
                  <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                    Default profile
                  </span>
                  <input
                    value={createForm.profile_name}
                    onChange={(e) =>
                      setCreateForm((p) => ({ ...p, profile_name: e.target.value }))
                    }
                    placeholder="defaults to email local-part"
                    className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                  />
                  <p className="text-xs text-zinc-500">
                    Hermes profile and workspace are created automatically for the default
                    profile.
                  </p>
                </label>
                <label className="block space-y-1.5 sm:col-span-2">
                  <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                    Additional profiles (optional)
                  </span>
                  <select
                    multiple
                    value={createForm.extra_profiles}
                    onChange={(e) => {
                      const picked = Array.from(e.target.selectedOptions).map(
                        (o) => o.value,
                      );
                      setCreateForm((p) => ({ ...p, extra_profiles: picked }));
                    }}
                    className="min-h-[6rem] w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                  >
                    {profileOptions
                      .filter((name) => name !== createForm.profile_name.trim())
                      .map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                  </select>
                  <p className="text-xs text-zinc-500">
                    Hold Ctrl/Cmd to select more than one. Extra profiles share this
                    account&apos;s workspace; only agent config is added per profile.
                  </p>
                </label>
              </>
            )}
          </div>
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
          >
            {actionPending ? "Creating…" : "Create user"}
          </button>
        </form>
      )}

      {mode === "detail" && selected && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <button
                type="button"
                onClick={() => {
                  setSelected(null);
                  setMode("list");
                }}
                className="mt-0.5 inline-flex items-center justify-center rounded-lg border border-zinc-200 p-2 text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
                aria-label="Back to user list"
              >
                <ArrowLeft className="h-4 w-4" />
              </button>
              <div className="min-w-0">
                <h2 className="truncate text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                  {detailTitle}
                </h2>
                <p className="truncate font-mono text-sm text-zinc-500">{selected.email}</p>
                <span
                  className={`mt-2 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    !roleRequiresProfile(editForm.role)
                      ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                      : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                  }`}
                >
                  <Shield className="h-3 w-3" />
                  {editForm.role}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={actionPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/40 px-3 py-2 text-sm font-medium text-rose-600 hover:bg-rose-500/10 dark:text-rose-400"
            >
              <Trash2 className="h-4 w-4" />
              Delete account
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <AuditMetaCards
              created_at={selected.created_at}
              updated_at={selected.updated_at}
              created_by={selected.created_by}
              updated_by={selected.updated_by}
            />
            {selected.session_summary && (
              <div className="rounded-xl border border-zinc-200 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/50">
                <div className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                  Sessions
                </div>
                <div className="mt-1 text-sm tabular-nums text-zinc-900 dark:text-zinc-100">
                  {selected.session_summary.total}
                  <span className="ml-1 text-xs text-zinc-500">
                    ({selected.session_summary.active} active)
                  </span>
                </div>
              </div>
            )}
            {roleRequiresProfile(editForm.role) && selected.workspace_path && (
              <div className="rounded-xl border border-indigo-500/25 bg-indigo-500/5 px-4 py-3 sm:col-span-1">
                <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-indigo-600 dark:text-indigo-400">
                  <FolderOpen className="h-3.5 w-3.5" />
                  Workspace
                </div>
                <div
                  className="mt-1 break-all font-mono text-xs text-zinc-800 dark:text-zinc-200"
                  title={selected.workspace_path}
                >
                  {selected.workspace_path}
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleSaveDetail} className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-2">
              <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]">
                <div className="border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
                  <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    <User className="h-4 w-4 text-zinc-500" />
                    Account
                  </div>
                  <p className="mt-1 text-xs text-zinc-500">
                    Login identity and organization fields.
                  </p>
                </div>
                <div className="space-y-4 p-5">
                  <label className="block space-y-1.5">
                    <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      <Mail className="h-3.5 w-3.5" />
                      Email
                    </span>
                    <input
                      type="email"
                      value={editForm.email}
                      onChange={(e) =>
                        setEditForm((p) => ({
                          ...p,
                          email: e.target.value.trim().toLowerCase(),
                        }))
                      }
                      className={`${inputClass} font-mono`}
                      autoComplete="off"
                      required
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      Display name
                    </span>
                    <input
                      value={editForm.display_name}
                      onChange={(e) =>
                        setEditForm((p) => ({ ...p, display_name: e.target.value }))
                      }
                      className={inputClass}
                    />
                  </label>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="block space-y-1.5">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        <Building2 className="h-3.5 w-3.5" />
                        Department
                      </span>
                      <select
                        value={editForm.department}
                        onChange={(e) =>
                          setEditForm((p) => ({ ...p, department: e.target.value }))
                        }
                        className={inputClass}
                      >
                        <option value="">— none —</option>
                        {departmentOptions.map((dept) => (
                          <option key={dept.id} value={dept.id}>
                            {dept.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block space-y-1.5">
                      <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        <Briefcase className="h-3.5 w-3.5" />
                        Position
                      </span>
                      <input
                        value={editForm.position}
                        onChange={(e) =>
                          setEditForm((p) => ({ ...p, position: e.target.value }))
                        }
                        className={inputClass}
                      />
                    </label>
                  </div>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                      Role
                    </span>
                    <select
                      value={editForm.role}
                      onChange={(e) =>
                        setEditForm((p) => ({ ...p, role: e.target.value as UserRole }))
                      }
                      className={inputClass}
                    >
                      {roleOptions.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.label} ({role.id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 px-3 py-2.5 dark:border-zinc-700">
                    <div>
                      <div className="text-xs font-medium text-zinc-700 dark:text-zinc-300">
                        Account active
                      </div>
                      <div className="text-xs text-zinc-500">
                        Disabled users cannot sign in.
                      </div>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={editForm.enabled}
                      onClick={() =>
                        setEditForm((p) => ({ ...p, enabled: !p.enabled }))
                      }
                      className={`relative h-6 w-11 shrink-0 rounded-full transition ${
                        editForm.enabled ? "bg-indigo-600" : "bg-zinc-300 dark:bg-zinc-600"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${
                          editForm.enabled ? "left-5" : "left-0.5"
                        }`}
                      />
                    </button>
                  </label>
                </div>
              </section>

              {roleRequiresProfile(editForm.role) ? (
                <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]">
                  <div className="border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
                    <div className="flex items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                      <Layers className="h-4 w-4 text-zinc-500" />
                      Agent access
                    </div>
                    <p className="mt-1 text-xs text-zinc-500">
                      File workspaces belong to this user account. Every assigned profile
                      can open any workspace listed here; profiles only change agent/model
                      config.
                    </p>
                  </div>
                  <div className="space-y-4 p-5">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setWorkspacesExpanded((open) => !open)}
                          className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                        >
                          {workspacesExpanded ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                          )}
                          File workspaces
                          <span className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-normal text-zinc-500 dark:bg-zinc-800">
                            {editForm.workspace_paths.length} selected
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={() => navigate("/settings/workspaces")}
                          className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                        >
                          Manage folders
                          <ExternalLink className="h-3 w-3" />
                        </button>
                      </div>
                      {workspacesExpanded ? (
                        <ul className="max-h-48 space-y-2 overflow-y-auto rounded-lg border border-zinc-200 p-2 dark:border-zinc-700">
                          {mergedWorkspaceChoices(
                            workspaceOptions,
                            editForm.workspace_paths,
                          ).map((ws) => {
                            const checked = editForm.workspace_paths.includes(ws.path);
                            const isRoot = ws.path === "/workspace";
                            return (
                              <li
                                key={ws.path}
                                className={`rounded-lg border px-3 py-2 transition ${
                                  checked
                                    ? "border-indigo-500/40 bg-indigo-500/5 dark:border-indigo-500/30"
                                    : "border-zinc-200 dark:border-zinc-700"
                                }`}
                              >
                                <label className="flex cursor-pointer items-start gap-2">
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    disabled={isRoot}
                                    className="mt-0.5 rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-60"
                                    onChange={(e) => {
                                      setEditForm((p) => {
                                        const set = new Set(p.workspace_paths);
                                        if (e.target.checked) set.add(ws.path);
                                        else set.delete(ws.path);
                                        if (!set.has("/workspace")) set.add("/workspace");
                                        return { ...p, workspace_paths: [...set] };
                                      });
                                    }}
                                  />
                                  <span className="min-w-0 flex-1">
                                    <span className="block text-sm font-medium">{ws.name}</span>
                                    <span className="block font-mono text-[10px] text-zinc-500">
                                      {ws.path}
                                    </span>
                                  </span>
                                </label>
                              </li>
                            );
                          })}
                        </ul>
                      ) : (
                        <p className="text-xs text-zinc-500">
                          Click to choose which workspace folders this account may use (shared
                          across all assigned profiles).
                        </p>
                      )}
                    </div>

                    <div className="space-y-2">
                      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                        Assigned profiles
                      </div>
                      <ul className="space-y-2">
                        {mergedProfileChoices(profileOptions, editForm.profile_names).map(
                          (name) => {
                            const checked = editForm.profile_names.includes(name);
                            const isPrimary = editForm.profile_name === name;
                            const onDisk = profileOptions.includes(name);
                            return (
                              <li
                                key={name}
                                className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2.5 transition ${
                                  checked
                                    ? "border-indigo-500/40 bg-indigo-500/5 dark:border-indigo-500/30"
                                    : "border-zinc-200 dark:border-zinc-700"
                                }`}
                              >
                                <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    className="rounded border-zinc-300 text-indigo-600 focus:ring-indigo-500"
                                    onChange={(e) => {
                                      setEditForm((p) => {
                                        const set = new Set(p.profile_names);
                                        if (e.target.checked) set.add(name);
                                        else set.delete(name);
                                        const next = [...set];
                                        const primary = next.includes(p.profile_name)
                                          ? p.profile_name
                                          : next[0] || "";
                                        return {
                                          ...p,
                                          profile_names: next,
                                          profile_name: primary,
                                        };
                                      });
                                    }}
                                  />
                                  <span className="font-mono text-sm">{name}</span>
                                  {!onDisk && checked ? (
                                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-700 dark:text-amber-300">
                                      new on save
                                    </span>
                                  ) : null}
                                </label>
                                {checked && (
                                  <button
                                    type="button"
                                    onClick={() => openProfileInSettings(name)}
                                    className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
                                  >
                                    View
                                  </button>
                                )}
                                {checked && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setEditForm((p) => ({ ...p, profile_name: name }))
                                    }
                                    className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition ${
                                      isPrimary
                                        ? "bg-indigo-600 text-white"
                                        : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                                    }`}
                                  >
                                    <Star
                                      className={`h-3 w-3 ${isPrimary ? "fill-current" : ""}`}
                                    />
                                    {isPrimary ? "Primary" : "Set primary"}
                                  </button>
                                )}
                              </li>
                            );
                          },
                        )}
                      </ul>
                    </div>

                  </div>
                </section>
              ) : (
                <section className="flex flex-col justify-center rounded-xl border border-dashed border-zinc-200 bg-zinc-50/50 px-5 py-8 text-center dark:border-zinc-700 dark:bg-zinc-900/30">
                  <Shield className="mx-auto h-8 w-8 text-amber-500/80" />
                  <p className="mt-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                    Administrator account
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">
                    Admins are not bound to a workspace or agent profiles.
                  </p>
                </section>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 bg-zinc-50/80 px-5 py-4 dark:border-zinc-800 dark:bg-zinc-900/40">
              <p className="text-xs text-zinc-500">
                Saving updates the account record
                {roleRequiresProfile(editForm.role) ? " and provisions any new profile ids." : "."}
              </p>
              <button
                type="submit"
                disabled={actionPending}
                className="inline-flex min-w-[9rem] items-center justify-center rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {actionPending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
