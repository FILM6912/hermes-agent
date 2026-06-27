import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { ChatSession } from "@/types";
import type { HermesStreamChunk } from "@/services/hermes/streamChat";
import {
  createStreamChunkReduceState,
  reduceStreamChunk,
} from "@/services/hermes/reduceStreamChunk";
import type { PreviewPanelContentState } from "@/features/preview/previewPanelContent";
import { findLatestTodosInSteps } from "@/features/preview/previewPanelContent";
import type { ProcessStep } from "@/types";

function toolDetailStepChanged(prev: ProcessStep, next: ProcessStep): boolean {
  return (
    prev.content !== next.content ||
    prev.preview !== next.preview ||
    prev.status !== next.status ||
    prev.title !== next.title ||
    prev.toolName !== next.toolName ||
    prev.type !== next.type
  );
}

export type ConsumeHermesStreamDeps = {
  activeSessionId: string;
  assistantMsgId: string;
  targetMessageId?: string;
  initialAccumulatedContent?: string;
  stream: AsyncGenerator<HermesStreamChunk, void, unknown>;
  setSessions: Dispatch<SetStateAction<Record<string, ChatSession>>>;
  setIsLoading: (value: boolean) => void;
  isStreamingRef: MutableRefObject<boolean>;
  setIsStreaming: (value: boolean) => void;
  abortControllerRef: MutableRefObject<AbortController | null>;
  autoExpandSidebarOnTool: boolean;
  isPreviewOpen: boolean;
  isSettingsOpen: boolean;
  setIsPreviewOpen: (value: boolean) => void;
  setPreviewPanelContent?: (
    value: SetStateAction<PreviewPanelContentState>,
  ) => void;
  clearSessionStreamFlags?: (sessionId: string) => void;
};

/**
 * Apply SSE chunks to the active assistant message (shared by send + reattach).
 * Session mutations go through `reduceStreamChunk`; React-only side effects stay here.
 */
export async function consumeHermesStream(
  deps: ConsumeHermesStreamDeps,
): Promise<void> {
  const {
    activeSessionId,
    assistantMsgId,
    targetMessageId,
    initialAccumulatedContent = "",
    stream,
    setSessions,
    setIsLoading,
    isStreamingRef,
    setIsStreaming,
    abortControllerRef,
    autoExpandSidebarOnTool,
    isPreviewOpen,
    isSettingsOpen,
    setIsPreviewOpen,
    setPreviewPanelContent,
    clearSessionStreamFlags,
  } = deps;

  const reduceStateRef = {
    current: createStreamChunkReduceState(
      initialAccumulatedContent,
      targetMessageId,
    ),
  };
  let isFirstChunk = true;

  for await (const chunk of stream) {
    if (isFirstChunk) {
      setIsLoading(false);
      isFirstChunk = false;
    }

    if (chunk.type === "turn_end") {
      isStreamingRef.current = false;
      setIsStreaming(false);
      clearSessionStreamFlags?.(activeSessionId);
      continue;
    }

    if (chunk.type === "steps" && chunk.steps?.length) {
      const latestTodos = findLatestTodosInSteps(chunk.steps);
      if (latestTodos && setPreviewPanelContent) {
        // Refresh the todos list only when the user already opened the todos panel.
        // Do not auto-switch away from files/skill/tool views on TodoWrite updates.
        setPreviewPanelContent((prev) => {
          if (prev.mode !== "todos") return prev;
          return {
            mode: "todos",
            items:
              latestTodos.items.length > 0 ? latestTodos.items : prev.items,
            toolName:
              latestTodos.step.toolName ||
              latestTodos.step.title ||
              prev.toolName,
          };
        });
      } else {
        setPreviewPanelContent?.((prev) => {
          if (prev.mode === "tool-detail") {
            const updated = chunk.steps!.find((s) => s.id === prev.step.id);
            if (updated && toolDetailStepChanged(prev.step, updated)) {
              return { mode: "tool-detail", step: updated };
            }
          }
          return prev;
        });
        if (
          autoExpandSidebarOnTool &&
          !isPreviewOpen &&
          !isSettingsOpen
        ) {
          setIsPreviewOpen(true);
        }
      }
    }

    setSessions((prev) => {
      const session = prev[activeSessionId];
      if (!session) {
        if (!reduceStateRef.current.messageInitialized && !targetMessageId) {
          console.error(
            `Session ${activeSessionId} not found in first chunk handler`,
          );
        } else if (
          (chunk.type === "text" && chunk.content) ||
          chunk.type === "steps"
        ) {
          console.warn(
            `[Stream Update] Session ${activeSessionId} vanished during streaming.`,
          );
        }
        return prev;
      }

      const { session: nextSession, state } = reduceStreamChunk(
        session,
        chunk,
        { assistantMsgId, targetMessageId },
        reduceStateRef.current,
      );
      reduceStateRef.current = state;
      return {
        ...prev,
        [activeSessionId]: nextSession,
      };
    });
  }

  isStreamingRef.current = false;
  setIsStreaming(false);
  abortControllerRef.current = null;
}
