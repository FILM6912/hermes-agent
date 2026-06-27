import React, { useEffect, useRef, useState } from "react";
import { Brain, Loader2 } from "lucide-react";
import { ProcessStep } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";

interface ThinkingTraceProps {
  step: ProcessStep;
  isStreaming?: boolean;
  isLastStep?: boolean;
}

/** Collapsible reasoning/thinking trace from Hermes stream steps or legacy tags. */
export const ThinkingTrace: React.FC<ThinkingTraceProps> = ({
  step,
  isStreaming = false,
  isLastStep = false,
}) => {
  const { t } = useLanguage();
  const isRunning = step.status === "running" || (isStreaming && isLastStep);
  const [isOpen, setIsOpen] = useState(isRunning);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isRunning) {
      setIsOpen(true);
    } else if (!isLastStep) {
      setIsOpen(false);
    }
  }, [isRunning, isLastStep]);

  useEffect(() => {
    if (!isRunning || !isOpen) return;
    const el = contentRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [step.content, isRunning, isOpen]);

  const label =
    step.title === "Reasoning" || step.title === "Deep Thinking"
      ? t("chat.thoughtProcess") || "Thought Process"
      : step.title || t("chat.thoughtProcess") || "Thought Process";

  return (
    <div
      className={`think-details group/think ${isOpen ? "open" : ""} ${isRunning ? "streaming" : ""}`}
    >
      <button
        type="button"
        className="think-summary flex w-full items-center gap-2 px-0 py-1.5 cursor-pointer transition-colors text-[8px] font-medium text-zinc-500 select-none text-left hover:text-zinc-700 dark:hover:text-zinc-300"
        onClick={() => setIsOpen((open) => !open)}
      >
        <div className="flex items-center justify-center relative">
          {isRunning ? (
            <>
              <Brain className="w-3.5 h-3.5 text-blue-500 animate-pulse" />
              <Loader2 className="w-4 h-4 text-blue-400 absolute animate-spin opacity-40" />
            </>
          ) : (
            <Brain
              className={`w-3.5 h-3.5 shrink-0 transition-colors ${isOpen ? "text-blue-500" : "text-zinc-400"}`}
            />
          )}
        </div>
        <span className="flex-1 text-[11px]">{label}</span>
        {isRunning && <span className="opacity-50">...</span>}
        <svg
          className="think-chevron w-3 h-3 shrink-0 text-zinc-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <div className="think-content">
        <div ref={contentRef} className="think-content-inner max-h-[min(50vh,320px)] overflow-y-auto">
          <div className="pb-2 pt-0.5 text-xs text-zinc-600 dark:text-zinc-400 font-mono whitespace-pre-wrap leading-relaxed">
            {step.content}
            {isRunning && <span className="animate-pulse">▍</span>}
          </div>
        </div>
      </div>
    </div>
  );
};

interface LegacyThinkBlock {
  content: string;
  isComplete: boolean;
  label: string;
}

interface LegacyThinkingTraceProps {
  block: LegacyThinkBlock;
  isStreaming: boolean;
}

/** Legacy `<think>` / solution-tag blocks in assistant markdown. */
export const LegacyThinkingTrace: React.FC<LegacyThinkingTraceProps> = ({
  block,
  isStreaming,
}) => {
  const shouldBeOpenByStreaming = !block.isComplete && isStreaming;
  const [isOpen, setIsOpen] = useState(shouldBeOpenByStreaming);

  useEffect(() => {
    setIsOpen(shouldBeOpenByStreaming);
  }, [shouldBeOpenByStreaming]);

  return (
    <div
      className={`think-details group/think ${isOpen ? "open" : ""}`}
    >
      <button
        type="button"
        className="think-summary flex w-full items-center gap-2 px-0 py-1.5 cursor-pointer transition-colors text-[8px] font-medium text-zinc-500 select-none text-left hover:text-zinc-700 dark:hover:text-zinc-300"
        onClick={() => setIsOpen((open) => !open)}
      >
        <div className="flex items-center justify-center relative">
          {!block.isComplete && isStreaming ? (
            <>
              <Brain className="w-3.5 h-3.5 text-blue-500 animate-pulse" />
              <Loader2 className="w-4 h-4 text-blue-400 absolute animate-spin opacity-40" />
            </>
          ) : (
            <Brain className={`w-3.5 h-3.5 shrink-0 transition-colors ${isOpen ? "text-blue-500" : "text-zinc-400"}`} />
          )}
        </div>
        <span className="flex-1 text-[11px]">{block.label}</span>
        {!block.isComplete && isStreaming && <span className="opacity-50">...</span>}
        <svg
          className="think-chevron w-3 h-3 shrink-0 text-zinc-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <div className="think-content">
        <div className="think-content-inner">
          <div className="pb-2 pt-0.5 text-xs text-zinc-600 dark:text-zinc-400 font-mono whitespace-pre-wrap leading-relaxed">
            {block.content}
            {!block.isComplete && isStreaming && <span className="animate-pulse">_</span>}
          </div>
        </div>
      </div>
    </div>
  );
};
