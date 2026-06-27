import type { ProcessStep } from "@/types";
import {
  isTodosToolName,
  parseTodosFromToolPayload,
  type TodoItem,
} from "@/features/preview/utils/parseTodosToolPayload";
import { parseStepInputOutput } from "@/features/preview/utils/toolStepContent";

export type PreviewPanelContentMode = "files" | "todos" | "tool-detail";

export type PreviewPanelContentState =
  | { mode: "files" }
  | { mode: "todos"; items: TodoItem[]; toolName?: string }
  | { mode: "tool-detail"; step: ProcessStep };

export const FILES_PANEL_CONTENT: PreviewPanelContentState = { mode: "files" };

/** Parse todos from a tool step's input/output payload. */
export function extractTodosFromStep(step: ProcessStep): TodoItem[] | null {
  const isTodos =
    isTodosToolName(step.toolName) || isTodosToolName(step.title);
  if (!isTodos) return null;

  const { inputContent, outputContent } = parseStepInputOutput(step.content);

  for (const raw of [
    step.preview,
    inputContent,
    outputContent,
    step.content,
  ]) {
    if (!raw?.trim()) continue;
    const items = parseTodosFromToolPayload(raw);
    if (items?.length) return items;
  }
  return [];
}

export function findLatestTodosStep(steps: ProcessStep[]): ProcessStep | null {
  for (let i = steps.length - 1; i >= 0; i--) {
    const step = steps[i];
    if (isTodosToolName(step.toolName) || isTodosToolName(step.title)) {
      return step;
    }
  }
  return null;
}

export type LatestTodosFromSteps = {
  items: TodoItem[];
  step: ProcessStep;
};

/** Merge todo items from every Todo/todos tool step (last write per id wins). */
export function collectTodosFromSteps(steps: ProcessStep[]): TodoItem[] {
  const byId = new Map<string, TodoItem>();
  for (const step of steps) {
    if (!isTodosToolName(step.toolName) && !isTodosToolName(step.title)) {
      continue;
    }
    const items = extractTodosFromStep(step);
    if (!items?.length) continue;
    for (const item of items) {
      byId.set(item.id, item);
    }
  }
  return [...byId.values()];
}

/** Latest todos tool step from a chunk (last todos tool wins). */
export function findLatestTodosInSteps(
  steps: ProcessStep[],
): LatestTodosFromSteps | null {
  const step = findLatestTodosStep(steps);
  if (!step) return null;
  const merged = collectTodosFromSteps(steps);
  return {
    step,
    items: merged.length > 0 ? merged : extractTodosFromStep(step) ?? [],
  };
}

export function resolvePreviewPanelContentForStep(
  step: ProcessStep,
): PreviewPanelContentState {
  if (isTodosToolName(step.toolName) || isTodosToolName(step.title)) {
    return {
      mode: "todos",
      items: extractTodosFromStep(step) ?? [],
      toolName: step.toolName || step.title,
    };
  }
  return { mode: "tool-detail", step };
}
