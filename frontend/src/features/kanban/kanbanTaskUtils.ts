import type { KanbanEvent, KanbanTask } from "./types";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(task: KanbanTask, ...keys: string[]): string {
  for (const key of keys) {
    const value = task[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** Latest human-readable block reason from task fields or event log. */
export function kanbanBlockedReason(
  task: KanbanTask | null | undefined,
  events?: KanbanEvent[] | null,
): string {
  if (!task || task.status !== "blocked") return "";

  const direct = stringField(
    task,
    "block_reason",
    "blocked_reason",
    "blockReason",
    "blockedReason",
    "last_block_reason",
  );
  if (direct) return direct;

  const progress = task.progress;
  if (typeof progress === "string" && progress.trim()) return progress.trim();
  const progressRecord = asRecord(progress);
  if (progressRecord) {
    const nested = stringField(progressRecord as KanbanTask, "reason", "summary", "message");
    if (nested) return nested;
  }

  const list = events ?? [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const event = list[i];
    const kind = (event.kind ?? event.type ?? "").toLowerCase();
    if (!kind.includes("block")) continue;
    const payload = asRecord(event.payload ?? event.data);
    const reason = payload ? stringField(payload as KanbanTask, "reason", "summary", "message") : "";
    if (reason) return reason;
  }

  return "";
}

export function kanbanEventSummary(event: KanbanEvent): string {
  const kind = event.kind ?? event.type ?? "event";
  const payload = asRecord(event.payload ?? event.data);
  if (!payload) return String(kind);
  const parts: string[] = [];
  for (const key of ["status", "reason", "summary", "message"] as const) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) parts.push(value.trim());
  }
  const fields = payload.fields;
  if (Array.isArray(fields)) {
    parts.push(fields.map(String).join(", "));
  }
  return parts.length ? `${kind}: ${parts.join(" · ")}` : String(kind);
}
