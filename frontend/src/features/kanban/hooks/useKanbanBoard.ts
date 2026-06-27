import { useCallback, useEffect, useState } from "react";
import { HermesApiError } from "@/lib/api";
import {
  archiveKanbanTasks,
  blockKanbanTask,
  bulkUpdateKanbanTasks,
  createKanbanTask,
  dispatchKanban,
  fetchKanbanBoard,
  fetchKanbanBoards,
  fetchKanbanTask,
  patchKanbanTask,
  switchKanbanBoard,
  unblockKanbanTask,
  type CreateKanbanTaskInput,
} from "../api/kanbanApi";
import { useKanbanEvents } from "./useKanbanEvents";
import type {
  KanbanBoardResponse,
  KanbanBoardSummary,
  KanbanEvent,
  KanbanTask,
} from "../types";

export function useKanbanBoard() {
  const [board, setBoard] = useState<KanbanBoardResponse | null>(null);
  const [boards, setBoards] = useState<KanbanBoardSummary[]>([]);
  const [activeBoard, setActiveBoard] = useState<string | undefined>();
  const [latestEventId, setLatestEventId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<KanbanTask | null>(null);
  const [selectedTaskEvents, setSelectedTaskEvents] = useState<KanbanEvent[]>([]);
  const [tenantFilter, setTenantFilter] = useState<string | undefined>();

  const loadBoard = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true);
    setError(null);
    try {
      const data = await fetchKanbanBoard({
        board: activeBoard,
        since: latestEventId > 0 ? latestEventId : undefined,
        tenant: tenantFilter,
      });
      if (data.changed === false) {
        if (typeof data.latest_event_id === "number") {
          setLatestEventId(data.latest_event_id);
        }
        return;
      }
      setBoard(data);
      if (typeof data.latest_event_id === "number") {
        setLatestEventId(data.latest_event_id);
      }
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load kanban board";
      setError(message);
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, [activeBoard, latestEventId, tenantFilter]);

  const loadBoards = useCallback(async () => {
    try {
      const data = await fetchKanbanBoards();
      setBoards(data.boards ?? []);
      if (data.active) setActiveBoard(data.active);
    } catch {
      /* boards list is optional */
    }
  }, []);

  useEffect(() => {
    void loadBoards();
  }, [loadBoards]);

  useEffect(() => {
    setLatestEventId(0);
  }, [tenantFilter]);

  useEffect(() => {
    void loadBoard();
  }, [loadBoard]);

  useKanbanEvents({
    board: activeBoard,
    since: latestEventId,
    onBoardChanged: () => {
      void loadBoard({ silent: true });
    },
  });

  const selectBoard = useCallback(
    async (slug: string) => {
      await switchKanbanBoard(slug);
      setActiveBoard(slug);
      setLatestEventId(0);
      setSelectedTask(null);
      setSelectedTaskEvents([]);
    },
    [],
  );

  const openTask = useCallback(
    async (taskId: string) => {
      try {
        const data = await fetchKanbanTask(taskId, { board: activeBoard });
        setSelectedTask(data.task);
        setSelectedTaskEvents(data.events ?? []);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load task";
        setError(message);
      }
    },
    [activeBoard],
  );

  const createTask = useCallback(
    async (input: CreateKanbanTaskInput) => {
      const data = await createKanbanTask({ ...input, board: activeBoard });
      await loadBoard({ silent: true });
      return data.task;
    },
    [activeBoard, loadBoard],
  );

  const updateTask = useCallback(
    async (taskId: string, updates: Record<string, unknown>) => {
      const data = await patchKanbanTask(taskId, updates, { board: activeBoard });
      setSelectedTask(data.task);
      await loadBoard({ silent: true });
      return data.task;
    },
    [activeBoard, loadBoard],
  );

  const moveTask = useCallback(
    async (taskId: string, status: string) => {
      await bulkUpdateKanbanTasks([taskId], { status }, { board: activeBoard });
      await loadBoard({ silent: true });
      if (selectedTask?.id === taskId) {
        setSelectedTask((prev) => (prev ? { ...prev, status } : prev));
        if (status !== "blocked") {
          void openTask(taskId);
        }
      }
    },
    [activeBoard, loadBoard, openTask, selectedTask?.id],
  );

  const archiveTask = useCallback(
    async (taskId: string) => {
      await archiveKanbanTasks([taskId], { board: activeBoard });
      setSelectedTask(null);
      setSelectedTaskEvents([]);
      await loadBoard({ silent: true });
    },
    [activeBoard, loadBoard],
  );

  const blockTask = useCallback(
    async (taskId: string, reason: string) => {
      const data = await blockKanbanTask(taskId, reason, { board: activeBoard });
      setSelectedTask(data.task);
      await loadBoard({ silent: true });
      await openTask(taskId);
    },
    [activeBoard, loadBoard, openTask],
  );

  const unblockTask = useCallback(
    async (taskId: string) => {
      const data = await unblockKanbanTask(taskId, { board: activeBoard });
      setSelectedTask(data.task);
      await loadBoard({ silent: true });
      await openTask(taskId);
    },
    [activeBoard, loadBoard, openTask],
  );

  const runDispatch = useCallback(
    async (opts?: { dryRun?: boolean }) => {
      const result = await dispatchKanban({
        board: activeBoard,
        dryRun: opts?.dryRun,
        max: 8,
      });
      await loadBoard({ silent: true });
      return result;
    },
    [activeBoard, loadBoard],
  );

  return {
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
  };
}
