/** Format POST /kanban/dispatch result for toast (legacy _kanbanFormatDispatchResult). */
export type KanbanDispatchResult = {
  spawned?: unknown[];
  promoted?: number;
  reclaimed?: number;
  skipped_unassigned?: unknown[];
  skipped_nonspawnable?: unknown[];
  auto_blocked?: unknown[];
  timed_out?: unknown[];
  crashed?: unknown[];
};

export function formatKanbanDispatchResult(
  result: KanbanDispatchResult | null | undefined,
  t: (path: string) => string,
  dryRun = false,
): string {
  const r = result ?? {};
  const spawned = Array.isArray(r.spawned) ? r.spawned.length : 0;
  const promoted = Number(r.promoted) || 0;
  const reclaimed = Number(r.reclaimed) || 0;
  const skippedUnassigned = Array.isArray(r.skipped_unassigned) ? r.skipped_unassigned.length : 0;
  const skippedNonspawnable = Array.isArray(r.skipped_nonspawnable)
    ? r.skipped_nonspawnable.length
    : 0;
  const autoBlocked = Array.isArray(r.auto_blocked) ? r.auto_blocked.length : 0;
  const timedOut = Array.isArray(r.timed_out) ? r.timed_out.length : 0;
  const crashed = Array.isArray(r.crashed) ? r.crashed.length : 0;

  const verb = dryRun ? t("kanban.dispatchPreview") : t("kanban.dispatchRun");
  const parts: string[] = [];
  parts.push(`${spawned} ${t("kanban.dispatchSpawned")}`);
  if (promoted) parts.push(`${promoted} ${t("kanban.dispatchPromoted")}`);
  if (reclaimed) parts.push(`${reclaimed} ${t("kanban.dispatchReclaimed")}`);
  if (skippedUnassigned) {
    parts.push(`${skippedUnassigned} ${t("kanban.dispatchSkippedUnassigned")}`);
  }
  if (skippedNonspawnable) {
    parts.push(`${skippedNonspawnable} ${t("kanban.dispatchSkippedNonspawnable")}`);
  }
  if (autoBlocked) parts.push(`${autoBlocked} ${t("kanban.dispatchAutoBlocked")}`);
  if (timedOut) parts.push(`${timedOut} ${t("kanban.dispatchTimedOut")}`);
  if (crashed) parts.push(`${crashed} ${t("kanban.dispatchCrashed")}`);
  return `${verb} ${parts.join(", ")}`;
}

/** Tenant slug for Kanban filter/create from a Hermes workspace path. */
export function workspaceTenantSlug(path: string, name?: string): string {
  const trimmedName = name?.trim();
  if (trimmedName) return trimmedName;
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || path.trim();
}

export type KanbanWorkspaceLike = { path: string; name?: string };

/** Resolve a Hermes workspace path from a Kanban tenant slug. */
export function workspacePathForTenant(
  workspaces: KanbanWorkspaceLike[],
  tenant: string | null | undefined,
): string {
  const slug = (tenant ?? "").trim();
  if (!slug) return "";
  for (const workspace of workspaces) {
    if (workspaceTenantSlug(workspace.path, workspace.name) === slug) {
      return workspace.path;
    }
    if (workspace.name?.trim() === slug) return workspace.path;
  }
  return "";
}

export function workspaceDisplayLabel(path: string, name?: string): string {
  const trimmedName = name?.trim();
  if (trimmedName) return trimmedName;
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || path.trim();
}
