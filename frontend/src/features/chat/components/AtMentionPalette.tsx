import React from "react";
import { FileText, Folder } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import {
  applyAtMatchToInput,
  extractAtToken,
  listAtMentionMatches,
  type AtMentionMatch,
  type AtTokenRange,
} from "@/services/hermes/atMention";

export type AtMentionPaletteProps = {
  input: string;
  cursor: number;
  sessionId?: string;
  workspace?: string;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
  onClose: () => void;
  onApplyMatch: (match: AtMentionMatch) => void;
};

export function useAtMentionPalette(
  input: string,
  cursor: number,
  options: { sessionId?: string; workspace?: string },
) {
  const [matches, setMatches] = React.useState<AtMentionMatch[]>([]);
  const [open, setOpen] = React.useState(false);
  const [selectedIndex, setSelectedIndex] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const inputSnapshotRef = React.useRef(input);
  const cursorSnapshotRef = React.useRef(cursor);

  const tokenRange = React.useMemo(
    () => extractAtToken(input, cursor),
    [input, cursor],
  );

  const canList = Boolean(
    options.workspace?.trim() || options.sessionId?.trim(),
  );

  React.useEffect(() => {
    inputSnapshotRef.current = input;
    cursorSnapshotRef.current = cursor;
    if (!tokenRange) {
      setOpen(false);
      setMatches([]);
      setLoading(false);
      return;
    }
    if (!canList) {
      setOpen(true);
      setMatches([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setOpen(true);
    setLoading(true);
    const snapshot = tokenRange.token;

    void listAtMentionMatches({
      sessionId: options.sessionId,
      workspace: options.workspace,
      parentDir: tokenRange.parentDir,
      namePrefix: tokenRange.namePrefix,
    })
      .then((next) => {
        if (cancelled || inputSnapshotRef.current !== input) return;
        const current = extractAtToken(
          inputSnapshotRef.current,
          cursorSnapshotRef.current,
        );
        if (!current || current.token !== snapshot) return;
        setMatches(next);
        setOpen(true);
        setSelectedIndex(next.length > 0 ? 0 : -1);
      })
      .catch(() => {
        if (!cancelled) {
          setMatches([]);
          setOpen(false);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    input,
    cursor,
    tokenRange,
    canList,
    options.sessionId,
    options.workspace,
  ]);

  const close = React.useCallback(() => {
    setOpen(false);
    setSelectedIndex(-1);
  }, []);

  return {
    matches,
    open,
    selectedIndex,
    setSelectedIndex,
    close,
    tokenRange,
    loading,
    canList,
  };
}

export const AtMentionPalette: React.FC<AtMentionPaletteProps & {
  matches: AtMentionMatch[];
  open: boolean;
  loading?: boolean;
  canList?: boolean;
  tokenRange: AtTokenRange | null;
}> = ({
  matches,
  open,
  loading = false,
  canList = true,
  selectedIndex,
  onSelectedIndexChange,
  onClose,
  onApplyMatch,
}) => {
  const { t } = useLanguage();
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open || !listRef.current) return;
    const selected = listRef.current.querySelector("[data-selected='true']");
    selected?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex, open]);

  if (!open) return null;

  const applyMatch = (match: AtMentionMatch) => {
    onApplyMatch(match);
    onClose();
  };

  return (
    <div
      ref={listRef}
      className="absolute bottom-full left-0 right-0 z-50 mx-1 mb-2 flex max-h-56 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xl animate-in fade-in slide-in-from-bottom-2 duration-200 dark:border-zinc-800 dark:bg-[#18181b]"
      role="listbox"
      aria-label={t("chat.atMentionTitle") || "Workspace files"}
    >
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900/50">
        <span>@</span>
        <span>{t("chat.atMentionTitle") || "Workspace files"}</span>
        {loading ? (
          <span className="ml-auto font-normal normal-case text-zinc-400">
            …
          </span>
        ) : null}
      </div>
      <div className="overflow-y-auto py-1 font-mono text-xs scrollbar-hide">
        {!canList ? (
          <div className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
            {t("chat.atMentionNeedWorkspace") ||
              "Choose a workspace or start a chat to attach files with @"}
          </div>
        ) : matches.length === 0 && !loading ? (
          <div className="px-3 py-2 text-zinc-500 dark:text-zinc-400">
            {t("chat.atMentionEmpty") || "No matching files"}
          </div>
        ) : (
          matches.map((match, index) => {
            const isSelected = index === selectedIndex;
            const Icon = match.type === "folder" ? Folder : FileText;
            return (
              <button
                key={`${match.path}-${index}`}
                type="button"
                data-selected={isSelected ? "true" : "false"}
                className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left transition-colors ${
                  isSelected
                    ? "bg-[#1447E6]/10 dark:bg-blue-500/15"
                    : "hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                }`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  applyMatch(match);
                }}
                onMouseEnter={() => onSelectedIndexChange(index)}
              >
                <span className="shrink-0 select-none text-zinc-400">|-</span>
                <Icon className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                <span className="min-w-0 truncate text-zinc-800 dark:text-zinc-200">
                  {match.label}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
};

export function handleAtPaletteKeyDown(
  e: React.KeyboardEvent,
  opts: {
    open: boolean;
    matches: AtMentionMatch[];
    selectedIndex: number;
    setSelectedIndex: (index: number) => void;
    onApplyMatch: (match: AtMentionMatch) => void;
    onClose: () => void;
  },
): boolean {
  const { open, matches, selectedIndex, setSelectedIndex, onApplyMatch, onClose } =
    opts;
  if (!open || matches.length === 0) return false;

  if (e.key === "ArrowDown") {
    e.preventDefault();
    setSelectedIndex((selectedIndex + 1) % matches.length);
    return true;
  }
  if (e.key === "ArrowUp") {
    e.preventDefault();
    setSelectedIndex((selectedIndex - 1 + matches.length) % matches.length);
    return true;
  }
  if (e.key === "Escape") {
    e.preventDefault();
    onClose();
    return true;
  }
  if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
    e.preventDefault();
    const match = matches[selectedIndex >= 0 ? selectedIndex : 0];
    if (match) onApplyMatch(match);
    onClose();
    return true;
  }
  return false;
}

export { applyAtMatchToInput };
