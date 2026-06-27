import React, { useEffect, useRef, useState } from "react";
import { useLanguage } from "@/hooks/useLanguage";
import {
  CONTEXT_RING_CIRCUMFERENCE,
  computeContextUsageDisplay,
  type SessionContextUsage,
} from "@/features/chat/utils/contextUsage";

type ContextUsageIndicatorProps = {
  usage?: SessionContextUsage;
  onCompressHint?: () => void;
};

export const ContextUsageIndicator: React.FC<ContextUsageIndicatorProps> = ({
  usage,
  onCompressHint,
}) => {
  const { t } = useLanguage();
  const [tooltipOpen, setTooltipOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const display = computeContextUsageDisplay(usage, t);

  useEffect(() => {
    if (!tooltipOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setTooltipOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [tooltipOpen]);

  if (!display.visible) return null;

  const ringOffset = CONTEXT_RING_CIRCUMFERENCE * (1 - display.pct / 100);
  const ringStrokeClass =
    display.level === "high"
      ? "stroke-red-500"
      : display.level === "mid"
        ? "stroke-amber-500"
        : "stroke-zinc-400 dark:stroke-zinc-500";

  const compressLabel =
    display.compressHint === "action"
      ? t("chat.contextUsageCompressAction")
      : display.compressHint === "hint"
        ? t("chat.contextUsageCompressHint")
        : "";

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        type="button"
        className="relative flex h-6 w-6 items-center justify-center rounded-full text-zinc-500 transition-colors hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
        aria-label={display.label}
        aria-describedby="ctx-usage-tooltip"
        aria-expanded={tooltipOpen}
        onClick={(event) => {
          event.stopPropagation();
          setTooltipOpen((open) => !open);
        }}
        onMouseEnter={() => setTooltipOpen(true)}
        onMouseLeave={() => setTooltipOpen(false)}
      >
        <svg
          className="absolute inset-0 h-6 w-6 -rotate-90"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            cx="12"
            cy="12"
            r="9.75"
            fill="none"
            strokeWidth="3"
            className="stroke-zinc-200 dark:stroke-zinc-700"
          />
          <circle
            cx="12"
            cy="12"
            r="9.75"
            fill="none"
            strokeWidth="3"
            strokeLinecap="round"
            className={`${ringStrokeClass} transition-[stroke-dashoffset] duration-300`}
            style={{
              strokeDasharray: String(CONTEXT_RING_CIRCUMFERENCE),
              strokeDashoffset: String(ringOffset),
            }}
          />
        </svg>
        <span className="relative z-10 flex h-[15px] w-[15px] items-center justify-center rounded-full bg-white text-[8px] font-semibold tabular-nums text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          {display.hasPromptTok ? display.pct : "·"}
        </span>
      </button>

      <div
        id="ctx-usage-tooltip"
        role="tooltip"
        aria-hidden={!tooltipOpen}
        className={`absolute bottom-full right-0 z-50 mb-2 min-w-[220px] max-w-[min(280px,calc(100vw-2rem))] rounded-xl border border-zinc-200 bg-white px-3 py-2 text-left shadow-lg dark:border-zinc-700 dark:bg-zinc-900 ${
          tooltipOpen ? "visible opacity-100" : "pointer-events-none invisible opacity-0"
        } transition-opacity duration-150`}
      >
        <p className="text-xs font-medium text-zinc-800 dark:text-zinc-100">
          {display.usageText}
        </p>
        <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
          {display.tokensText}
        </p>
        {display.thresholdText ? (
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            {display.thresholdText}
          </p>
        ) : null}
        {display.costText ? (
          <p className="mt-0.5 text-[11px] text-zinc-500 dark:text-zinc-400">
            {display.costText}
          </p>
        ) : null}
        {compressLabel && onCompressHint ? (
          <button
            type="button"
            className="mt-2 w-full rounded-lg border border-zinc-200 px-2 py-1 text-left text-[11px] text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            onClick={(event) => {
              event.stopPropagation();
              onCompressHint();
              setTooltipOpen(false);
            }}
          >
            {compressLabel}
          </button>
        ) : null}
      </div>
    </div>
  );
};
