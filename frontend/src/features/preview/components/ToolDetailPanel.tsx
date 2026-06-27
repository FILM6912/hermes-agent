import React from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { ProcessStep } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { TodosToolList } from "@/features/preview/components/TodosToolList";
import {
  JsonPrettyBlock,
  ToolPlainOutputView,
} from "@/features/preview/components/ToolPlainOutputView";
import { SkillViewToolPanel } from "@/features/preview/components/SkillViewToolPanel";
import {
  isTodosToolName,
  parseTodosFromToolPayload,
} from "@/features/preview/utils/parseTodosToolPayload";
import { stepUsesSkillViewPanel } from "@/features/preview/utils/parseSkillViewToolPayload";
import {
  parseStepInputOutput,
  tryParseJsonValue,
  TOOL_OUTPUT_COLLAPSE_CHARS,
} from "@/features/preview/utils/toolStepContent";

const ToolPayloadSection = ({
  label,
  raw,
  step,
  tone,
}: {
  label: string;
  raw: string;
  step: ProcessStep;
  tone: "input" | "output" | "error";
}) => {
  if (!raw.trim()) return null;
  const parsed = tryParseJsonValue(raw);
  const isTodosTool = isTodosToolName(step.toolName) || isTodosToolName(step.title);
  const todos = isTodosTool ? parseTodosFromToolPayload(parsed ?? raw) : null;

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
        {label}
      </div>
      {todos ? (
        <TodosToolList items={todos} />
      ) : parsed !== null ? (
        <JsonPrettyBlock value={parsed} tone={tone} />
      ) : (
        <ToolPlainOutputView
          text={raw}
          tone={tone}
          toolName={step.toolName ?? step.title}
          collapseAt={TOOL_OUTPUT_COLLAPSE_CHARS}
        />
      )}
    </div>
  );
};

export type ToolDetailPanelProps = {
  step: ProcessStep;
};

export const ToolDetailPanel: React.FC<ToolDetailPanelProps> = ({ step }) => {
  const { t } = useLanguage();
  if (stepUsesSkillViewPanel(step)) {
    return <SkillViewToolPanel step={step} />;
  }

  const isError = step.type === "error";
  const { inputContent, outputContent } = parseStepInputOutput(step.content);
  const title = step.title || step.toolName || t("process.toolExecution");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 pb-3 dark:border-zinc-800">
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{title}</span>
        {step.duration ? (
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">{step.duration}</span>
        ) : null}
        {step.status === "running" ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" aria-hidden />
        ) : step.status === "completed" && !isError ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
        ) : null}
        {isError ? (
          <span className="inline-flex items-center gap-1 rounded-md bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950/50 dark:text-red-300">
            <AlertCircle className="h-3 w-3" />
            {t("preview.toolError") || "Error"}
          </span>
        ) : null}
      </div>

      <ToolPayloadSection
        label={t("process.input")}
        raw={inputContent}
        step={step}
        tone="input"
      />
      <ToolPayloadSection
        label={t("process.output")}
        raw={outputContent}
        step={step}
        tone={isError ? "error" : "output"}
      />

      {!inputContent.trim() && !outputContent.trim() && step.content.trim() ? (
        <ToolPlainOutputView
          text={step.content.trim()}
          tone={isError ? "error" : "output"}
          toolName={step.toolName ?? step.title}
          collapseAt={TOOL_OUTPUT_COLLAPSE_CHARS}
        />
      ) : null}

      {!inputContent.trim() && !outputContent.trim() && !step.content.trim() ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {step.status === "running"
            ? t("preview.toolOutputPending") || "Waiting for tool result…"
            : t("chat.activityNoDetail") || "No additional details."}
        </p>
      ) : null}
    </div>
  );
};
