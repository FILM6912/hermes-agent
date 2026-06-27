import { fetchJson } from "@/lib/api";
import type {
  KanbanBoardResponse,
  KanbanBoardsResponse,
  KanbanTaskDetailResponse,
  KanbanTaskResponse,
} from "../types";

export type KanbanQuery = {
  board?: string;
  since?: number;
  include_archived?: boolean;
  only_mine?: boolean;
  assignee?: string;
  tenant?: string;
};

function boardQuery(query?: KanbanQuery): Record<string, string | number | boolean | undefined> {
  if (!query) return {};
  const out: Record<string, string | number | boolean | undefined> = {};
  if (query.board) out.board = query.board;
  if (query.since !== undefined) out.since = query.since;
  if (query.include_archived) out.include_archived = true;
  if (query.only_mine) out.only_mine = true;
  if (query.assignee) out.assignee = query.assignee;
  if (query.tenant) out.tenant = query.tenant;
  return out;
}

/** GET /api/v1/kanban/board */
export async function fetchKanbanBoard(query?: KanbanQuery): Promise<KanbanBoardResponse> {
  return fetchJson<KanbanBoardResponse>("/kanban/board", { query: boardQuery(query) });
}

/** GET /api/v1/kanban/boards */
export async function fetchKanbanBoards(): Promise<KanbanBoardsResponse> {
  return fetchJson<KanbanBoardsResponse>("/kanban/boards");
}

/** POST /api/v1/kanban/boards/{slug}/switch */
export async function switchKanbanBoard(slug: string): Promise<{ ok?: boolean; active?: string }> {
  return fetchJson(`/kanban/boards/${encodeURIComponent(slug)}/switch`, { method: "POST" });
}

/** GET /api/v1/kanban/tasks/{id} — full detail (task, events, comments, …). */
export async function fetchKanbanTask(
  taskId: string,
  query?: KanbanQuery,
): Promise<KanbanTaskDetailResponse> {
  return fetchJson<KanbanTaskDetailResponse>(`/kanban/tasks/${encodeURIComponent(taskId)}`, {
    query: boardQuery(query),
  });
}

/** POST /api/v1/kanban/tasks/bulk — archive tasks (soft delete). */
export async function archiveKanbanTasks(
  ids: string[],
  query?: KanbanQuery,
): Promise<{ results?: Array<{ id: string; ok: boolean; error?: string }> }> {
  return bulkUpdateKanbanTasks(ids, { archive: true }, query);
}

/** POST /api/v1/kanban/tasks/{id}/block */
export async function blockKanbanTask(
  taskId: string,
  reason: string,
  query?: KanbanQuery,
): Promise<KanbanTaskResponse> {
  return fetchJson<KanbanTaskResponse>(`/kanban/tasks/${encodeURIComponent(taskId)}/block`, {
    method: "POST",
    query: boardQuery(query),
    body: { reason },
  });
}

/** POST /api/v1/kanban/tasks/{id}/unblock */
export async function unblockKanbanTask(
  taskId: string,
  query?: KanbanQuery,
): Promise<KanbanTaskResponse> {
  return fetchJson<KanbanTaskResponse>(`/kanban/tasks/${encodeURIComponent(taskId)}/unblock`, {
    method: "POST",
    query: boardQuery(query),
    body: {},
  });
}

export type CreateKanbanTaskInput = {
  title: string;
  body?: string;
  assignee?: string;
  tenant?: string;
  status?: string;
  priority?: number;
  board?: string;
};

/** POST /api/v1/kanban/tasks */
export async function createKanbanTask(input: CreateKanbanTaskInput): Promise<KanbanTaskResponse> {
  const { board, ...body } = input;
  return fetchJson<KanbanTaskResponse>("/kanban/tasks", {
    method: "POST",
    query: board ? { board } : undefined,
    body,
  });
}

/** PATCH /api/v1/kanban/tasks/{id} */
export async function patchKanbanTask(
  taskId: string,
  updates: Record<string, unknown>,
  query?: KanbanQuery,
): Promise<KanbanTaskResponse> {
  return fetchJson<KanbanTaskResponse>(`/kanban/tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    query: boardQuery(query),
    body: updates,
  });
}

/** POST /api/v1/kanban/tasks/bulk — move tasks between columns */
export async function bulkUpdateKanbanTasks(
  ids: string[],
  updates: { status?: string; archive?: boolean },
  query?: KanbanQuery,
): Promise<{ results?: Array<{ id: string; ok: boolean; error?: string }> }> {
  return fetchJson("/kanban/tasks/bulk", {
    method: "POST",
    query: boardQuery(query),
    body: { ids, ...updates },
  });
}

export type KanbanDispatchOptions = {
  board?: string;
  dryRun?: boolean;
  max?: number;
};

/** POST /api/v1/kanban/dispatch — claim Ready tasks and spawn workers. */
export async function dispatchKanban(
  options: KanbanDispatchOptions = {},
): Promise<Record<string, unknown>> {
  const query: Record<string, string | number | boolean | undefined> = {
    max: options.max ?? 8,
  };
  if (options.board) query.board = options.board;
  if (options.dryRun) query.dry_run = true;
  return fetchJson<Record<string, unknown>>("/kanban/dispatch", {
    method: "POST",
    query,
    body: {},
  });
}
