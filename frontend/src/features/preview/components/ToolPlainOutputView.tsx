import React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  vscDarkPlus,
  vs,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import { useTheme } from "@/hooks/useTheme";
import {
  inferToolOutputLanguage,
  isTerminalLikeTool,
  normalizeToolOutputText,
  parseToolOutputBlocks,
  type ToolOutputBlock,
} from "@/features/preview/utils/formatToolOutput";

const SCROLL_SHELL =
  "max-h-[min(70vh,520px)] overflow-y-auto overflow-x-auto overscroll-contain";

const HIGHLIGHTER_STYLE = {
  margin: 0,
  padding: 0,
  fontSize: "0.75rem",
  lineHeight: "1.625",
  background: "transparent",
} as const;

const ToolHighlightedCode = ({
  code,
  language,
  className = "",
}: {
  code: string;
  language: "json" | "python" | "bash";
  className?: string;
}) => {
  const { isDark } = useTheme();
  return (
    <SyntaxHighlighter
      language={language}
      style={isDark ? vscDarkPlus : vs}
      customStyle={HIGHLIGHTER_STYLE}
      codeTagProps={{
        style: {
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        },
      }}
      wrapLongLines
      PreTag="div"
      className={className}
    >
      {code}
    </SyntaxHighlighter>
  );
};

const ToolCodeBody = ({
  text,
  tone,
  terminal = false,
  toolName,
  language,
}: {
  text: string;
  tone: "input" | "output" | "error";
  terminal?: boolean;
  toolName?: string;
  language?: "json" | "python" | "bash" | null;
}) => {
  const resolved =
    language ?? inferToolOutputLanguage(text, { toolName, tone });

  if (resolved) {
    return <ToolHighlightedCode code={text} language={resolved} />;
  }

  return (
    <pre
      className={`whitespace-pre-wrap break-words m-0 leading-relaxed ${
        terminal
          ? "text-emerald-100/95"
          : tone === "error"
            ? "text-red-800 dark:text-red-200"
            : "text-zinc-700 dark:text-zinc-300"
      }`}
    >
      {text}
    </pre>
  );
};

export const JsonPrettyBlock = ({
  value,
  tone,
}: {
  value: unknown;
  tone: "input" | "output" | "error";
}) => {
  const formatted = JSON.stringify(value, null, 2);
  const shell = toneShell(tone);
  return (
    <div className={`${shell} text-xs font-mono ${SCROLL_SHELL}`}>
      <ToolHighlightedCode code={formatted} language="json" className="min-w-min" />
    </div>
  );
};

export const CollapsibleTextBlock = ({
  text,
  tone,
  collapseAt,
  terminal = false,
  toolName,
}: {
  text: string;
  tone: "input" | "output" | "error";
  collapseAt: number;
  terminal?: boolean;
  toolName?: string;
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const normalized = React.useMemo(() => normalizeToolOutputText(text), [text]);
  const large = normalized.length > collapseAt;
  const shown = large && !expanded ? `${normalized.slice(0, collapseAt)}\n…` : normalized;
  const shell = terminal ? terminalShell() : toneShell(tone);

  return (
    <div className="space-y-2">
      <div className={`${shell} text-xs font-mono ${SCROLL_SHELL}`}>
        <ToolCodeBody
          text={shown}
          tone={tone}
          terminal={terminal}
          toolName={toolName}
        />
      </div>
      {large ? (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? (
            <>
              <ChevronDown className="h-3 w-3" />
              Show less
            </>
          ) : (
            <>
              <ChevronRight className="h-3 w-3" />
              Show full output ({normalized.length.toLocaleString()} chars)
            </>
          )}
        </button>
      ) : null}
    </div>
  );
};

function toneShell(tone: "input" | "output" | "error"): string {
  if (tone === "error") {
    return "rounded-lg p-3 border bg-red-50 dark:bg-red-950/25 border-red-200/80 dark:border-red-900/50";
  }
  if (tone === "input") {
    return "rounded-lg p-3 border bg-zinc-50 dark:bg-zinc-900/50 border-zinc-200/80 dark:border-zinc-800/60";
  }
  return "rounded-lg p-3 border bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200/60 dark:border-emerald-800/40";
}

function terminalShell(): string {
  return "rounded-lg p-3 border bg-zinc-950 border-zinc-800/80 shadow-inner";
}

const OutputTable = ({ caption, rows }: { caption: string; rows: string[][] }) => {
  const colCount = Math.max(...rows.map((r) => r.length), 0);
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{caption}</div>
      <div className={`rounded-lg border border-zinc-200/80 dark:border-zinc-800/60 overflow-x-auto ${SCROLL_SHELL}`}>
        <table className="w-full text-left text-[11px] font-mono border-collapse min-w-max">
          <tbody>
            {rows.map((row, ri) => (
              <tr
                key={ri}
                className={
                  ri % 2 === 0
                    ? "bg-zinc-50/80 dark:bg-zinc-900/40"
                    : "bg-white/50 dark:bg-zinc-950/30"
                }
              >
                {Array.from({ length: colCount }, (_, ci) => (
                  <td
                    key={ci}
                    className="px-2.5 py-1.5 whitespace-nowrap text-zinc-700 dark:text-zinc-300 border-b border-zinc-100 dark:border-zinc-800/60"
                  >
                    {row[ci] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const SectionCard = ({
  emoji,
  title,
  lines,
  terminal,
  tone,
  toolName,
}: {
  emoji: string;
  title: string;
  lines: string[];
  terminal: boolean;
  tone: "input" | "output" | "error";
  toolName?: string;
}) => {
  const body = lines.join("\n").trim();
  if (!body) {
    return (
      <div
        className={`rounded-lg border px-3 py-2 ${
          terminal
            ? "border-zinc-800 bg-zinc-950/80"
            : "border-zinc-200/80 bg-zinc-50/50 dark:border-zinc-800/60 dark:bg-zinc-900/30"
        }`}
      >
        <div className="flex items-start gap-2 text-sm">
          <span className="shrink-0" aria-hidden>
            {emoji}
          </span>
          <span
            className={
              terminal
                ? "text-emerald-100/90 font-medium"
                : "text-zinc-800 dark:text-zinc-200 font-medium"
            }
          >
            {title}
          </span>
        </div>
      </div>
    );
  }
  return (
    <div
      className={`rounded-lg border overflow-hidden ${
        terminal
          ? "border-zinc-800 bg-zinc-950/90"
          : "border-zinc-200/80 dark:border-zinc-800/60"
      }`}
    >
      <div
        className={`flex items-start gap-2 px-3 py-2 text-sm font-medium border-b ${
          terminal
            ? "border-zinc-800 text-emerald-100/95 bg-zinc-900/50"
            : "border-zinc-200/80 dark:border-zinc-800/60 text-zinc-800 dark:text-zinc-200 bg-zinc-50/80 dark:bg-zinc-900/40"
        }`}
      >
        <span className="shrink-0" aria-hidden>
          {emoji}
        </span>
        <span className="min-w-0 break-words">{title}</span>
      </div>
      {body ? (
        <div className="px-3 py-2 text-xs font-mono">
          <ToolCodeBody
            text={body}
            tone={tone}
            terminal={terminal}
            toolName={toolName}
          />
        </div>
      ) : null}
    </div>
  );
};

const StructuredBlocks = ({
  blocks,
  terminal,
  tone,
  toolName,
}: {
  blocks: ToolOutputBlock[];
  terminal: boolean;
  tone: "input" | "output" | "error";
  toolName?: string;
}) => {
  const outer =
    tone === "error"
      ? toneShell("error")
      : terminal
        ? terminalShell()
        : toneShell(tone);

  return (
    <div className={`space-y-3 ${terminal ? "" : outer} ${terminal ? `${terminalShell()} p-3 space-y-3` : "p-0"}`}>
      {blocks.map((block, i) => {
        if (block.type === "section") {
          return (
            <SectionCard
              key={`s-${i}`}
              emoji={block.emoji}
              title={block.title}
              lines={block.lines}
              terminal={terminal}
              tone={tone}
              toolName={toolName}
            />
          );
        }
        if (block.type === "table") {
          return <OutputTable key={`t-${i}`} caption={block.caption} rows={block.rows} />;
        }
        const text = block.lines.join("\n").trim();
        if (!text) return null;
        return (
          <div key={`x-${i}`} className="text-xs font-mono">
            <ToolCodeBody
              text={text}
              tone={tone}
              terminal={terminal}
              toolName={toolName}
            />
          </div>
        );
      })}
    </div>
  );
};

export type ToolPlainOutputViewProps = {
  text: string;
  tone: "input" | "output" | "error";
  toolName?: string;
  collapseAt: number;
};

export const ToolPlainOutputView: React.FC<ToolPlainOutputViewProps> = ({
  text,
  tone,
  toolName,
  collapseAt,
}) => {
  const [expanded, setExpanded] = React.useState(false);
  const normalized = React.useMemo(() => normalizeToolOutputText(text), [text]);
  const blocks = React.useMemo(() => parseToolOutputBlocks(normalized), [normalized]);
  const terminal = isTerminalLikeTool(toolName);
  const structured =
    blocks.length > 1 ||
    blocks.some((b) => b.type === "section" || b.type === "table");
  const large = normalized.length > collapseAt;

  if (!structured) {
    return (
      <CollapsibleTextBlock
        text={text}
        tone={tone}
        collapseAt={collapseAt}
        terminal={terminal}
        toolName={toolName}
      />
    );
  }

  const previewBlocks =
    large && !expanded
      ? blocks.slice(0, Math.min(blocks.length, 4))
      : blocks;

  return (
    <div className="space-y-2">
      <div className={large && !expanded ? "max-h-[min(50vh,360px)] overflow-hidden relative" : ""}>
        <StructuredBlocks
          blocks={previewBlocks}
          terminal={terminal}
          tone={tone}
          toolName={toolName}
        />
        {large && !expanded ? (
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-background to-transparent"
            aria-hidden
          />
        ) : null}
      </div>
      {large ? (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? (
            <>
              <ChevronDown className="h-3 w-3" />
              Show less
            </>
          ) : (
            <>
              <ChevronRight className="h-3 w-3" />
              Show full output ({normalized.length.toLocaleString()} chars)
            </>
          )}
        </button>
      ) : null}
    </div>
  );
};
