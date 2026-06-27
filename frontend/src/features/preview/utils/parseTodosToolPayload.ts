import { isSkillViewToolResult } from "@/features/preview/utils/parseSkillViewToolPayload";

export type TodoItemStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface TodoItem {
  id: string;
  content: string;
  status: TodoItemStatus;
}

const VALID_STATUSES = new Set<TodoItemStatus>([
  "pending",
  "in_progress",
  "completed",
  "cancelled",
]);

/** Strip optional ```json ... ``` fences from tool input text */
export function stripJsonFences(raw: string): string {
  let t = raw.trim();
  const fenced = t.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$/i);
  if (fenced) return fenced[1].trim();
  return t;
}

function tryParseJsonString(raw: string): unknown | null {
  const t = stripJsonFences(raw);
  if (!t || (!t.startsWith("{") && !t.startsWith("["))) return null;
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

/** Best-effort parse for Python-style single-quoted dict/list literals */
function tryParsePythonishJson(raw: string): unknown | null {
  const t = stripJsonFences(raw).trim();
  if (!t.startsWith("{") && !t.startsWith("[")) return null;
  try {
    const normalized = t
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false")
      .replace(/\bNone\b/g, "null")
      .replace(/'/g, '"');
    return JSON.parse(normalized);
  } catch {
    return null;
  }
}

export function isTodosToolName(name: string | undefined): boolean {
  if (!name?.trim()) return false;
  const key = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
  return (
    key === "todo" ||
    key === "todos" ||
    key === "to_dos" ||
    key === "todowrite" ||
    key === "todo_write" ||
    key.startsWith("todo_")
  );
}

function normalizeStatus(raw: unknown): TodoItemStatus {
  const status = String(raw ?? "pending")
    .trim()
    .toLowerCase();
  if (VALID_STATUSES.has(status as TodoItemStatus)) {
    return status as TodoItemStatus;
  }
  return "pending";
}

function isTodoItemRecord(rec: Record<string, unknown>): boolean {
  if (isSkillViewToolResult(rec)) return false;
  if (
    "file_path" in rec ||
    "bytes_written" in rec ||
    "resolved_path" in rec ||
    "files_modified" in rec ||
    "command" in rec ||
    "cwd" in rec
  ) {
    return false;
  }
  const hasTaskText =
    typeof rec.content === "string" ||
    typeof rec.text === "string" ||
    typeof rec.title === "string";
  if (!hasTaskText) return false;
  return "id" in rec || "status" in rec;
}

function normalizeTodoItem(item: unknown, index: number): TodoItem | null {
  if (!item || typeof item !== "object") return null;
  const rec = item as Record<string, unknown>;
  if (!isTodoItemRecord(rec)) return null;
  const content = String(rec.content ?? rec.text ?? rec.title ?? "").trim();
  if (!content) return null;
  const id = String(rec.id ?? `todo-${index + 1}`).trim() || `todo-${index + 1}`;
  return {
    id,
    content,
    status: normalizeStatus(rec.status),
  };
}

function todosFromArray(arr: unknown[]): TodoItem[] | null {
  const items = arr
    .map((item, index) => normalizeTodoItem(item, index))
    .filter((item): item is TodoItem => item !== null);
  return items.length > 0 ? items : null;
}

function todosFromObject(obj: Record<string, unknown>): TodoItem[] | null {
  if (isSkillViewToolResult(obj)) return null;
  if (Array.isArray(obj.todos)) return todosFromArray(obj.todos);
  if (Array.isArray(obj.tasks)) return todosFromArray(obj.tasks);
  const single = normalizeTodoItem(obj, 0);
  if (single) return [single];
  return null;
}

function todosFromUnknown(value: unknown): TodoItem[] | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") {
    const parsed =
      tryParseJsonString(value) ?? tryParsePythonishJson(value);
    return parsed !== null ? todosFromUnknown(parsed) : null;
  }
  if (Array.isArray(value)) return todosFromArray(value);
  if (typeof value === "object") {
    return todosFromObject(value as Record<string, unknown>);
  }
  return null;
}

/** Parse todos from tool args, JSON input, or tool result payload. */
export function parseTodosFromToolPayload(raw: unknown): TodoItem[] | null {
  return todosFromUnknown(raw);
}
