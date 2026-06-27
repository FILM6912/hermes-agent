import React, { useState } from "react";
import { ChevronRight, Copy, Star } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useToast } from "@/components/toast/ToastProvider";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { SessionCompressionAnchor } from "@/types";
import { compressionCopyForAnchor } from "../utils/compressionAnchor";

type CompressionReferenceCardProps = {
  anchor: SessionCompressionAnchor;
};

export const CompressionReferenceCard: React.FC<CompressionReferenceCardProps> = ({
  anchor,
}) => {
  const { t } = useLanguage();
  const { success, error } = useToast();
  const [expanded, setExpanded] = useState(false);
  const text = anchor.summary.trim();
  const copy = compressionCopyForAnchor(anchor, t);
  const preview = text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(" ");

  const handleCopy = async (event: React.MouseEvent) => {
    event.stopPropagation();
    const ok = await copyTextToClipboard(text);
    if (ok) success(t("chat.copy"));
    else error(t("chat.copyFailed"));
  };

  return (
    <div className="my-3 flex justify-start px-2 sm:px-4">
      <div className="w-full max-w-3xl">
        <div
          className={`overflow-hidden rounded-xl border border-amber-200/80 bg-amber-50/70 shadow-sm dark:border-amber-900/50 dark:bg-amber-950/20 ${
            expanded ? "ring-1 ring-amber-200/60 dark:ring-amber-900/40" : ""
          }`}
        >
          <div className="flex w-full items-center gap-2 px-3 py-2.5">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-2 text-left transition-colors hover:opacity-90"
              onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}
            >
              <Star className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <span className="shrink-0 text-sm font-medium text-amber-900 dark:text-amber-100">
                {copy.label}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-amber-800/80 dark:text-amber-200/70">
                {copy.preview}
                {preview ? ` · ${preview}` : ""}
              </span>
              <ChevronRight
                className={`h-4 w-4 shrink-0 text-amber-700 transition-transform dark:text-amber-300 ${
                  expanded ? "rotate-90" : ""
                }`}
              />
            </button>
            <button
              type="button"
              className="rounded-md p-1 text-amber-700 hover:bg-amber-200/60 dark:text-amber-300 dark:hover:bg-amber-900/50"
              title={t("chat.copy")}
              onClick={handleCopy}
              aria-label={t("chat.copy")}
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
          {expanded ? (
            <div className="border-t border-amber-200/70 px-3 py-3 dark:border-amber-900/40">
              <pre className="max-h-[min(70vh,48rem)] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">
                {text}
              </pre>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
