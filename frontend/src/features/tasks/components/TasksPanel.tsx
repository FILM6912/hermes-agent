import React from "react";
import {
  ArrowLeft,
  CalendarClock,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Pencil,
} from "lucide-react";
import {
  cronStatusLabel,
  formatSchedule,
} from "../api/cronsApi";
import { useCrons } from "../hooks/useCrons";

const STATUS_TONE: Record<string, string> = {
  ok: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  warn: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  err: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  muted: "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400",
};

interface TasksPanelProps {
  onBack: () => void;
}

export const TasksPanel: React.FC<TasksPanelProps> = ({ onBack }) => {
  const {
    jobs,
    loading,
    error,
    selectedJob,
    selectedId,
    formMode,
    formValues,
    setFormValues,
    profiles,
    deliveryOptions,
    actionPending,
    loadJobs,
    selectJob,
    openCreate,
    openEdit,
    cancelForm,
    saveForm,
    runAction,
  } = useCrons();

  const isEditing = formMode === "create" || formMode === "edit";

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <CalendarClock className="h-5 w-5 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Scheduled jobs</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            Cron jobs and recurring agent tasks
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
        >
          <Plus className="h-4 w-4" />
          New job
        </button>
        <button
          type="button"
          onClick={() => void loadJobs()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh jobs"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </header>

      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="flex w-80 shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-800">
          <div className="flex-1 overflow-y-auto">
            {loading && jobs.length === 0 ? (
              <div className="flex justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />
              </div>
            ) : jobs.length === 0 ? (
              <p className="p-4 text-sm text-zinc-500">No scheduled jobs yet.</p>
            ) : (
              jobs.map((job) => {
                const status = cronStatusLabel(job);
                return (
                  <button
                    key={job.id}
                    type="button"
                    onClick={() => selectJob(job)}
                    className={`w-full border-b border-zinc-100 px-4 py-3 text-left transition dark:border-zinc-800/80 ${
                      selectedId === job.id
                        ? "bg-indigo-50 dark:bg-indigo-950/30"
                        : "hover:bg-zinc-100 dark:hover:bg-zinc-900"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="line-clamp-1 text-sm font-medium">
                        {job.name || job.id}
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${STATUS_TONE[status.tone]}`}
                      >
                        {status.label}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-zinc-500">
                      {formatSchedule(job.schedule)}
                    </p>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {!selectedJob && formMode !== "create" ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-zinc-500">
              <CalendarClock className="h-10 w-10 opacity-40" />
              <p className="text-sm">Select a job or create a new one</p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
                <h2 className="text-sm font-medium">
                  {formMode === "create"
                    ? "New scheduled job"
                    : selectedJob?.name || selectedJob?.id}
                </h2>
                {!isEditing && selectedJob && (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={actionPending}
                      onClick={() => void runAction("run")}
                      className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                      title="Run now"
                    >
                      <Play className="h-4 w-4" />
                    </button>
                    {selectedJob.state === "paused" ? (
                      <button
                        type="button"
                        disabled={actionPending}
                        onClick={() => void runAction("resume")}
                        className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                        title="Resume"
                      >
                        <Play className="h-4 w-4" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={actionPending}
                        onClick={() => void runAction("pause")}
                        className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                        title="Pause"
                      >
                        <Pause className="h-4 w-4" />
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={actionPending}
                      onClick={openEdit}
                      className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                      title="Edit"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      disabled={actionPending}
                      onClick={() => void runAction("delete")}
                      className="rounded-lg p-2 text-rose-600 hover:bg-rose-500/10"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                {isEditing ? (
                  <form
                    className="mx-auto max-w-xl space-y-4"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void saveForm();
                    }}
                  >
                    <label className="block space-y-1">
                      <span className="text-xs text-zinc-500">Name</span>
                      <input
                        value={formValues.name}
                        onChange={(e) =>
                          setFormValues({ ...formValues, name: e.target.value })
                        }
                        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                        placeholder="Optional display name"
                      />
                    </label>
                    <label className="block space-y-1">
                      <span className="text-xs text-zinc-500">Schedule</span>
                      <input
                        value={formValues.schedule}
                        onChange={(e) =>
                          setFormValues({ ...formValues, schedule: e.target.value })
                        }
                        required
                        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                        placeholder="every 1h, 0 9 * * *, @daily"
                      />
                    </label>
                    {!selectedJob?.no_agent && (
                      <label className="block space-y-1">
                        <span className="text-xs text-zinc-500">Prompt</span>
                        <textarea
                          rows={5}
                          value={formValues.prompt}
                          onChange={(e) =>
                            setFormValues({ ...formValues, prompt: e.target.value })
                          }
                          required={formMode === "create"}
                          className="w-full resize-none rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                        />
                      </label>
                    )}
                    <label className="block space-y-1">
                      <span className="text-xs text-zinc-500">Delivery</span>
                      <select
                        value={formValues.deliver}
                        onChange={(e) =>
                          setFormValues({ ...formValues, deliver: e.target.value })
                        }
                        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                      >
                        {(deliveryOptions.length
                          ? deliveryOptions
                          : [{ value: "local", label: "Local" }]
                        ).map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block space-y-1">
                      <span className="text-xs text-zinc-500">Profile</span>
                      <select
                        value={formValues.profile}
                        onChange={(e) =>
                          setFormValues({ ...formValues, profile: e.target.value })
                        }
                        className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                      >
                        <option value="">Server default</option>
                        {profiles.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={formValues.toast_notifications}
                        onChange={(e) =>
                          setFormValues({
                            ...formValues,
                            toast_notifications: e.target.checked,
                          })
                        }
                        className="rounded border-zinc-300"
                      />
                      Show completion toasts
                    </label>
                    <div className="flex justify-end gap-2 pt-2">
                      <button
                        type="button"
                        onClick={cancelForm}
                        className="rounded-lg px-3 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={actionPending}
                        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                      >
                        {actionPending ? "Saving…" : formMode === "create" ? "Create" : "Save"}
                      </button>
                    </div>
                  </form>
                ) : selectedJob ? (
                  <dl className="mx-auto max-w-xl space-y-4 text-sm">
                    <div>
                      <dt className="text-xs text-zinc-500">Schedule</dt>
                      <dd className="mt-1 font-mono text-sm">
                        {formatSchedule(selectedJob.schedule)}
                      </dd>
                    </div>
                    {selectedJob.prompt && (
                      <div>
                        <dt className="text-xs text-zinc-500">Prompt</dt>
                        <dd className="mt-1 whitespace-pre-wrap rounded-lg bg-zinc-100 p-3 dark:bg-zinc-900">
                          {selectedJob.prompt}
                        </dd>
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <dt className="text-xs text-zinc-500">Delivery</dt>
                        <dd className="mt-1">{selectedJob.deliver ?? "local"}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">Profile</dt>
                        <dd className="mt-1">{selectedJob.profile || "Server default"}</dd>
                      </div>
                    </div>
                    {selectedJob.last_run != null && (
                      <div>
                        <dt className="text-xs text-zinc-500">Last run</dt>
                        <dd className="mt-1">{String(selectedJob.last_run)}</dd>
                      </div>
                    )}
                  </dl>
                ) : null}
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
};
