import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useToast } from "@/components/toast/ToastProvider";
import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  updateDepartment,
  type DepartmentSummary,
} from "./departmentsApi";
import { AuditMetaCards } from "./AuditMetaCards";

type PanelMode = "list" | "create" | "edit";

const inputClass =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm text-zinc-900 shadow-sm transition focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-900/80 dark:text-zinc-100";

function emptyForm() {
  return { label: "", description: "" };
}

export const DepartmentsPanel: React.FC = () => {
  const toast = useToast();
  const [mode, setMode] = useState<PanelMode>("list");
  const [departments, setDepartments] = useState<DepartmentSummary[]>([]);
  const [selected, setSelected] = useState<DepartmentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [createForm, setCreateForm] = useState(emptyForm);
  const [editForm, setEditForm] = useState({ id: "", label: "", description: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listDepartments();
      setDepartments(data.departments);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load departments");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(
    () => [...departments].sort((a, b) => a.label.localeCompare(b.label)),
    [departments],
  );

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const label = createForm.label.trim();
    if (!label) {
      toast.error("Label is required");
      return;
    }
    setActionPending(true);
    try {
      const result = await createDepartment({
        label,
        description: createForm.description.trim() || null,
      });
      toast.success(`Department created (${result.department.id})`);
      setCreateForm(emptyForm());
      setMode("list");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Create failed");
    } finally {
      setActionPending(false);
    }
  };

  const openEdit = (row: DepartmentSummary) => {
    setSelected(row);
    setEditForm({
      id: row.id,
      label: row.label,
      description: row.description ?? "",
    });
    setMode("edit");
  };

  const handleUpdate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setActionPending(true);
    try {
      await updateDepartment(selected.id, {
        label: editForm.label.trim() || selected.id,
        description: editForm.description.trim() || null,
      });
      toast.success("Department updated");
      setMode("list");
      setSelected(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setActionPending(false);
    }
  };

  const handleDelete = async (row: DepartmentSummary) => {
    if (!window.confirm(`Delete department "${row.label}"?`)) return;
    setActionPending(true);
    try {
      await deleteDepartment(row.id);
      toast.success("Department deleted");
      if (selected?.id === row.id) {
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

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-zinc-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading departments…
      </div>
    );
  }

  if (mode === "create") {
    return (
      <form onSubmit={handleCreate} className="mx-auto max-w-xl space-y-4">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">New department</h2>
        <p className="text-sm text-zinc-500">
          Department id is assigned automatically. You only need a display name.
        </p>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Label</span>
          <input
            className={inputClass}
            value={createForm.label}
            onChange={(e) => setCreateForm((p) => ({ ...p, label: e.target.value }))}
            placeholder="Human Resources"
            required
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Description</span>
          <input
            className={inputClass}
            value={createForm.description}
            onChange={(e) => setCreateForm((p) => ({ ...p, description: e.target.value }))}
          />
        </label>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Create
          </button>
          <button
            type="button"
            onClick={() => setMode("list")}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm dark:border-zinc-600"
          >
            Cancel
          </button>
        </div>
      </form>
    );
  }

  if (mode === "edit" && selected) {
    return (
      <form onSubmit={handleUpdate} className="mx-auto max-w-xl space-y-4">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          Edit {selected.label}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <AuditMetaCards
            created_at={selected.created_at}
            updated_at={selected.updated_at}
            created_by={selected.created_by}
            updated_by={selected.updated_by}
          />
        </div>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Id</span>
          <input className={inputClass} value={editForm.id} disabled />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Label</span>
          <input
            className={inputClass}
            value={editForm.label}
            onChange={(e) => setEditForm((p) => ({ ...p, label: e.target.value }))}
            required
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium">Description</span>
          <input
            className={inputClass}
            value={editForm.description}
            onChange={(e) => setEditForm((p) => ({ ...p, description: e.target.value }))}
          />
        </label>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={actionPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("list");
              setSelected(null);
            }}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm dark:border-zinc-600"
          >
            Cancel
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Departments</h2>
          <p className="text-sm text-zinc-500">
            Departments can be used to group users for access control.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setMode("create")}
            className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" />
            Add department
          </button>
        </div>
      </div>

      {sorted.length === 0 ? (
        <p className="text-sm text-zinc-500">No departments yet.</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-700">
          <table className="min-w-full divide-y divide-zinc-200 text-sm dark:divide-zinc-700">
            <thead className="bg-zinc-50 dark:bg-zinc-900/60">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Label</th>
                <th className="px-4 py-3 text-left font-medium">Id</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-700">
              {sorted.map((row) => (
                <tr key={row.id}>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 font-medium">
                      <Building2 className="h-4 w-4 text-zinc-400" />
                      {row.label}
                    </div>
                    {row.description ? (
                      <p className="mt-0.5 text-xs text-zinc-500">{row.description}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500">{row.id}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => openEdit(row)}
                      className="mr-2 text-indigo-600 hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(row)}
                      disabled={actionPending}
                      className="inline-flex items-center gap-1 text-red-600 hover:underline disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
