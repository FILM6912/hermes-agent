import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import type { ApprovalChoice } from "../services/approvalApi";
import { formatApprovalDescription } from "../utils/formatApprovalDescription";
import { displayVirtualPathsInText } from "@/services/hermes/displayVirtualPaths";

export interface ApprovalComposerPanelProps {
  pending: {
    approval_id?: string;
    description?: string;
    pattern_key?: string;
    pattern_keys?: string[];
    command?: string;
  };
  pendingCount: number;
  isResponding: boolean;
  onRespond: (choice: ApprovalChoice) => void | Promise<void>;
}

export const ApprovalComposerPanel: React.FC<ApprovalComposerPanelProps> = ({
  pending,
  pendingCount,
  isResponding,
  onRespond,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const onceRef = useRef<HTMLButtonElement>(null);

  const description = useMemo(
    () => formatApprovalDescription(pending),
    [pending],
  );

  const commandPreview = useMemo(
    () => (pending.command ? displayVirtualPathsInText(pending.command) : ""),
    [pending.command],
  );

  useEffect(() => {
    setCollapsed(false);
  }, [pending.approval_id]);

  useEffect(() => {
    if (onceRef.current) {
      onceRef.current.focus({ preventScroll: true });
    }
  }, [pending.approval_id]);

  const handleChoice = (choice: ApprovalChoice) => {
    void onRespond(choice);
  };

  return (
    <div
      className="border-b border-amber-200/70 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 px-4 py-3"
      role="region"
      aria-labelledby="approval-composer-heading"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2
              id="approval-composer-heading"
              className="text-sm font-semibold text-zinc-900 dark:text-zinc-100"
            >
              Approval required
            </h2>
            {pendingCount > 1 && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                1 of {pendingCount}
              </span>
            )}
            <button
              type="button"
              onClick={() => setCollapsed((v) => !v)}
              className="ml-auto rounded-md p-1 text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-zinc-800"
              aria-expanded={!collapsed}
              aria-label={collapsed ? "Expand approval" : "Collapse approval"}
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
              <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">
                {description || "Dangerous command detected"}
              </p>
              {commandPreview ? (
                <pre className="mt-2 max-h-28 overflow-auto rounded-lg bg-zinc-950 px-3 py-2 text-xs text-zinc-100 font-mono whitespace-pre-wrap break-all">
                  {commandPreview}
                </pre>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  ref={onceRef}
                  type="button"
                  disabled={isResponding}
                  onClick={() => handleChoice("once")}
                  className="inline-flex items-center justify-center rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60 transition-colors"
                >
                  {isResponding ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Allow once"
                  )}
                </button>
                <button
                  type="button"
                  disabled={isResponding}
                  onClick={() => handleChoice("session")}
                  className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60 transition-colors"
                >
                  Allow session
                </button>
                <button
                  type="button"
                  disabled={isResponding}
                  onClick={() => handleChoice("always")}
                  className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60 transition-colors"
                >
                  Always allow
                </button>
                <button
                  type="button"
                  disabled={isResponding}
                  onClick={() => handleChoice("deny")}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60 transition-colors"
                >
                  Deny
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
