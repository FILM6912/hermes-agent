import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Columns3,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useAuthBoot } from "@/features/auth/hooks/useAuthBoot";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useLanguage } from "@/hooks/useLanguage";
import { WorkspacePicker } from "@/features/chat/components/WorkspacePicker";
import { listWorkspaces, type HermesWorkspace } from "@/services/hermes/workspace";
import { KANBAN_COLUMNS } from "../types";
import { kanbanPriorityLabel, kanbanStatusLabel } from "../kanbanI18n";
import {
  formatKanbanDispatchResult,
  workspacePathForTenant,
  workspaceTenantSlug,
} from "../kanbanDispatch";
import { kanbanBlockedReason, kanbanEventSummary } from "../kanbanTaskUtils";
import { useKanbanBoard } from "../hooks/useKanbanBoard";
import {
  KanbanTaskFormFields,
  type KanbanTaskFormValues,
} from "./KanbanTaskFormFields";
import { KanbanAssigneeSelect } from "./KanbanAssigneeSelect";
import { KanbanPrioritySelect } from "./KanbanPrioritySelect";
import { KanbanWorkspaceSelect, KANBAN_CUSTOM_TENANT } from "./KanbanWorkspaceSelect";

const COLUMN_COLORS: Record<string, string> = {
  triage: "border-amber-500/30 bg-amber-500/5",
  todo: "border-zinc-500/30 bg-zinc-500/5",
  ready: "border-sky-500/30 bg-sky-500/5",
  running: "border-indigo-500/30 bg-indigo-500/5",
  blocked: "border-rose-500/30 bg-rose-500/5",
  done: "border-emerald-500/30 bg-emerald-500/5",
};

const EMPTY_CREATE_FORM: KanbanTaskFormValues = {
  title: "",
  body: "",
  status: "ready",
  assignee: "",
  workspacePath: "",
  tenant: "",
  priority: 0,
};

type DragState = {
  taskId: string;
  fromStatus: string;
};

interface KanbanPanelProps {
  onBack: () => void;
}

export const KanbanPanel: React.FC<KanbanPanelProps> = ({ onBack }) => {
  const { t } = useLanguage();
  const { status: authStatus } = useAuthBoot();
  const { profiles, activeProfile } = useActiveProfile();
  const {
    board,
    boards,
    activeBoard,
    tenantFilter,
    setTenantFilter,
    loading,
    error,
    selectedTask,
    setSelectedTask,
    selectedTaskEvents,
    loadBoard,
    selectBoard,
    openTask,
    createTask,
    updateTask,
    moveTask,
    archiveTask,
    blockTask,
    unblockTask,
    runDispatch,
  } = useKanbanBoard();

  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaces, setWorkspaces] = useState<HermesWorkspace[]>([]);
  const [detailWorkspacePath, setDetailWorkspacePath] = useState("");
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);
  const workspaceMenuRef = useRef<HTMLDivElement>(null);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchNotice, setDispatchNotice] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState<KanbanTaskFormValues>(EMPTY_CREATE_FORM);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [readyUnassignedWarned, setReadyUnassignedWarned] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [dropStatus, setDropStatus] = useState<string | null>(null);

  const historicalAssignees = board?.assignees ?? [];
  const tenantOptions = board?.tenants ?? [];

  const workspaceBooted = useRef(false);

  useEffect(() => {
    let cancelled = false;
    void listWorkspaces()
      .then((data) => {
        if (cancelled) return;
        setWorkspaces(data.workspaces);
        if (workspaceBooted.current) return;
        const initial =
          data.last?.trim() ||
          data.workspaces[0]?.path?.trim() ||
          "";
        if (!initial) return;
        workspaceBooted.current = true;
        setWorkspacePath(initial);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedTask) {
      setDetailWorkspacePath("");
      return;
    }
    const matched = workspacePathForTenant(workspaces, selectedTask.tenant);
    setDetailWorkspacePath(
      matched || (selectedTask.tenant?.trim() ? KANBAN_CUSTOM_TENANT : ""),
    );
  }, [selectedTask, workspaces]);

  const defaultAssignee = useCallback((): string => {
    const bound = authStatus?.profile_name?.trim();
    if (bound && profiles.some((p) => p.name === bound)) return bound;
    if (activeProfile && profiles.some((p) => p.name === activeProfile)) {
      return activeProfile;
    }
    return profiles[0]?.name ?? bound ?? "";
  }, [activeProfile, authStatus?.profile_name, profiles]);

  const defaultTenant = useCallback((): string => {
    if (!workspacePath) return "";
    const match = workspaces.find((w) => w.path === workspacePath);
    return workspaceTenantSlug(workspacePath, match?.name);
  }, [workspacePath, workspaces]);

  const handleWorkspaceChange = async (path: string, _name: string) => {
    setWorkspacePath(path);
    setWorkspaceMenuOpen(false);
  };

  const handleDeleteTask = async () => {
    if (!selectedTask) return;
    if (!window.confirm(t("kanban.deleteTaskConfirm"))) return;
    try {
      await archiveTask(selectedTask.id);
    } catch (err) {
      setDispatchNotice(
        err instanceof Error ? err.message : t("kanban.deleteTaskFailed"),
      );
    }
  };

  const handleDetailStatusChange = (status: string) => {
    if (!selectedTask) return;
    if (status === "blocked") {
      const reason = window.prompt(t("kanban.blockPrompt"), "");
      if (reason === null) return;
      void blockTask(selectedTask.id, reason.trim() || t("kanban.blockDefaultReason"));
      return;
    }
    setSelectedTask({ ...selectedTask, status });
    void moveTask(selectedTask.id, status);
  };

  const handleRunDispatch = async () => {
    if (dispatching) return;
    if (!window.confirm(t("kanban.dispatchConfirm"))) return;
    setDispatching(true);
    setDispatchNotice(null);
    try {
      const result = await runDispatch();
      setDispatchNotice(formatKanbanDispatchResult(result, t));
    } catch (err) {
      setDispatchNotice(
        err instanceof Error ? err.message : t("kanban.dispatchFailed"),
      );
    } finally {
      setDispatching(false);
    }
  };

  const openCreateModal = () => {
    const tenant = defaultTenant();
    setCreateForm({
      ...EMPTY_CREATE_FORM,
      assignee: defaultAssignee(),
      workspacePath: workspacePath || workspacePathForTenant(workspaces, tenant),
      tenant,
    });
    setCreateError(null);
    setReadyUnassignedWarned(false);
    setShowCreate(true);
  };

  const patchCreateForm = (patch: Partial<KanbanTaskFormValues>) => {
    setCreateForm((prev) => ({ ...prev, ...patch }));
    if ("status" in patch || "assignee" in patch) {
      setReadyUnassignedWarned(false);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const title = createForm.title.trim();
    if (!title) {
      setCreateError(t("kanban.titleRequired"));
      return;
    }

    if (
      createForm.status === "ready" &&
      !createForm.assignee.trim() &&
      !readyUnassignedWarned
    ) {
      setCreateError(t("kanban.readyNeedsAssignee"));
      setReadyUnassignedWarned(true);
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      await createTask({
        title,
        body: createForm.body.trim() || undefined,
        status: createForm.status,
        assignee: createForm.assignee.trim() || undefined,
        tenant: createForm.tenant.trim() || undefined,
        priority: createForm.priority || undefined,
      });
      setCreateForm(EMPTY_CREATE_FORM);
      setShowCreate(false);
      setReadyUnassignedWarned(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : t("kanban.createFailed"));
    } finally {
      setCreating(false);
    }
  };

  const handleSaveTask = async () => {
    if (!selectedTask) return;
    setSaving(true);
    try {
      await updateTask(selectedTask.id, {
        title: selectedTask.title,
        body: selectedTask.body ?? "",
        assignee: selectedTask.assignee ?? "",
        tenant: selectedTask.tenant ?? "",
        priority: selectedTask.priority ?? 0,
        status: selectedTask.status,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTaskDragStart = (taskId: string, fromStatus: string) => {
    setDragState({ taskId, fromStatus });
  };

  const handleTaskDragEnd = () => {
    setDragState(null);
    setDropStatus(null);
  };

  const handleColumnDrop = async (targetStatus: string) => {
    if (!dragState) return;
    setDropStatus(null);
    if (dragState.fromStatus === targetStatus) {
      setDragState(null);
      return;
    }
    try {
      await moveTask(dragState.taskId, targetStatus);
    } finally {
      setDragState(null);
    }
  };

  const columns = board?.columns ?? KANBAN_COLUMNS.map((name) => ({ name, tasks: [] }));
  const selectedBlockedReason = kanbanBlockedReason(selectedTask, selectedTaskEvents);

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label={t("kanban.backToChat")}
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <Columns3 className="h-5 w-5 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">{t("kanban.title")}</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            {t("kanban.subtitle")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <WorkspacePicker
            value={workspacePath}
            onChange={handleWorkspaceChange}
            allowReselect
            menuRef={workspaceMenuRef}
            isOpen={workspaceMenuOpen}
            onToggle={() => setWorkspaceMenuOpen((open) => !open)}
          />
          <label className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <span className="sr-only">{t("kanban.tenantFilter")}</span>
            <select
              value={tenantFilter ?? ""}
              onChange={(e) => setTenantFilter(e.target.value.trim() || undefined)}
              aria-label={t("kanban.tenantFilter")}
              className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              <option value="">{t("kanban.allTenants")}</option>
              {tenantOptions.map((tenant) => (
                <option key={tenant} value={tenant}>
                  {tenant}
                </option>
              ))}
            </select>
          </label>
          {boards.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              <span className="sr-only">{t("kanban.board")}</span>
              <select
                value={activeBoard ?? ""}
                onChange={(e) => void selectBoard(e.target.value)}
                aria-label={t("kanban.board")}
                className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              >
                {boards.map((b) => (
                  <option key={b.slug} value={b.slug}>
                    {b.label ??
                      (typeof b.name === "string" ? b.name : b.slug)}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleRunDispatch()}
          disabled={dispatching || loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
          title={t("kanban.runDispatcher")}
        >
          {dispatching ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {t("kanban.runDispatcher")}
        </button>
        <button
          type="button"
          onClick={openCreateModal}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >
          <Plus className="h-4 w-4" />
          {t("kanban.newTask")}
        </button>
        <button
          type="button"
          onClick={() => void loadBoard()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label={t("kanban.refresh")}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </header>

      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {dispatchNotice && (
        <div className="mx-4 mt-3 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-800 dark:text-sky-200">
          {dispatchNotice}
        </div>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {loading && !board ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
          </div>
        ) : (
          <div className="relative flex h-full gap-3 overflow-x-auto p-4">
            {columns
              .filter((col) => KANBAN_COLUMNS.includes(col.name as (typeof KANBAN_COLUMNS)[number]))
              .map((column) => (
                <section
                  key={column.name}
                  className={`flex w-72 shrink-0 flex-col rounded-xl border ${COLUMN_COLORS[column.name] ?? "border-zinc-700/30 bg-zinc-500/5"}`}
                  onDragOver={(event) => {
                    if (!dragState) return;
                    event.preventDefault();
                    setDropStatus(column.name);
                  }}
                  onDragLeave={() => {
                    if (dropStatus === column.name) {
                      setDropStatus(null);
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    void handleColumnDrop(column.name);
                  }}
                >
                  <div className="flex items-center justify-between px-3 py-2">
                    <h2 className="text-sm font-medium">
                      {kanbanStatusLabel(column.name, t)}
                    </h2>
                    <span className="rounded-full bg-zinc-200/80 px-2 py-0.5 text-xs dark:bg-zinc-800">
                      {column.tasks.length}
                    </span>
                  </div>
                  <div
                    className={`flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2 ${
                      dragState && dropStatus === column.name
                        ? "rounded-md ring-2 ring-indigo-400/60"
                        : ""
                    }`}
                  >
                    {column.tasks.map((task) => {
                      const blockedReason = kanbanBlockedReason(task);
                      return (
                      <button
                        key={task.id}
                        type="button"
                        draggable
                        onDragStart={() => handleTaskDragStart(task.id, task.status)}
                        onDragEnd={handleTaskDragEnd}
                        onClick={() => void openTask(task.id)}
                        className={`rounded-lg border border-zinc-200 bg-white p-3 text-left shadow-sm transition hover:border-indigo-400/50 dark:border-zinc-700 dark:bg-zinc-900 ${
                          selectedTask?.id === task.id ? "ring-2 ring-indigo-500/50" : ""
                        }`}
                      >
                        <p className="line-clamp-2 text-sm font-medium">{task.title}</p>
                        {blockedReason ? (
                          <p className="mt-1 line-clamp-2 text-xs text-rose-600 dark:text-rose-400">
                            {t("kanban.blockedReason")}: {blockedReason}
                          </p>
                        ) : null}
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                          {task.assignee && <span className="truncate">{task.assignee}</span>}
                          {task.tenant ? (
                            <span className="truncate rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                              {task.tenant}
                            </span>
                          ) : null}
                          {(task.priority ?? 0) !== 0 && (
                            <span className="rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                              {kanbanPriorityLabel(task.priority, t)}
                            </span>
                          )}
                        </div>
                      </button>
                      );
                    })}
                  </div>
                </section>
              ))}
          </div>
        )}

        {selectedTask && (
          <aside className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-[#0c0c0e]">
            <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h3 className="font-medium">{t("kanban.taskDetails")}</h3>
              <button
                type="button"
                onClick={() => setSelectedTask(null)}
                className="rounded p-1 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 space-y-4 overflow-y-auto p-4">
              {selectedTask.status === "blocked" && selectedBlockedReason ? (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-800 dark:text-rose-200">
                  <span className="font-medium">{t("kanban.blockedReason")}: </span>
                  {selectedBlockedReason}
                </div>
              ) : null}
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldTitle")}</span>
                <input
                  value={selectedTask.title}
                  onChange={(e) =>
                    setSelectedTask({ ...selectedTask, title: e.target.value })
                  }
                  className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldStatus")}</span>
                <select
                  value={selectedTask.status}
                  onChange={(e) => handleDetailStatusChange(e.target.value)}
                  className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                >
                  {KANBAN_COLUMNS.map((s) => (
                    <option key={s} value={s}>
                      {kanbanStatusLabel(s, t)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldAssignee")}</span>
                <KanbanAssigneeSelect
                  value={selectedTask.assignee ?? ""}
                  onChange={(assignee) =>
                    setSelectedTask({ ...selectedTask, assignee })
                  }
                  profiles={profiles}
                  historicalAssignees={historicalAssignees}
                  className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldWorkspace")}</span>
                <KanbanWorkspaceSelect
                  workspacePath={detailWorkspacePath}
                  tenant={selectedTask.tenant ?? ""}
                  onChange={(patch) => {
                    setDetailWorkspacePath(patch.workspacePath);
                    setSelectedTask({ ...selectedTask, tenant: patch.tenant });
                  }}
                  workspaces={workspaces}
                  className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldPriority")}</span>
                <KanbanPrioritySelect
                  value={selectedTask.priority ?? 0}
                  onChange={(priority) =>
                    setSelectedTask({
                      ...selectedTask,
                      priority,
                    })
                  }
                  className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs text-zinc-500">{t("kanban.fieldDescription")}</span>
                <textarea
                  rows={6}
                  value={selectedTask.body ?? ""}
                  onChange={(e) =>
                    setSelectedTask({ ...selectedTask, body: e.target.value })
                  }
                  className="w-full resize-none rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              {selectedTaskEvents.length > 0 ? (
                <div className="space-y-2">
                  <span className="text-xs text-zinc-500">{t("kanban.recentEvents")}</span>
                  <ul className="max-h-40 space-y-2 overflow-y-auto rounded-lg border border-zinc-200 bg-zinc-50 p-2 text-xs dark:border-zinc-700 dark:bg-zinc-900">
                    {selectedTaskEvents.slice(-8).reverse().map((event, index) => (
                      <li key={`${event.kind ?? "event"}-${index}`} className="text-zinc-600 dark:text-zinc-300">
                        {kanbanEventSummary(event)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
            <div className="space-y-2 border-t border-zinc-200 p-4 dark:border-zinc-800">
              {selectedTask.status === "blocked" ? (
                <button
                  type="button"
                  onClick={() => void unblockTask(selectedTask.id)}
                  className="w-full rounded-lg border border-zinc-200 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  {t("kanban.unblock")}
                </button>
              ) : null}
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleSaveTask()}
                className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {saving ? t("kanban.saving") : t("kanban.save")}
              </button>
              <button
                type="button"
                onClick={() => void handleDeleteTask()}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 py-2 text-sm font-medium text-rose-700 hover:bg-rose-500/10 dark:text-rose-300"
              >
                <Trash2 className="h-4 w-4" />
                {t("kanban.deleteTask")}
              </button>
            </div>
          </aside>
        )}
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <form
            onSubmit={(e) => void handleCreate(e)}
            className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
          >
            <div className="border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <h3 className="text-lg font-semibold">{t("kanban.newTask")}</h3>
            </div>
            <div className="overflow-y-auto px-5 py-4">
              {createError && (
                <p className="mb-3 text-sm text-amber-700 dark:text-amber-300">{createError}</p>
              )}
              <KanbanTaskFormFields
                values={createForm}
                onChange={patchCreateForm}
                profiles={profiles}
                workspaces={workspaces}
                historicalAssignees={historicalAssignees}
                titleAutoFocus
              />
            </div>
            <div className="flex justify-end gap-2 border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded-lg px-3 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              >
                {t("kanban.cancel")}
              </button>
              <button
                type="submit"
                disabled={creating}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {creating ? t("kanban.creating") : t("kanban.create")}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
