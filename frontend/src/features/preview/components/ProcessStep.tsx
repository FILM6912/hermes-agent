import React, { useState, useEffect, useRef } from "react";
import {
  ChevronDown,
  ChevronRight,

  Brain,
  FileEdit,
  CheckCircle2,
  Loader2,
  Wrench,
  ListTodo,
} from "lucide-react";
import { ProcessStep as ProcessStepType } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { TodosToolList } from "@/features/preview/components/TodosToolList";
import {
  JsonPrettyBlock,
  ToolPlainOutputView,
} from "@/features/preview/components/ToolPlainOutputView";
import {
  isTodosToolName,
  parseTodosFromToolPayload,
} from "@/features/preview/utils/parseTodosToolPayload";
import { extractTodosFromStep } from "@/features/preview/previewPanelContent";
import {
  parseStepInputOutput,
  tryParseJsonValue,
  TOOL_OUTPUT_COLLAPSE_CHARS,
} from "@/features/preview/utils/toolStepContent";

interface ProcessStepProps {
  step: ProcessStepType;
  forceExpanded?: boolean;
  isLastStep?: boolean;
  onOpenInPanel?: (step: ProcessStepType) => void;
  embedded?: boolean;
}

export const ProcessStep: React.FC<ProcessStepProps> = ({
  step,
  forceExpanded = false,
  isLastStep = false,
  onOpenInPanel,
  embedded = false,
}) => {
  const { t } = useLanguage();
  const isTodosTool =
    isTodosToolName(step.toolName) || isTodosToolName(step.title);
  const panelNavigate = Boolean(onOpenInPanel && isTodosTool);
  const [expanded, setExpanded] = useState(() => {
    if (forceExpanded || embedded) return true;
    if (panelNavigate) return false;
    if (step.type === "thinking") {
      return true;
    }
    return step.isExpanded ?? false;
  });

  const wasLastStepRef = useRef(isLastStep);

  useEffect(() => {
    if (forceExpanded || embedded) return;
    if (step.type === "thinking") {
      if (wasLastStepRef.current && !isLastStep) {
        setExpanded(false);
      }
      wasLastStepRef.current = isLastStep;
    }
  }, [isLastStep, step.type, forceExpanded, embedded]);

  const todosSummary = React.useMemo(() => {
    if (!panelNavigate) return null;
    const items = extractTodosFromStep(step);
    if (!items?.length) return null;
    const done = items.filter((i) => i.status === "completed").length;
    const inProgress = items.filter((i) => i.status === "in_progress").length;
    return { total: items.length, done, inProgress };
  }, [panelNavigate, step.content]);

  const handleHeaderClick = () => {
    if (panelNavigate && onOpenInPanel) {
      onOpenInPanel(step);
      return;
    }
    if (!embedded) setExpanded(!expanded);
  };

  const getIcon = () => {
    if (isTodosToolName(step.toolName) || isTodosToolName(step.title)) {
      return <ListTodo className="w-4 h-4 text-amber-600 dark:text-amber-400" />;
    }
    switch (step.type) {
      case "thinking":
        return (
          <Brain className="w-4 h-4 text-purple-500 dark:text-purple-400" />
        );
      case "command":
        return (
          <Wrench className="w-4 h-4 text-indigo-500 dark:text-indigo-400" />
        );
      case "edit":
        return (
          <FileEdit className="w-4 h-4 text-blue-500 dark:text-blue-400" />
        );
      case "error":
        return <div className="w-2 h-2 rounded-full bg-red-500" />;
      default:
        return <Wrench className="w-4 h-4 text-zinc-400" />;
    }
  };

  const getTitle = () => {
    if (step.title === "Deep Thinking" || step.type === "thinking")
      return t("process.thinking");
    if (step.title === "Reasoning") return t("process.thinking");

    if (step.title) return step.title;

    switch (step.type) {
      case "command":
        return t("process.toolExecution");
      case "edit":
        return t("process.edit");
      default:
        return t("process.default");
    }
  };

  const getContent = () => {
    if (step.content.includes("Analyzing technical requirements"))
      return t("process.analyzing") + "...";
    if (step.content.includes("Deconstructing the problem"))
      return t("process.deconstructing") + "...";
    return step.content;
  };



  return (
    <div
      className={
        embedded
          ? "process-step-embedded"
          : `process-step mb-2 last:mb-0 rounded-xl bg-zinc-100 dark:bg-[#0c0c0e] overflow-hidden group transition-all duration-200 border border-zinc-300 dark:border-white/10 shadow-sm ${expanded ? "process-step-open" : ""}`
      }
    >
      {!embedded ? (
      <div
        className="flex items-center gap-3 p-3 min-h-[44px] cursor-pointer select-none"
        onClick={handleHeaderClick}
      >
        <div className="flex items-center justify-center w-4 h-4 text-zinc-500 dark:text-zinc-600 group-hover:text-zinc-800 dark:group-hover:text-zinc-400 transition-colors process-step-chevron">
          {!forceExpanded && !panelNavigate && (
            expanded ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )
          )}
        </div>

        <div className="flex items-center gap-3 flex-1 overflow-hidden min-w-0">
          <div className="shrink-0 flex items-center justify-center">
            {getIcon()}
          </div>

          <span
            className="text-sm font-medium whitespace-nowrap shrink-0 text-zinc-800 dark:text-zinc-200"
          >
            {getTitle()}
          </span>
          {todosSummary ? (
            <span className="truncate text-xs text-zinc-500 dark:text-zinc-400">
              {todosSummary.total} {t("preview.todosCount")}
              {todosSummary.inProgress > 0
                ? ` · ${todosSummary.inProgress} ${t("preview.todosInProgress")}`
                : ""}
              {todosSummary.done > 0
                ? ` · ${todosSummary.done} ${t("preview.todosDone")}`
                : ""}
            </span>
          ) : null}
        </div>

          <div className="flex items-center gap-3 pl-2 shrink-0">
          {step.duration && (
            <span className="text-xs font-mono text-zinc-400 dark:text-zinc-500">
              {step.duration}
            </span>
          )}
          {step.status === "running" ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-400 dark:text-zinc-500" />
          ) : step.status === "completed" ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          ) : null}
        </div>
      </div>
      ) : null}

      {(embedded || expanded) && (
      <div className="process-step-content">
        <div className={embedded ? "px-1 pb-1" : "pl-10 pr-4 pb-3"}>
          {step.type === "thinking" && (
            <div className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed animate-in fade-in slide-in-from-top-1 duration-200 border-l-2 border-zinc-200 dark:border-zinc-800 pl-4 py-1">
              {getContent()}
            </div>
          )}

          {step.type === "command" && (
            <div className="mt-1 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
              {/* Parse and display content in Input/Output format */}
              {(() => {
                const { inputContent, outputContent } = parseStepInputOutput(step.content);
                const toolLabel = step.toolName ?? step.title;

                const renderPayload = (
                  raw: string,
                  tone: "input" | "output",
                ) => {
                  const parsed = tryParseJsonValue(raw);
                  const isTodosTool =
                    isTodosToolName(step.toolName) || isTodosToolName(step.title);
                  const todos = isTodosTool
                    ? parseTodosFromToolPayload(parsed ?? raw)
                    : null;
                  if (todos) return <TodosToolList items={todos} />;
                  if (parsed !== null) {
                    return <JsonPrettyBlock value={parsed} tone={tone} />;
                  }
                  return (
                    <ToolPlainOutputView
                      text={raw}
                      tone={tone}
                      toolName={toolLabel}
                      collapseAt={TOOL_OUTPUT_COLLAPSE_CHARS}
                    />
                  );
                };

                return (
                  <>
                    {inputContent ? (
                      <div className="space-y-1.5">
                        <div className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                          Input
                        </div>
                        {renderPayload(inputContent, "input")}
                      </div>
                    ) : null}
                    {outputContent ? (
                      <div className="space-y-1.5">
                        <div className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                          Output
                        </div>
                        {renderPayload(outputContent, "output")}
                      </div>
                    ) : null}
                  </>
                );
              })()}
            </div>
          )}

          {step.type !== "thinking" && step.type !== "command" && (
            <div className="text-xs font-mono text-zinc-600 dark:text-zinc-500 bg-zinc-100 dark:bg-zinc-900/30 p-2 rounded break-all whitespace-pre-wrap animate-in fade-in slide-in-from-top-1 duration-200">
              {step.content}
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
};
