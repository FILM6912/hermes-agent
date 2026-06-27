import React, { useCallback, useEffect, useState } from "react";
import { FolderOpen, Loader2, Pencil, Plus, RefreshCw, Trash2, X, Check } from "lucide-react";
import { toastMessage, useToast } from "@/components/toast/ToastProvider";
import {
  createAdminWorkspace,
  deleteAdminWorkspace,
  listAdminWorkspaces,
  renameAdminWorkspace,
  type AdminWorkspaceEntry,
} from "./usersApi";

const inputClass =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100";

export const AdminWorkspacesPanel: React.FC = () => {
  const toast = useToast();
  const [rows, setRows] = useState<AdminWorkspaceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAdminWorkspaces();
      setRows(data.workspaces ?? []);
    } catch (err) {
      toast.error(toastMessage(err));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = folderName.trim();
    if (!name) {
      toast.error("Folder name is required.");
      return;
    }
    setPending(true);
    try {
      const data = await createAdminWorkspace(name);
      setRows(data.workspaces ?? []);
      setFolderName("");
      toast.success(`Workspace folder "${name}" created.`);
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setPending(false);
    }
  };

  const startEdit = (row: AdminWorkspaceEntry) => {
    setEditingPath(row.path);
    setEditName(row.name);
  };

  const cancelEdit = () => {
    setEditingPath(null);
    setEditName("");
  };

  const saveEdit = async (row: AdminWorkspaceEntry) => {
    const name = editName.trim();
    if (!name) {
      toast.error("Folder name is required.");
      return;
    }
    if (name === row.name) {
      cancelEdit();
      return;
    }
    setPending(true);
    try {
      const data = await renameAdminWorkspace(row.path, name);
      setRows(data.workspaces ?? []);
      cancelEdit();
      toast.success(`Renamed to "${name}".`);
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setPending(false);
    }
  };

  const handleDelete = async (row: AdminWorkspaceEntry) => {
    if (
      !window.confirm(
        `Delete workspace folder "${row.name}"?\n\nFiles under ${row.path} will be removed. User assignments referencing this folder will be cleared.`,
      )
    ) {
      return;
    }
    setPending(true);
    try {
      const data = await deleteAdminWorkspace(row.path);
      setRows(data.workspaces ?? []);
      if (editingPath === row.path) cancelEdit();
      toast.success(`Deleted "${row.name}".`);
    } catch (err) {
      toast.error(toastMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          Workspace folders
        </h2>
        <p className="mt-1 text-sm text-zinc-500">
          Create, rename, or delete top-level folders under the shared workspace mount.
          Assign them to users from Users → View → File workspaces.
        </p>
      </div>

      <form
        onSubmit={handleCreate}
        className="flex flex-wrap items-end gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]"
      >
        <div className="min-w-[12rem] flex-1">
          <label className="mb-1 block text-xs font-medium text-zinc-500">
            New folder name
          </label>
          <input
            className={inputClass}
            value={folderName}
            onChange={(e) => setFolderName(e.target.value)}
            placeholder="e.g. project-alpha"
            disabled={pending}
          />
        </div>
        <button
          type="submit"
          disabled={pending}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {pending && !editingPath ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          Add
        </button>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2.5 text-sm text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </form>

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]">
        {loading && rows.length === 0 ? (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-sm text-zinc-500">
            <FolderOpen className="h-8 w-8 opacity-40" />
            No workspace folders yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/50">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Path</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isEditing = editingPath === row.path;
                return (
                  <tr
                    key={row.path}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/80"
                  >
                    <td className="px-4 py-3">
                      {isEditing ? (
                        <input
                          className={inputClass}
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          disabled={pending}
                          autoFocus
                        />
                      ) : (
                        <span className="font-medium text-zinc-900 dark:text-zinc-100">
                          {row.name}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-zinc-500">{row.path}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {isEditing ? (
                          <>
                            <button
                              type="button"
                              title="Save"
                              disabled={pending}
                              onClick={() => void saveEdit(row)}
                              className="rounded-md p-1.5 text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-50"
                            >
                              <Check className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              title="Cancel"
                              disabled={pending}
                              onClick={cancelEdit}
                              className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              title="Rename"
                              disabled={pending}
                              onClick={() => startEdit(row)}
                              className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-indigo-600 dark:hover:bg-zinc-800 dark:hover:text-indigo-400"
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                            <button
                              type="button"
                              title="Delete"
                              disabled={pending}
                              onClick={() => void handleDelete(row)}
                              className="rounded-md p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
