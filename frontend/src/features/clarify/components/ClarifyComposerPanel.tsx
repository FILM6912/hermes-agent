import React, { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, HelpCircle } from "lucide-react";
import type { ClarifyPending } from "../services/clarifyApi";

export function clarifyChoices(pending: {
  choices_offered?: string[];
  choices?: string[];
}): string[] {
  if (Array.isArray(pending.choices_offered) && pending.choices_offered.length > 0) {
    return pending.choices_offered;
  }
  if (Array.isArray(pending.choices) && pending.choices.length > 0) {
    return pending.choices;
  }
  return [];
}

export function clarifyExpiryMs(pending: {
  expires_at?: number;
  requested_at?: number;
  timeout_seconds?: number;
}): number {
  const expiresAt = Number(pending.expires_at);
  if (Number.isFinite(expiresAt) && expiresAt > 0) return expiresAt * 1000;
  const requestedAt = Number(pending.requested_at);
  const timeoutSeconds = Number(pending.timeout_seconds);
  if (Number.isFinite(requestedAt) && Number.isFinite(timeoutSeconds)) {
    return (requestedAt + timeoutSeconds) * 1000;
  }
  return 0;
}

export interface ClarifyComposerPanelProps {
  pending: ClarifyPending;
  isResponding: boolean;
  error: string | null;
  onRespond: (text: string) => Promise<boolean>;
  onFocusInput?: () => void;
}

export const ClarifyComposerPanel: React.FC<ClarifyComposerPanelProps> = ({
  pending,
  isResponding,
  error,
  onRespond,
  onFocusInput,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  const question = pending?.question ?? pending?.description ?? "";
  const choices = useMemo(() => clarifyChoices(pending), [pending]);

  useEffect(() => {
    setCollapsed(false);
  }, [pending.clarify_id]);

  useEffect(() => {
    const expires = clarifyExpiryMs(pending);
    if (!expires) {
      setSecondsLeft(null);
      return;
    }
    const tick = () => {
      setSecondsLeft(Math.max(0, Math.ceil((expires - Date.now()) / 1000)));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [pending]);

  const submitChoice = async (choice: string) => {
    await onRespond(choice);
  };

  return (
    <div
      className="border-b border-blue-200/70 dark:border-blue-900/50 bg-blue-50/50 dark:bg-blue-950/20 px-4 py-3"
      role="region"
      aria-labelledby="clarify-composer-heading"
    >
      <div className="flex items-start gap-2">
        <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-blue-600 dark:text-blue-400" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2
              id="clarify-composer-heading"
              className="text-sm font-semibold text-zinc-900 dark:text-zinc-100"
            >
              Clarification needed
            </h2>
            {secondsLeft !== null && (
              <span
                className={`text-xs font-medium tabular-nums ${
                  secondsLeft <= 10
                    ? "text-red-500"
                    : "text-zinc-500 dark:text-zinc-400"
                }`}
              >
                {secondsLeft}s
              </span>
            )}
            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              className="ml-auto rounded-md p-1 text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-zinc-800"
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Expand clarification" : "Collapse clarification"}
            >
              {collapsed ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </button>
          </div>
          {!collapsed && (
            <>
              <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap">
                {question}
              </p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Pick a choice below, or type your answer in the box.
              </p>
              {choices.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {choices.map((choice, index) => (
                    <button
                      key={`${choice}-${index}`}
                      type="button"
                      disabled={isResponding}
                      onClick={() => void submitChoice(choice)}
                      className="inline-flex max-w-full items-center gap-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2.5 py-1.5 text-left text-sm text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60 transition-colors"
                    >
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-zinc-200 dark:bg-zinc-700 text-xs font-semibold">
                        {index + 1}
                      </span>
                      <span className="truncate">{choice}</span>
                    </button>
                  ))}
                  <button
                    type="button"
                    disabled={isResponding}
                    onClick={() => onFocusInput?.()}
                    className="inline-flex items-center rounded-lg border border-dashed border-zinc-300 dark:border-zinc-600 px-2.5 py-1.5 text-sm text-zinc-600 dark:text-zinc-400 hover:bg-white dark:hover:bg-zinc-900 disabled:opacity-60 transition-colors"
                  >
                    Other
                  </button>
                </div>
              )}
              {error ? <p className="mt-2 text-xs text-red-500">{error}</p> : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
