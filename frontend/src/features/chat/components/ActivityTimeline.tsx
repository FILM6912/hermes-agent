import React from "react";
import { createPortal } from "react-dom";
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileCode2,
  Loader2,
  Presentation,
  Search,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import type { ProcessStep } from "@/types";
import {
  activityIconKind,
  activityStepTitle,
  activityTimelineShowsDone,
  buildActivitySummary,
  shouldUseActivityTimeline,
  stepsToActivityRows,
  thinkingStepsOnly,
  type ActivityIconKind,
  type ActivityRow,
} from "../utils/activityTimeline";
import { ThinkingTrace } from "./ThinkingTrace";

export type ActivityTimelineProps = {
  steps: ProcessStep[];
  isStreaming?: boolean;
  defaultCollapsed?: boolean;
  /** grouped = collapsible timeline (legacy parity); inline = compact list (deprecated) */
  variant?: "grouped" | "inline";
  /** When false, omit the terminal "Done" row (used for reasoning-only timelines). */
  showDoneStep?: boolean;
  /** Open tool detail or todos in the workspace preview panel. */
  onOpenToolInPanel?: (step: ProcessStep) => void;
};

type ActivityDetailModalProps = {
  row: Extract<ActivityRow, { kind: "tool" | "thinking" }>;
  onClose: () => void;
};

const ActivityDetailModal: React.FC<ActivityDetailModalProps> = ({ row, onClose }) => {
  const { t } = useLanguage();

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const body =
    row.kind === "tool"
      ? row.expandContent?.trim() ||
        row.detail?.trim() ||
        row.fileName ||
        ""
      : row.expandContent?.trim() || row.detail?.trim() || "";

  const parsedBody = React.useMemo(() => {
    if (!body) return { summary: "", inputJson: "" };
    const inputMatch = body.match(/Input:\s*```json\s*([\s\S]*?)\s*```/i);
    const summary = inputMatch ? body.slice(0, inputMatch.index).trim() : body.trim();
    const inputJson = inputMatch?.[1]?.trim() ?? "";
    return { summary, inputJson };
  }, [body]);

  const prettyJson = (value: string): string => {
    const text = value.trim();
    if (!text) return "";
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[9998] flex items-center justify-center p-4 animate-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="activity-detail-title"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[min(80vh,640px)] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-[#18181b] animate-modal-content"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h3
            id="activity-detail-title"
            className="text-sm font-semibold text-zinc-900 dark:text-zinc-100"
          >
            {row.kind === "thinking"
              ? t("chat.thoughtProcess") || row.label
              : activityStepTitle(row)}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            aria-label={t("common.close") || "Close"}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {row.kind === "tool" && row.fileName ? (
            <code className="mb-3 inline-flex max-w-full truncate rounded bg-zinc-100 px-2 py-1 font-mono text-[11px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
              {row.fileName}
            </code>
          ) : null}
          {body ? (
            <div className="space-y-3">
              {row.kind === "thinking" ? (
                <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">
                  {body}
                </pre>
              ) : (
                <>
                  {parsedBody.summary ? (
                    <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/40">
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                        Result
                      </p>
                      <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">
                        {prettyJson(parsedBody.summary)}
                      </pre>
                    </div>
                  ) : null}
                  {parsedBody.inputJson ? (
                    <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-[#111113]">
                      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                        Input
                      </p>
                      <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">
                        {prettyJson(parsedBody.inputJson)}
                      </pre>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {t("chat.activityNoDetail") || "No additional details."}
            </p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
};

const StepIcon: React.FC<{ kind: ActivityIconKind; fileName?: string; running?: boolean }> = ({
  kind,
  fileName: _fileName,
  running = false,
}) => {
  const iconClass = "h-4 w-4 text-zinc-500 dark:text-zinc-400";

  if (running) {
    return <Loader2 className={`${iconClass} animate-spin`} />;
  }

  if (kind === "file") {
    return (
      <span className="inline-flex min-w-0 items-center gap-1 rounded bg-zinc-100 px-1 py-0.5 dark:bg-zinc-800/80">
        <FileCode2 className={iconClass} />
      </span>
    );
  }

  if (kind === "present") {
    return <Presentation className={iconClass} />;
  }
  if (kind === "command") {
    return <Terminal className={iconClass} />;
  }
  if (kind === "search") {
    return <Search className={iconClass} />;
  }
  return <Wrench className={iconClass} />;
};

/** Full reasoning body — stream the complete text, not a clamped preview. */
const ThinkingStreamBody: React.FC<{
  row: Extract<ActivityRow, { kind: "thinking" }>;
  isStreaming?: boolean;
}> = ({ row, isStreaming = false }) => {
  const { t } = useLanguage();
  const contentRef = React.useRef<HTMLDivElement>(null);
  const running = row.status === "running" || isStreaming;
  const fullContent = row.expandContent?.trim() || row.detail?.trim() || "";

  React.useEffect(() => {
    if (!running) return;
    const el = contentRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [fullContent, running]);

  if (running && !fullContent) {
    return (
      <div className="flex items-center gap-2 py-1 pl-[26px] text-xs text-zinc-500 dark:text-zinc-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
        <span>{t("chat.thinking") || "Thinking…"}</span>
      </div>
    );
  }

  if (!fullContent) return null;

  return (
    <div
      ref={contentRef}
      className="max-h-[min(50vh,320px)] overflow-y-auto py-1 pl-[26px] pr-1"
    >
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
        {fullContent}
        {running ? <span className="animate-pulse">▍</span> : null}
      </pre>
    </div>
  );
};

const ThinkingTimelineStep: React.FC<{
  row: Extract<ActivityRow, { kind: "thinking" }>;
  isLast: boolean;
  title: string;
  /** Omit row heading when it would repeat the group summary. */
  hideTitle?: boolean;
  isStreaming?: boolean;
}> = ({ row, isLast, title, hideTitle = false, isStreaming = false }) => {
  const [open, setOpen] = React.useState(false);
  const running = row.status === "running" || isStreaming;
  const hasDetail = Boolean(row.expandContent?.trim());
  const showTitle = !hideTitle && Boolean(title.trim());
  const showInlineStream = running || hasDetail;

  if (showInlineStream && (running || row.expandContent?.trim())) {
    return (
      <div className={`relative pb-3 ${isLast ? "pb-0" : ""}`}>
        {!isLast ? (
          <span
            aria-hidden
            className="absolute left-[8px] top-[22px] bottom-0 w-px bg-zinc-300/80 dark:bg-zinc-700/80"
          />
        ) : null}
        {showTitle ? (
          <div className="mb-1 flex gap-2.5">
            <span className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center">
              {running ? (
                <Loader2 className="h-4 w-4 animate-spin text-zinc-500 dark:text-zinc-400" />
              ) : (
                <Brain className="h-4 w-4 text-purple-500/90 dark:text-purple-400/90" />
              )}
            </span>
            <div className="min-w-0 flex-1 text-xs font-semibold leading-snug text-zinc-700 dark:text-zinc-300">
              {title}
            </div>
          </div>
        ) : null}
        <ThinkingStreamBody row={row} isStreaming={isStreaming} />
      </div>
    );
  }

  return (
    <>
      <div className={`relative flex gap-2.5 pb-3 ${isLast ? "pb-0" : ""}`}>
        {!isLast ? (
          <span
            aria-hidden
            className="absolute left-[8px] top-[22px] bottom-0 w-px bg-zinc-300/80 dark:bg-zinc-700/80"
          />
        ) : null}
        <span className="relative z-[1] mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center">
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin text-zinc-500 dark:text-zinc-400" />
          ) : (
            <Brain className="h-4 w-4 text-purple-500/90 dark:text-purple-400/90" />
          )}
        </span>
        <button
          type="button"
          disabled={!hasDetail && !running}
          onClick={() => hasDetail && setOpen(true)}
          className="group min-w-0 flex-1 text-left disabled:cursor-default"
        >
          {showTitle ? (
            <div
              className={`text-xs font-semibold leading-snug ${
                running
                  ? "text-zinc-500 dark:text-zinc-400"
                  : hasDetail
                    ? "text-zinc-800 group-hover:text-[#1447E6] dark:text-zinc-200 dark:group-hover:text-blue-400"
                    : "text-zinc-700 dark:text-zinc-300"
              }`}
            >
              {title}
            </div>
          ) : null}
          {row.detail ? (
            <div
              className={`truncate text-[10px] text-zinc-500 dark:text-zinc-500 ${
                showTitle ? "mt-0.5" : "text-xs leading-relaxed"
              }`}
            >
              {row.detail}
            </div>
          ) : null}
        </button>
      </div>
      {open && hasDetail ? (
        <ActivityDetailModal row={row} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
};

const TimelineStep: React.FC<{
  row: Extract<ActivityRow, { kind: "tool" }>;
  isLast: boolean;
  step?: ProcessStep;
  onOpenToolInPanel?: (step: ProcessStep) => void;
}> = ({ row, isLast, step, onOpenToolInPanel }) => {
  const [open, setOpen] = React.useState(false);
  const running = row.status === "running";
  const title = activityStepTitle(row);
  const kind = activityIconKind(row.toolName);
  const hasDetail = Boolean(
    row.expandContent?.trim() || row.detail?.trim() || row.fileName,
  );
  const usePreviewPanel = Boolean(onOpenToolInPanel && step && hasDetail);

  const handleClick = () => {
    if (usePreviewPanel && step && onOpenToolInPanel) {
      onOpenToolInPanel(step);
      return;
    }
    if (hasDetail) setOpen(true);
  };

  return (
    <>
      <div className={`relative flex gap-2.5 pb-3 ${isLast ? "pb-0" : ""}`}>
        {!isLast ? (
          <span
            aria-hidden
            className="absolute left-[8px] top-[22px] bottom-0 w-px bg-zinc-300/80 dark:bg-zinc-700/80"
          />
        ) : null}
        <span className="relative z-[1] mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center">
          <StepIcon kind={kind} fileName={row.fileName} running={running} />
        </span>
        <button
          type="button"
          disabled={!hasDetail && !running}
          onClick={handleClick}
          className="group min-w-0 flex-1 text-left disabled:cursor-default"
        >
          <div
            className={`text-xs font-semibold leading-snug ${
              running
                ? "text-zinc-500 dark:text-zinc-400"
                : hasDetail
                  ? "text-zinc-800 group-hover:text-[#1447E6] dark:text-zinc-200 dark:group-hover:text-blue-400"
                  : "text-zinc-700 dark:text-zinc-300"
            }`}
          >
            {title}
          </div>
        </button>
      </div>
      {open && hasDetail && !usePreviewPanel ? (
        <ActivityDetailModal row={row} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
};

const DoneStep: React.FC = () => {
  const { t } = useLanguage();
  return (
    <div className="relative flex gap-2.5">
      <span className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center">
        <CheckCircle2 className="h-4 w-4 text-emerald-500/90 dark:text-emerald-400/90" />
      </span>
      <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
        {t("chat.activityDone") || "Done"}
      </span>
    </div>
  );
};

export const ActivityTimeline: React.FC<ActivityTimelineProps> = ({
  steps,
  isStreaming = false,
  defaultCollapsed = true,
  variant: _variant = "grouped",
  showDoneStep,
  onOpenToolInPanel,
}) => {
  const { t } = useLanguage();
  const rows = React.useMemo(() => stepsToActivityRows(steps), [steps]);
  const stepById = React.useMemo(
    () => new Map(steps.map((step) => [step.id, step])),
    [steps],
  );
  const summary = React.useMemo(() => buildActivitySummary(steps), [steps]);
  const hasRunning = steps.some((s) => s.status === "running");
  const [collapsed, setCollapsed] = React.useState(defaultCollapsed);

  React.useEffect(() => {
    if (isStreaming && hasRunning) {
      setCollapsed(false);
    }
  }, [hasRunning, isStreaming]);

  if (rows.length === 0) return null;

  const thinkingRows = rows.filter(
    (r): r is Extract<ActivityRow, { kind: "thinking" }> => r.kind === "thinking",
  );
  const toolRows = rows.filter(
    (r): r is Extract<ActivityRow, { kind: "tool" }> => r.kind === "tool",
  );

  const summaryLabel =
    summary ||
    (thinkingRows.length > 0 && toolRows.length === 0
      ? t("chat.thoughtProcess") || "Thought Process"
      : t("chat.activity") || "Activity");

  const reasoningOnlySingleton =
    thinkingRows.length === 1 && toolRows.length === 0;

  const allowDone =
    showDoneStep ?? activityTimelineShowsDone(steps);
  const showDone =
    allowDone &&
    !hasRunning &&
    !isStreaming &&
    toolRows.length > 0 &&
    toolRows.every(
      (r) => r.status === "completed" || r.status === "cancelled",
    );

  if (reasoningOnlySingleton) {
    const step = thinkingStepsOnly(steps)[0];
    if (!step) return null;
    return (
      <ThinkingTrace
        step={step}
        isStreaming={hasRunning && isStreaming}
        isLastStep
      />
    );
  }

  return (
    <div
      className={`tool-call-group my-3 w-full max-w-full rounded-lg ${
        hasRunning && isStreaming ? "activity-live" : ""
      }`}
    >
      <button
        type="button"
        className="tool-call-group-summary flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left text-xs text-zinc-500 transition-colors hover:bg-zinc-100/60 dark:text-zinc-400 dark:hover:bg-zinc-800/40"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="opacity-70">
          {collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </span>
        <span
          className={`truncate font-semibold text-zinc-600 dark:text-zinc-300 ${
            hasRunning && isStreaming ? "activity-sweep-label" : ""
          }`}
        >
          {summaryLabel}
        </span>
        {hasRunning && isStreaming ? (
          <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin opacity-70" />
        ) : null}
      </button>
      {!collapsed && (
        <div className="tool-call-group-body px-1 pb-1 pt-1">
          <div className="pl-0.5">
            {thinkingRows.map((row, index) => {
                const running = row.status === "running";
                const title = running
                  ? t("chat.thinking") || row.label
                  : row.detail || row.label;
                const isLastRow =
                  index === thinkingRows.length - 1 &&
                  toolRows.length === 0 &&
                  !showDone;
                return (
                  <ThinkingTimelineStep
                    key={row.id}
                    row={row}
                    title={title}
                    hideTitle={!running && Boolean(row.detail)}
                    isLast={isLastRow}
                    isStreaming={hasRunning && isStreaming}
                  />
                );
              })}
            {toolRows.map((row, index) => (
              <TimelineStep
                key={row.id}
                row={row}
                step={stepById.get(row.id)}
                onOpenToolInPanel={onOpenToolInPanel}
                isLast={index === toolRows.length - 1 && !showDone}
              />
            ))}
            {showDone ? <DoneStep /> : null}
          </div>
        </div>
      )}
      <style>{`
        @keyframes activity-label-sweep {
          0% { background-position: 100% 0; }
          100% { background-position: -100% 0; }
        }
        .activity-sweep-label {
          background: linear-gradient(
            90deg,
            rgb(113 113 122) 0%,
            rgb(113 113 122) 40%,
            rgb(59 130 246) 50%,
            rgb(113 113 122) 60%,
            rgb(113 113 122) 100%
          );
          background-size: 200% 100%;
          -webkit-background-clip: text;
          background-clip: text;
          color: transparent;
          animation: activity-label-sweep 2.2s ease-in-out infinite;
        }
        :is(.dark) .activity-sweep-label {
          background: linear-gradient(
            90deg,
            rgb(161 161 170) 0%,
            rgb(161 161 170) 40%,
            rgb(96 165 250) 50%,
            rgb(161 161 170) 60%,
            rgb(161 161 170) 100%
          );
          background-size: 200% 100%;
          -webkit-background-clip: text;
          background-clip: text;
        }
      `}</style>
    </div>
  );
};

export { shouldUseActivityTimeline };
