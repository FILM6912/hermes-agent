import React, { useState, useEffect, useRef } from "react";
import {
  Brain,
  FileEdit,
  CheckCircle2,
  Loader2,
  Command,
  Wrench,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { ProcessStep as ProcessStepType } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { TodosToolList } from "@/features/preview/components/TodosToolList";
import {
  isTodosToolName,
  parseTodosFromToolPayload,
  stripJsonFences,
} from "@/features/preview/utils/parseTodosToolPayload";

interface ProcessStepCardProps {
  step: ProcessStepType;
  isLastStep?: boolean;
}

export const ProcessStepCard: React.FC<ProcessStepCardProps> = ({ step, isLastStep = false }) => {
  const { t } = useLanguage();
  const [expanded, setExpanded] = useState(() => {
    if (step.type === "thinking") {
      return true;
    }
    return step.isExpanded ?? false;
  });

  const wasLastStepRef = useRef(isLastStep);

  useEffect(() => {
    if (step.type === "thinking") {
      if (wasLastStepRef.current && !isLastStep) {
        setExpanded(false);
      }
      wasLastStepRef.current = isLastStep;
    }
  }, [isLastStep, step.type]);

  const getIcon = () => {
    switch (step.type) {
      case "thinking":
        return (
          <div className="relative">
            <div className="absolute inset-0 bg-purple-500/20 blur-lg rounded-full" />
            <Brain className="w-5 h-5 text-purple-500 dark:text-purple-400 relative z-10" />
          </div>
        );
      case "command":
        return (
          <div className="relative">
            <div className="absolute inset-0 bg-indigo-500/20 blur-lg rounded-full" />
            <Wrench className="w-5 h-5 text-indigo-500 dark:text-indigo-400 relative z-10" />
          </div>
        );
      case "edit":
        return (
          <div className="relative">
            <div className="absolute inset-0 bg-blue-500/20 blur-lg rounded-full" />
            <FileEdit className="w-5 h-5 text-blue-500 dark:text-blue-400 relative z-10" />
          </div>
        );
      default:
        return <Command className="w-5 h-5 text-zinc-400" />;
    }
  };

  const getTitle = () => {
    if (step.title === "Deep Thinking" || step.type === "thinking")
      return t("process.thinking") || "Thinking";
    if (step.title === "Reasoning") return t("process.thinking") || "Thinking";
    
    // Priority: use the specific title (e.g., tool name) if it exists
    if (step.title) return step.title;

    switch (step.type) {
      case "command":
        return t("process.toolExecution") || "Tool Execution";
      case "edit":
        return t("process.edit") || "Edit File";
      default:
        return t("process.default") || "Process Step";
    }
  };

  const parseContent = () => {
    const lines = step.content.split("\n");
    const inputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "input:");
    const outputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "output:");

    let inputContent = "";
    let outputContent = "";

    if (inputIndex !== -1) {
      const inputEnd = outputIndex !== -1 ? outputIndex : lines.length;
      inputContent = lines.slice(inputIndex + 1, inputEnd).join("\n").trim();
      inputContent = inputContent.replace(/```(json|typescript|javascript)?\n?/g, "").replace(/```\n?/g, "").trim();
    }

    if (outputIndex !== -1) {
      outputContent = lines.slice(outputIndex + 1).join("\n").trim();
    }

    // Fallback if no Input/Output headers
    if (inputIndex === -1 && outputIndex === -1 && step.type !== "thinking") {
      outputContent = step.content;
    }

    return { inputContent, outputContent };
  };

  const { inputContent, outputContent } = parseContent();

  return (
    <div className="group relative border-b border-white/5 last:border-0 transition-all duration-300 hover:bg-white/1">
      <div className="py-6 px-4">
        {/* Header */}
        <div 
          className="flex items-center justify-between mb-4 cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-3">
            <div className="text-zinc-500">
              {expanded ? (
                <ChevronDown className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
            </div>
            {getIcon()}
            <div className="flex flex-col">
              <span className="text-sm font-semibold text-zinc-100 dark:text-zinc-100 tracking-tight">
                {getTitle()}
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            {step.duration && (
              <span className="text-sm font-mono text-zinc-500">
                {step.duration}
              </span>
            )}
            {step.status === "running" ? (
              <Loader2 className="w-5 h-5 animate-spin text-indigo-500" />
            ) : step.status === "completed" ? (
              <div className="flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              </div>
            ) : null}
          </div>
        </div>

        {/* Content */}
        {expanded && (
        <div className="space-y-6 ml-7">
          {step.type === "thinking" ? (
            <div className="text-sm text-zinc-400 leading-relaxed font-medium">
              {step.content}
            </div>
          ) : (
            <>
              {inputContent && (
                <div className="space-y-3">
                  <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-[0.2em] mb-2">
                    {t("process.input")}
                  </div>
                  {(() => {
                    const raw = stripJsonFences(inputContent);
                    let parsed: unknown = null;
                    try {
                      parsed = JSON.parse(raw);
                    } catch {
                      parsed = null;
                    }
                    const isTodosTool =
                      isTodosToolName(step.toolName) || isTodosToolName(step.title);
                    const todos = isTodosTool
                      ? parseTodosFromToolPayload(parsed ?? inputContent)
                      : null;
                    if (todos) return <TodosToolList items={todos} />;
                    return (
                      <div className="bg-[#141416]/50 rounded-xl p-3 border border-white/5 overflow-hidden">
                        <pre className="text-[11px] font-mono text-zinc-400 whitespace-pre-wrap break-words">
                          {parsed !== null ? JSON.stringify(parsed, null, 2) : inputContent}
                        </pre>
                      </div>
                    );
                  })()}
                </div>
              )}

              {outputContent && (
                <div className="space-y-3">
                  <div className="text-[9px] font-bold text-zinc-500 uppercase tracking-[0.2em] mb-2">
                    {t("process.output")}
                  </div>
                  <div className="bg-emerald-500/2 rounded-xl p-3 border border-emerald-500/5 overflow-hidden">
                    <div className="text-[13px] text-zinc-300 prose prose-invert prose-sm max-w-none break-words overflow-wrap-anywhere">
                      <Markdown 
                        remarkPlugins={[remarkGfm]}
                        components={{
                          strong: ({ children }) => (
                            <strong className="font-bold">
                              {children}
                            </strong>
                          ),
                          p: ({ children }) => (
                            <p className="break-words overflow-wrap-anywhere leading-relaxed mb-3 last:mb-0">{children}</p>
                          ),
                          pre: ({ children }) => (
                             <pre className="whitespace-pre-wrap break-all overflow-wrap-anywhere text-xs my-2 p-2 rounded bg-black/20 overflow-hidden">{children}</pre>
                          ),
                          code: ({ children, className }) => {
                             const isInline = !className;
                             return isInline ? (
                               <code className="bg-black/10 dark:bg-black/20 px-1 py-0.5 rounded font-mono text-xs break-all overflow-wrap-anywhere border border-black/5 dark:border-white/5">{children}</code>
                             ) : (
                               <code className={`${className} break-all whitespace-pre-wrap overflow-wrap-anywhere`}>{children}</code>
                             );
                          }
                        }}
                      >
                        {outputContent}
                      </Markdown>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
        )}
      </div>
    </div>
  );
};
