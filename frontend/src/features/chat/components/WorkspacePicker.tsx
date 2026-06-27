import React from "react";
import {
  Check,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  Pencil,
  Plus,
  Shield,
  Trash2,
} from "lucide-react";
import { ConfirmModal } from "@/components/ConfirmModal";
import { InputModal } from "@/components/InputModal";
import { useLanguage } from "@/hooks/useLanguage";
import {
  createNestedWorkspace,
  isProtectedWorkspaceRoot,
  listWorkspaces,
  removeWorkspace,
  renameWorkspace,
  type HermesWorkspace,
} from "@/services/hermes/workspace";

export type WorkspacePickerProps = {
  value: string;
  onChange: (path: string, name: string) => void | Promise<void>;
  /** Allow selecting the current value (re-bind session workspace). */
  allowReselect?: boolean;
  disabled?: boolean;
  menuRef?: React.RefObject<HTMLDivElement | null>;
  isOpen?: boolean;
  onToggle?: () => void;
};

type DialogState =
  | { kind: "none" }
  | { kind: "rename"; ws: HermesWorkspace }
  | { kind: "addPath" }
  | { kind: "delete"; ws: HermesWorkspace };

function workspaceLabel(
  workspaces: HermesWorkspace[],
  path: string,
): string {
  if (!path) return "";
  const match = workspaces.find((w) => w.path === path);
  if (match?.name) return match.name;
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

function defaultParentPath(workspaces: HermesWorkspace[]): string {
  const root = workspaces.find((w) => w.path === "/workspace");
  if (root) return "/workspace";
  const virtual = workspaces.find((w) => w.path.startsWith("/workspace"));
  return virtual?.path ?? "/workspace";
}

export const WorkspacePicker: React.FC<WorkspacePickerProps> = ({
  value,
  onChange,
  allowReselect = false,
  disabled = false,
  menuRef,
  isOpen = false,
  onToggle,
}) => {
  const { t } = useLanguage();
  const [workspaces, setWorkspaces] = React.useState<HermesWorkspace[]>([]);
  const [nestedWorkspaces, setNestedWorkspaces] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [switching, setSwitching] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showCreate, setShowCreate] = React.useState(false);
  const [createName, setCreateName] = React.useState("");
  const [createParent, setCreateParent] = React.useState("/workspace");
  const [createError, setCreateError] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<DialogState>({ kind: "none" });
  const [dialogError, setDialogError] = React.useState<string | null>(null);

  const loadList = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listWorkspaces();
      setWorkspaces(data.workspaces);
      setNestedWorkspaces(Boolean(data.nested_workspaces));
      setCreateParent(defaultParentPath(data.workspaces));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workspaces");
      setWorkspaces([]);
      setNestedWorkspaces(false);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadList();
  }, [loadList]);

  React.useEffect(() => {
    if (isOpen) void loadList();
  }, [isOpen, loadList]);

  React.useEffect(() => {
    if (!isOpen) {
      setShowCreate(false);
      setCreateName("");
      setCreateError(null);
      // Portaled rename/delete modals stay open when the popover closes.
    }
  }, [isOpen]);

  const handleSelect = async (path: string, name: string) => {
    if (!path || switching) return;
    if (path === value && !allowReselect) return;
    setSwitching(path);
    setError(null);
    try {
      await onChange(path, name);
      await loadList();
      onToggle?.();
    } catch (err) {
      console.error("Failed to switch workspace:", err);
      setError(err instanceof Error ? err.message : "Failed to switch workspace");
    } finally {
      setSwitching(null);
    }
  };

  const submitRename = async (ws: HermesWorkspace, newName: string) => {
    if (!newName || newName === (ws.name || ws.path)) return;
    setSwitching(ws.path);
    setError(null);
    try {
      const result = await renameWorkspace(ws.path, newName);
      setWorkspaces(result.workspaces);
      if (value === ws.path) {
        await onChange(ws.path, newName);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to rename workspace";
      setError(message);
      throw err instanceof Error ? err : new Error(message);
    } finally {
      setSwitching(null);
    }
  };

  const submitAddPath = async (path: string) => {
    if (!path) return;
    await handleSelect(path, path);
  };

  const submitRemove = async (ws: HermesWorkspace) => {
    setSwitching(ws.path);
    setError(null);
    try {
      const result = await removeWorkspace(ws.path);
      setWorkspaces(result.workspaces);
      if (value === ws.path) {
        const fallback =
          result.workspaces.find((w) => isProtectedWorkspaceRoot(w.path)) ??
          result.workspaces[0];
        if (fallback) {
          await onChange(fallback.path, fallback.name || fallback.path);
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to remove workspace";
      setError(message);
      setDialogError(message);
      throw err instanceof Error ? err : new Error(message);
    } finally {
      setSwitching(null);
    }
  };

  const handleCreateNested = async () => {
    if (switching) return;
    const name = createName.trim();
    if (!name) {
      setCreateError(t("chat.workspaceCreateName") || "Folder name is required");
      return;
    }
    setSwitching("__create__");
    setCreateError(null);
    setError(null);
    try {
      const result = await createNestedWorkspace(name, {
        displayName: name,
        parent: createParent,
      });
      setWorkspaces(result.workspaces);
      setNestedWorkspaces(Boolean(result.nested_workspaces));
      const createdPath =
        result.path ||
        result.workspaces.find(
          (w) => w.name === name || w.path.endsWith(`/${name}`),
        )?.path;
      if (createdPath) {
        const created = result.workspaces.find((w) => w.path === createdPath);
        await onChange(createdPath, created?.name || name);
        setShowCreate(false);
        setCreateName("");
        onToggle?.();
      } else {
        await loadList();
        setShowCreate(false);
        setCreateName("");
      }
    } catch (err) {
      setCreateError(
        err instanceof Error ? err.message : "Failed to create workspace",
      );
    } finally {
      setSwitching(null);
    }
  };

  const label =
    workspaceLabel(workspaces, value) ||
    t("chat.noWorkspace") ||
    "Workspace";
  const hasSelection = !!value;
  const isCreating = switching === "__create__";

  const sorted = React.useMemo(
    () =>
      [...workspaces].sort((a, b) => {
        const aRoot = isProtectedWorkspaceRoot(a.path);
        const bRoot = isProtectedWorkspaceRoot(b.path);
        if (aRoot !== bRoot) return aRoot ? -1 : 1;
        return (a.name || a.path).localeCompare(b.name || b.path, undefined, {
          sensitivity: "base",
        });
      }),
    [workspaces],
  );

  const parentOptions = React.useMemo(() => {
    const virtual = sorted.filter(
      (w) => w.path === "/workspace" || w.path.startsWith("/workspace/"),
    );
    return virtual.length > 0 ? virtual : sorted;
  }, [sorted]);

  const renameDialog = dialog.kind === "rename" ? dialog.ws : null;
  const deleteDialog = dialog.kind === "delete" ? dialog.ws : null;

  return (
    <>
      <div className="relative" ref={menuRef}>
        {isOpen && (
          <div className="absolute bottom-full mb-2 left-0 w-[min(19rem,calc(100vw-1.5rem))] max-h-[min(22rem,75vh)] bg-white dark:bg-[#18181b] border border-zinc-200/80 dark:border-zinc-800 rounded-2xl shadow-2xl shadow-black/10 dark:shadow-black/40 z-50 flex flex-col animate-in slide-in-from-bottom-2 fade-in duration-200 overflow-hidden">
            <div className="px-3.5 py-2.5 border-b border-zinc-200/80 dark:border-zinc-800 bg-gradient-to-r from-zinc-50 to-indigo-50/40 dark:from-zinc-900/80 dark:to-indigo-950/20 flex justify-between items-center">
              <div className="flex items-center gap-2 min-w-0">
                <div className="p-1 rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400">
                  <FolderOpen className="w-3.5 h-3.5" />
                </div>
                <span className="text-[11px] font-semibold text-zinc-700 dark:text-zinc-200 tracking-wide">
                  {t("chat.workspacePicker") || "Workspace"}
                </span>
              </div>
              <span className="text-[10px] font-bold tabular-nums bg-white/80 dark:bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded-full border border-zinc-200/80 dark:border-zinc-700">
                {loading ? "…" : workspaces.length}
              </span>
            </div>

            {error ? (
              <div className="mx-2.5 mt-2 rounded-lg border border-rose-500/25 bg-rose-500/10 px-2.5 py-2 text-[11px] text-rose-600 dark:text-rose-300">
                {error}
              </div>
            ) : null}

            <div className="p-2 max-h-56 overflow-y-auto scrollbar-hide space-y-1">
              {loading && workspaces.length === 0 ? (
                <div className="flex items-center justify-center gap-2 text-xs text-zinc-500 py-8">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                  <span>{t("chat.workspaceLoading") || "Loading…"}</span>
                </div>
              ) : sorted.length === 0 ? (
                <div className="text-xs text-zinc-500 text-center py-8 italic">
                  {t("chat.noWorkspaces") || "No workspaces"}
                </div>
              ) : (
                sorted.map((ws) => {
                  const isActive = ws.path === value;
                  const isBusy = switching === ws.path;
                  const isRoot = isProtectedWorkspaceRoot(ws.path);
                  const canManage = nestedWorkspaces && !isRoot;
                  return (
                    <div
                      key={ws.path}
                      className={`group rounded-xl border transition-all ${
                        isActive
                          ? "border-indigo-300/70 dark:border-indigo-700/60 bg-indigo-50/80 dark:bg-indigo-950/30 shadow-sm"
                          : "border-transparent hover:border-zinc-200 dark:hover:border-zinc-700/80 hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
                      }`}
                    >
                      <div className="flex items-stretch gap-0.5 p-1">
                        <button
                          type="button"
                          disabled={!!switching}
                          onClick={() => handleSelect(ws.path, ws.name || ws.path)}
                          className="min-w-0 flex-1 flex items-center gap-2.5 p-2 rounded-lg text-left disabled:opacity-60"
                        >
                          <div
                            className={`shrink-0 p-1.5 rounded-lg ${
                              isActive
                                ? "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400"
                                : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500"
                            }`}
                          >
                            {isRoot ? (
                              <Shield className="w-3.5 h-3.5" />
                            ) : (
                              <Folder className="w-3.5 h-3.5" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <span
                                className={`text-xs font-semibold truncate ${
                                  isActive
                                    ? "text-indigo-700 dark:text-indigo-300"
                                    : "text-zinc-800 dark:text-zinc-200"
                                }`}
                              >
                                {ws.name || ws.path}
                              </span>
                              {isRoot ? (
                                <span className="text-[9px] uppercase tracking-wide text-zinc-400">
                                  main
                                </span>
                              ) : null}
                            </div>
                            <div className="text-[10px] text-zinc-500 truncate font-mono">
                              {ws.path}
                            </div>
                          </div>
                          {isBusy ? (
                            <Loader2 className="w-4 h-4 animate-spin shrink-0 text-indigo-500" />
                          ) : isActive ? (
                            <Check className="w-4 h-4 shrink-0 text-indigo-500" />
                          ) : null}
                        </button>
                        {canManage ? (
                          <div className="flex shrink-0 items-center gap-0.5 pr-1 opacity-80 group-hover:opacity-100">
                            <button
                              type="button"
                              disabled={!!switching || disabled}
                              title={t("chat.workspaceRename") || "Rename"}
                              aria-label={t("chat.workspaceRename") || "Rename"}
                              onClick={(event) => {
                                event.stopPropagation();
                                setDialogError(null);
                                setDialog({ kind: "rename", ws });
                              }}
                              className="p-1.5 rounded-lg text-zinc-500 hover:text-indigo-600 hover:bg-white dark:hover:bg-zinc-900 disabled:opacity-40 transition-colors"
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              disabled={!!switching || disabled}
                              title={t("chat.workspaceRemove") || "Remove"}
                              aria-label={t("chat.workspaceRemove") || "Remove"}
                              onClick={(event) => {
                                event.stopPropagation();
                                setDialogError(null);
                                setDialog({ kind: "delete", ws });
                              }}
                              className="p-1.5 rounded-lg text-zinc-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-40 transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="border-t border-zinc-200/80 dark:border-zinc-800 p-2 space-y-1.5 bg-zinc-50/50 dark:bg-zinc-900/30">
              {showCreate && nestedWorkspaces ? (
                <div className="rounded-xl border border-indigo-200/60 dark:border-indigo-900/50 p-3 space-y-2.5 bg-white/90 dark:bg-zinc-900/60">
                  <p className="text-[10px] text-zinc-500 leading-snug">
                    {t("chat.workspaceCreateHint")}
                  </p>
                  <label className="block">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                      {t("chat.workspaceCreateName")}
                    </span>
                    <input
                      type="text"
                      value={createName}
                      onChange={(e) => {
                        setCreateName(e.target.value);
                        setCreateError(null);
                      }}
                      placeholder={t("chat.workspaceCreateNamePlaceholder")}
                      className="mt-1 w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                      autoFocus
                    />
                  </label>
                  <label className="block">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                      {t("chat.workspaceCreateParent")}
                    </span>
                    <select
                      value={createParent}
                      onChange={(e) => setCreateParent(e.target.value)}
                      className="mt-1 w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 px-2.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                    >
                      {parentOptions.map((ws) => (
                        <option key={ws.path} value={ws.path}>
                          {ws.name || ws.path} ({ws.path})
                        </option>
                      ))}
                    </select>
                  </label>
                  {createError ? (
                    <p className="text-[10px] text-red-500">{createError}</p>
                  ) : null}
                  <div className="flex gap-2 pt-0.5">
                    <button
                      type="button"
                      disabled={!!switching || disabled}
                      onClick={() => void handleCreateNested()}
                      className="flex-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold py-2 disabled:opacity-60 transition-colors"
                    >
                      {isCreating ? (
                        <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                      ) : (
                        t("chat.workspaceCreateSubmit")
                      )}
                    </button>
                    <button
                      type="button"
                      disabled={!!switching}
                      onClick={() => {
                        setShowCreate(false);
                        setCreateError(null);
                      }}
                      className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-medium py-2 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                    >
                      {t("chat.workspaceCreateCancel")}
                    </button>
                  </div>
                </div>
              ) : null}
              {nestedWorkspaces ? (
                <button
                  type="button"
                  disabled={!!switching || disabled}
                  onClick={() => {
                    setShowCreate((open) => !open);
                    setCreateError(null);
                  }}
                  className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-left text-xs font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-950/30 disabled:opacity-60 transition-colors"
                >
                  <FolderPlus className="w-4 h-4 shrink-0" />
                  <span>{t("chat.workspaceCreate")}</span>
                </button>
              ) : null}
              <button
                type="button"
                disabled={!!switching || disabled}
                onClick={() => setDialog({ kind: "addPath" })}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl text-left text-xs font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/60 disabled:opacity-60 transition-colors"
              >
                {switching && !isCreating ? (
                  <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                ) : (
                  <Plus className="w-4 h-4 shrink-0" />
                )}
                <span>{t("chat.workspaceAddPath") || "Choose path…"}</span>
              </button>
              {!nestedWorkspaces && !loading ? (
                <p className="text-[10px] text-zinc-500 px-2 leading-snug">
                  {t("chat.workspaceCreateBlocked")}
                </p>
              ) : null}
            </div>
          </div>
        )}
        <button
          type="button"
          disabled={disabled || !!switching}
          onClick={onToggle}
          className={`flex items-center gap-1.5 max-w-[min(6.5rem,26vw)] sm:max-w-[140px] px-2.5 sm:px-3 py-1.5 rounded-full border transition-all ${
            isOpen || hasSelection
              ? "bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-zinc-800 text-indigo-700 dark:text-indigo-400 shadow-sm"
              : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400"
          } disabled:opacity-60`}
          title={value || t("chat.workspacePicker") || "Workspace"}
        >
          <Folder className="w-3.5 h-3.5 shrink-0" />
          <span className="text-xs font-medium truncate">{label}</span>
        </button>
      </div>

      <InputModal
        isOpen={renameDialog !== null}
        onClose={() => setDialog({ kind: "none" })}
        onConfirm={(newName) => {
          if (!renameDialog) return;
          void submitRename(renameDialog, newName);
        }}
        title={t("chat.workspaceRenameTitle") || "Rename workspace"}
        initialValue={renameDialog?.name || renameDialog?.path || ""}
        placeholder={t("chat.workspaceRenamePrompt") || "Display name"}
        confirmText={t("chat.workspaceRename") || "Save"}
        cancelText={t("chat.workspaceCreateCancel") || "Cancel"}
      />

      <InputModal
        isOpen={dialog.kind === "addPath"}
        onClose={() => setDialog({ kind: "none" })}
        onConfirm={(path) => void submitAddPath(path)}
        title={t("chat.workspaceAddPathTitle") || "Add workspace path"}
        initialValue={value || ""}
        placeholder={t("chat.workspacePathPrompt") || "/path/to/folder"}
        confirmText={t("chat.workspaceAddPath") || "Add"}
        cancelText={t("chat.workspaceCreateCancel") || "Cancel"}
      />

      <ConfirmModal
        isOpen={deleteDialog !== null}
        onClose={() => {
          setDialog({ kind: "none" });
          setDialogError(null);
        }}
        onConfirm={() => {
          if (!deleteDialog) return;
          return submitRemove(deleteDialog);
        }}
        title={t("chat.workspaceRemoveTitle") || "Remove workspace"}
        message={(() => {
          if (!deleteDialog) return dialogError || "";
          const lines = [
            t("chat.workspaceRemoveHint"),
            "",
            deleteDialog.name || deleteDialog.path,
            deleteDialog.path,
          ];
          if (dialogError) {
            lines.push("", dialogError);
          }
          return lines.join("\n");
        })()}
        confirmText={t("chat.workspaceRemove") || "Remove"}
        cancelText={t("chat.workspaceCreateCancel") || "Cancel"}
        type="danger"
      />
    </>
  );
};
