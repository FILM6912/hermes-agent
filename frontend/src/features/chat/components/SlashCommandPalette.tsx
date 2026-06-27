import React from "react";
import { Terminal } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import {
  extractSlashToken,
  listCommands,
  loadSkillsForSlashCached,
  matchSlashCommands,
  type HermesCommand,
  type SlashCommandMatch,
  type SlashTokenRange,
} from "@/services/hermes/commands";

export type SlashCommandPaletteProps = {
  input: string;
  setInput: (value: string) => void;
  selectedIndex: number;
  onSelectedIndexChange: (index: number) => void;
  onClose: () => void;
  onConfirmSelection?: () => void;
};

let commandsCache: HermesCommand[] | null = null;
let commandsLoadPromise: Promise<HermesCommand[]> | null = null;

async function loadCommandsCached(): Promise<HermesCommand[]> {
  if (commandsCache) return commandsCache;
  if (commandsLoadPromise) return commandsLoadPromise;
  commandsLoadPromise = listCommands()
    .then((cmds) => {
      commandsCache = cmds;
      return cmds;
    })
    .catch(() => {
      commandsCache = [];
      return [];
    })
    .finally(() => {
      commandsLoadPromise = null;
    });
  return commandsLoadPromise;
}

export function useSlashCommandPalette(input: string, cursor: number) {
  const { t } = useLanguage();
  const [matches, setMatches] = React.useState<SlashCommandMatch[]>([]);
  const [open, setOpen] = React.useState(false);
  const [selectedIndex, setSelectedIndex] = React.useState(0);
  const inputSnapshotRef = React.useRef(input);
  const cursorSnapshotRef = React.useRef(cursor);
  const skillDefaultDesc =
    t("chat.slashSkillDesc") || "Invoke this skill";

  const tokenRange = React.useMemo(
    () => extractSlashToken(input, cursor),
    [input, cursor],
  );

  const applyMatches = React.useCallback(
    (snapshot: string, commands: HermesCommand[], skills: Awaited<ReturnType<typeof loadSkillsForSlashCached>>) => {
      const next = matchSlashCommands(snapshot, commands, {
        skills,
        skillDefaultDescription: skillDefaultDesc,
      });
      setMatches(next);
      setOpen(next.length > 0);
      setSelectedIndex(next.length > 0 ? 0 : -1);
    },
    [skillDefaultDesc],
  );

  React.useEffect(() => {
    inputSnapshotRef.current = input;
    cursorSnapshotRef.current = cursor;
    if (!tokenRange) {
      setOpen(false);
      setMatches([]);
      return;
    }

    let cancelled = false;
    const snapshot = tokenRange.token;
    void Promise.all([loadCommandsCached(), loadSkillsForSlashCached()]).then(
      ([commands, skills]) => {
        if (cancelled || inputSnapshotRef.current !== input) return;
        const current = extractSlashToken(
          inputSnapshotRef.current,
          cursorSnapshotRef.current,
        );
        if (!current || current.token !== snapshot) return;
        applyMatches(snapshot, commands, skills);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [input, cursor, tokenRange, applyMatches]);

  const close = React.useCallback(() => {
    setOpen(false);
    setSelectedIndex(-1);
  }, []);

  return { matches, open, selectedIndex, setSelectedIndex, close, tokenRange };
}

export const SlashCommandPalette: React.FC<
  SlashCommandPaletteProps & {
    matches: SlashCommandMatch[];
    open: boolean;
    tokenRange: SlashTokenRange | null;
    onApplyMatch: (match: SlashCommandMatch) => void;
  }
> = ({
  input: _input,
  matches,
  open,
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

  if (!open || matches.length === 0) return null;

  const applyMatch = (match: SlashCommandMatch) => {
    onApplyMatch(match);
    onClose();
  };

  return (
    <div
      ref={listRef}
      className="absolute bottom-full left-0 right-0 mb-2 mx-1 bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl z-50 flex flex-col animate-in slide-in-from-bottom-2 fade-in duration-200 overflow-hidden max-h-56"
      role="listbox"
      aria-label={t("chat.slashCommands") || "Slash commands"}
    >
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-[10px] font-bold text-zinc-500 uppercase tracking-wider flex items-center gap-2">
        <Terminal className="w-3 h-3" />
        <span>{t("chat.slashCommands") || "Commands"}</span>
      </div>
      <div className="overflow-y-auto scrollbar-hide py-1">
        {matches.map((match, index) => {
          const isSubArg = Boolean(match.subArg);
          const label = isSubArg
            ? `/${match.parent} ${match.subArg}`
            : `/${match.name}`;
          const isSelected = index === selectedIndex;

          return (
            <button
              key={`${match.name}-${match.subArg ?? ""}-${index}`}
              type="button"
              data-selected={isSelected ? "true" : "false"}
              className={`w-full text-left px-3 py-2 flex flex-col gap-0.5 transition-colors ${
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
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200 truncate">
                  {label}
                </span>
                {match.source === "skill" ? (
                  <span className="shrink-0 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300">
                    {t("chat.slashSkillBadge") || "Skill"}
                  </span>
                ) : match.category ? (
                  <span className="shrink-0 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-zinc-200/80 dark:bg-zinc-700/80 text-zinc-600 dark:text-zinc-400">
                    {match.category}
                  </span>
                ) : null}
              </div>
              {match.description && (
                <span className="text-xs text-zinc-500 dark:text-zinc-400 line-clamp-2">
                  {match.description}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

/** Keyboard handler for slash palette — call from textarea onKeyDown. Returns true if handled. */
export function handleSlashPaletteKeyDown(
  e: React.KeyboardEvent,
  opts: {
    open: boolean;
    matches: SlashCommandMatch[];
    selectedIndex: number;
    setSelectedIndex: (index: number) => void;
    onApplyMatch: (match: SlashCommandMatch) => void;
    onClose: () => void;
  },
): boolean {
  const { open, matches, selectedIndex, setSelectedIndex, onApplyMatch, onClose } = opts;
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
