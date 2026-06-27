export const KANBAN_COLUMNS = [
  "triage",
  "todo",
  "ready",
  "running",
  "blocked",
  "done",
] as const;

export type KanbanColumnName = (typeof KANBAN_COLUMNS)[number];

export type KanbanTask = {
  id: string;
  title: string;
  status: string;
  assignee?: string | null;
  tenant?: string | null;
  priority?: number;
  body?: string | null;
  comment_count?: number;
  link_counts?: { parents: number; children: number };
  age_seconds?: number | null;
  progress?: unknown;
  block_reason?: string | null;
  [key: string]: unknown;
};

export type KanbanEvent = {
  kind?: string;
  type?: string;
  payload?: unknown;
  data?: unknown;
  created_at?: number | string;
  ts?: number | string;
  [key: string]: unknown;
};

export type KanbanTaskDetailResponse = {
  task: KanbanTask;
  comments?: unknown[];
  events?: KanbanEvent[];
  links?: { parents?: string[]; children?: string[] };
  runs?: unknown[];
  read_only?: boolean;
};

export type KanbanColumn = {
  name: string;
  tasks: KanbanTask[];
};

export type KanbanBoardResponse = {
  columns: KanbanColumn[];
  tenants?: string[];
  assignees?: string[];
  latest_event_id?: number;
  changed?: boolean;
  read_only?: boolean;
  filters?: Record<string, unknown>;
};

export type KanbanBoardSummary = {
  slug: string;
  label?: string;
  active?: boolean;
  [key: string]: unknown;
};

export type KanbanBoardsResponse = {
  boards: KanbanBoardSummary[];
  active?: string;
};

export type KanbanTaskResponse = {
  task: KanbanTask;
  read_only?: boolean;
};
