/** Kanban priority levels (matches legacy static-legacy/panels.js). */
export const KANBAN_PRIORITY_LEVELS = [
  { value: -1, labelKey: "kanban.priorityLow" },
  { value: 0, labelKey: "kanban.priorityNormal" },
  { value: 1, labelKey: "kanban.priorityHigh" },
  { value: 2, labelKey: "kanban.priorityUrgent" },
] as const;

export function kanbanPriorityLabel(
  priority: number | null | undefined,
  t: (path: string) => string,
): string {
  const n = Number(priority);
  if (Number.isNaN(n)) return "";
  const hit = KANBAN_PRIORITY_LEVELS.find((level) => level.value === n);
  if (hit) return t(hit.labelKey);
  return t("kanban.priorityCustom").replace("{n}", String(n));
}

export function kanbanStatusLabel(status: string, t: (path: string) => string): string {
  const key = `kanban.status.${status}`;
  const label = t(key);
  return label === key ? status : label;
}
