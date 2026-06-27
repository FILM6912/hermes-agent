import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, RefreshCw, Shield, Trash2 } from "lucide-react";
import { notifyAuthRefresh } from "@/features/auth/authRefresh";
import { useToast } from "@/components/toast/ToastProvider";
import {
  createRole,
  deleteRole,
  emptyPermissions,
  enabledPermissionIds,
  hasAnyPermission,
  listRoles,
  permissionsForEdit,
  buildRoleUpdatePatch,
  togglePermissionMap,
  updateRole,
  type PermissionCatalogEntry,
  type RolePermissions,
  type RoleSummary,
} from "./rolesApi";
import { AuditMetaCards } from "./AuditMetaCards";

type PanelMode = "list" | "create" | "edit";

const inputClass =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100";

type CreateRoleForm = {
  label: string;
  description: string;
  permissions: RolePermissions;
  requires_profile: boolean;
};

type EditRoleForm = CreateRoleForm & { id: string };

function emptyCreateForm(catalog: PermissionCatalogEntry[] = []): CreateRoleForm {
  return {
    label: "",
    description: "",
    permissions: emptyPermissions(catalog),
    requires_profile: true,
  };
}

function emptyEditForm(catalog: PermissionCatalogEntry[] = []): EditRoleForm {
  return { id: "", ...emptyCreateForm(catalog) };
}

export const RolesPanel: React.FC = () => {
  const toast = useToast();
  const [mode, setMode] = useState<PanelMode>("list");
  const [roles, setRoles] = useState<RoleSummary[]>([]);
  const [catalog, setCatalog] = useState<PermissionCatalogEntry[]>([]);
  const [selected, setSelected] = useState<RoleSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [createForm, setCreateForm] = useState(() => emptyCreateForm());
  const [editForm, setEditForm] = useState(() => emptyEditForm());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listRoles();
      setRoles(data.roles);
      setCatalog(data.permissions);
      setCreateForm((prev) => ({
        ...prev,
        permissions:
          Object.keys(prev.permissions).length > 0
            ? prev.permissions
            : emptyPermissions(data.permissions),
      }));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load roles");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedRoles = useMemo(
    () => [...roles].sort((a, b) => a.label.localeCompare(b.label)),
    [roles],
  );

  const togglePermission = (
    current: RolePermissions,
    permission: string,
    checked: boolean,
  ): RolePermissions => togglePermissionMap(current, permission, checked, catalog);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!createForm.label.trim()) {
      toast.error("Label is required");
      return;
    }
    if (!hasAnyPermission(createForm.permissions)) {
      toast.error("Select at least one permission");
      return;
    }
    setActionPending(true);
    try {
      const result = await createRole({
        label: createForm.label.trim(),
        description: createForm.description.trim() || null,
        permissions: createForm.permissions,
        requires_profile: createForm.requires_profile,
      });
      toast.success(`Created role ${result.role.id}`);
      setCreateForm(emptyCreateForm(catalog));
      setMode("list");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Create failed");
    } finally {
      setActionPending(false);
    }
  };

  const openEdit = (role: RoleSummary) => {
    setSelected(role);
    setEditForm({
      id: role.id,
      label: role.label,
      description: role.description ?? "",
      permissions: permissionsForEdit(role.permissions, catalog),
      requires_profile: role.requires_profile,
    });
    setMode("edit");
  };

  const handleUpdate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    if (!editForm.label.trim()) {
      toast.error("Label is required");
      return;
    }
    if (!hasAnyPermission(editForm.permissions)) {
      toast.error("Select at least one permission");
      return;
    }
    setActionPending(true);
    try {
      const patch = buildRoleUpdatePatch(selected, editForm, catalog);
      if (Object.keys(patch).length === 0) {
        toast.error("No changes to save");
        return;
      }
      await updateRole(selected.id, patch);
      toast.success(`Updated role ${selected.id}`);
      notifyAuthRefresh();
      setMode("list");
      setSelected(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async (role: RoleSummary) => {
    if (role.builtin) {
      toast.error("Built-in roles cannot be deleted");
      return;
    }
    if (!window.confirm(`Delete role "${role.label}" (${role.id})?`)) return;
    setActionPending(true);
    try {
      await deleteRole(role.id);
      toast.success(`Deleted role ${role.id}`);
      if (selected?.id === role.id) {
        setSelected(null);
        setMode("list");
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setActionPending(false);
    }
  };

  const renderPermissionPicker = (
    permissions: RolePermissions,
    onChange: (next: RolePermissions) => void,
    disabled?: boolean,
  ) => {
    const general = catalog.filter((entry) => !entry.id.startsWith("rag:"));
    const rag = catalog.filter((entry) => entry.id.startsWith("rag:"));

    const renderEntries = (entries: PermissionCatalogEntry[]) =>
      entries.map((entry) => (
        <label
          key={entry.id}
          className="flex items-start gap-2 rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-700"
        >
          <input
            type="checkbox"
            className="mt-0.5"
            checked={Boolean(permissions["*"]) || Boolean(permissions[entry.id])}
            disabled={disabled || (Boolean(permissions["*"]) && entry.id !== "*")}
            onChange={(e) => onChange(togglePermission(permissions, entry.id, e.target.checked))}
          />
          <span>
            <span className="font-medium">{entry.label}</span>
            <span className="mt-0.5 block font-mono text-xs text-zinc-500">{entry.id}</span>
          </span>
        </label>
      ));

    return (
      <div className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="flex items-start gap-2 rounded-lg border border-indigo-200 bg-indigo-50/60 p-3 text-sm dark:border-indigo-900/50 dark:bg-indigo-950/20 sm:col-span-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={Boolean(permissions["*"])}
              disabled={disabled}
              onChange={(e) => onChange(togglePermission(permissions, "*", e.target.checked))}
            />
            <span>
              <span className="font-medium">* Full access</span>
              <span className="mt-0.5 block text-xs text-zinc-500">Grants every permission</span>
            </span>
          </label>
          {renderEntries(general)}
        </div>
        {rag.length > 0 ? (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
              RAG / Document knowledge base
            </h3>
            <div className="grid gap-2 sm:grid-cols-2">{renderEntries(rag)}</div>
          </div>
        ) : null}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-zinc-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading roles…
      </div>
    );
  }

  if (mode === "create") {
    return (
      <div className="max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Create role</h2>
          <button
            type="button"
            onClick={() => setMode("list")}
            className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            Back
          </button>
        </div>
        <form onSubmit={handleCreate} className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <p className="text-sm text-zinc-500">
            Role id is assigned automatically. You only need a display name and permissions.
          </p>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Label</span>
            <input
              value={createForm.label}
              onChange={(e) => setCreateForm((p) => ({ ...p, label: e.target.value }))}
              placeholder="หัวหน้า"
              className={inputClass}
              required
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Description</span>
            <input
              value={createForm.description}
              onChange={(e) => setCreateForm((p) => ({ ...p, description: e.target.value }))}
              className={inputClass}
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={createForm.requires_profile}
              onChange={(e) =>
                setCreateForm((p) => ({ ...p, requires_profile: e.target.checked }))
              }
            />
            Requires profile binding
          </label>
          <div className="space-y-2">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Permissions</span>
            {renderPermissionPicker(createForm.permissions, (next) =>
              setCreateForm((p) => ({ ...p, permissions: next })),
            )}
          </div>
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
          >
            {actionPending ? "Creating…" : "Create role"}
          </button>
        </form>
      </div>
    );
  }

  if (mode === "edit" && selected) {
    return (
      <div className="max-w-3xl space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            Edit role: {selected.id}
          </h2>
          <button
            type="button"
            onClick={() => {
              setMode("list");
              setSelected(null);
            }}
            className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            Back
          </button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <AuditMetaCards
            created_at={selected.created_at}
            updated_at={selected.updated_at}
            created_by={selected.created_by}
            updated_by={selected.updated_by}
          />
        </div>
        <form onSubmit={handleUpdate} className="space-y-4 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950">
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Label</span>
            <input
              value={editForm.label}
              onChange={(e) => setEditForm((p) => ({ ...p, label: e.target.value }))}
              className={inputClass}
              required
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Description</span>
            <input
              value={editForm.description}
              onChange={(e) => setEditForm((p) => ({ ...p, description: e.target.value }))}
              className={inputClass}
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={editForm.requires_profile}
              onChange={(e) =>
                setEditForm((p) => ({ ...p, requires_profile: e.target.checked }))
              }
            />
            Requires profile binding
          </label>
          <div className="space-y-2">
            <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">Permissions</span>
            {renderPermissionPicker(editForm.permissions, (next) =>
              setEditForm((p) => ({ ...p, permissions: next })),
            )}
          </div>
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
          >
            {actionPending ? "Saving…" : "Save role"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Roles</h2>
          <p className="text-sm text-zinc-500">
            Define permissions per role as JSON-backed records in roles.json
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => {
              setCreateForm(emptyCreateForm(catalog));
              setMode("create");
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-500"
          >
            <Plus className="h-4 w-4" />
            Add role
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
        <table className="min-w-full divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
          <thead className="bg-zinc-50 dark:bg-zinc-900/60">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-zinc-600 dark:text-zinc-400">Role</th>
              <th className="px-4 py-3 text-left font-medium text-zinc-600 dark:text-zinc-400">Permissions</th>
              <th className="px-4 py-3 text-left font-medium text-zinc-600 dark:text-zinc-400">Profile</th>
              <th className="px-4 py-3 text-right font-medium text-zinc-600 dark:text-zinc-400">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200 bg-white dark:divide-zinc-800 dark:bg-zinc-950">
            {sortedRoles.map((role) => (
              <tr key={role.id}>
                <td className="px-4 py-3 align-top">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4 text-indigo-500" />
                    <div>
                      <div className="font-medium text-zinc-900 dark:text-zinc-100">{role.label}</div>
                      <div className="font-mono text-xs text-zinc-500">{role.id}</div>
                      {role.description ? (
                        <div className="mt-1 text-xs text-zinc-500">{role.description}</div>
                      ) : null}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 align-top">
                  <div className="flex flex-wrap gap-1">
                    {enabledPermissionIds(role.permissions).map((perm) => (
                      <span
                        key={perm}
                        className="rounded-full bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
                      >
                        {perm}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 align-top text-zinc-600 dark:text-zinc-400">
                  {role.requires_profile ? "Required" : "None"}
                </td>
                <td className="px-4 py-3 align-top">
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => openEdit(role)}
                      className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs dark:border-zinc-700"
                    >
                      Edit
                    </button>
                    {!role.builtin ? (
                      <button
                        type="button"
                        onClick={() => void handleDelete(role)}
                        disabled={actionPending}
                        className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-3 py-1.5 text-xs text-red-600 dark:border-red-900/40 dark:text-red-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
