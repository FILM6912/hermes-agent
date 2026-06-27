/** Normalize tool stdout / snippet text for display (preserve structure). */
export function normalizeToolOutputText(text: string): string {
  let t = text.replace(/\r\n/g, "\n");
  // Break emoji section headers glued to prior text on the same line.
  t = t.replace(
    /([^\n])(?=(?:✅|📊|📈|📁|📋|🔧|⚠️|❌|💡|📝|🚀|🔄|⏱|📦|🌡|💾)\s)/gu,
    "$1\n",
  );
  // Mid-line emoji headers (e.g. "success! 📊 Total records").
  t = t.replace(
    /\s+(📊|📈|📁|📋|🔧|⚠️|❌|💡|📝|🚀|🔄|⏱|📦|🌡|💾)\s+/gu,
    "\n$1 ",
  );
  // Break crammed tabular rows: "... 41.75 1 2026-06-04 ..."
  t = t.replace(
    /(\d+\.\d+)\s+(\d+)\s+(20\d{2}-\d{2}-\d{2}\s)/g,
    "$1\n$2 $3",
  );
  return t;
}

const SECTION_EMOJI_RE =
  /^(✅|📊|📈|📁|📋|🔧|⚠️|❌|💡|📝|🚀|🔄|⏱|📦|🌡|💾)\s*(.*)$/u;

const TABLE_CAPTION_RE = /sample\s+data|first\s+\d+\s+rows?/i;
const TABLE_ROW_INDEX_RE = /^\d+\s+20\d{2}-\d{2}-\d{2}/;

export type ToolOutputBlock =
  | { type: "section"; emoji: string; title: string; lines: string[] }
  | { type: "table"; caption: string; rows: string[][] }
  | { type: "text"; lines: string[] };

function splitWhitespaceRow(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed) return [];
  if (/\t/.test(trimmed)) {
    return trimmed.split(/\t+/).map((c) => c.trim()).filter(Boolean);
  }
  if (/\s{2,}/.test(trimmed)) {
    return trimmed.split(/\s{2,}/).map((c) => c.trim()).filter(Boolean);
  }
  return trimmed.split(/\s+/).filter(Boolean);
}

function isTableDataRow(line: string): boolean {
  const t = line.trim();
  if (!t) return false;
  if (TABLE_ROW_INDEX_RE.test(t)) return true;
  const cols = splitWhitespaceRow(t);
  return cols.length >= 5 && /\d/.test(t);
}

function parseTableLines(lines: string[]): { caption: string; rows: string[][] } | null {
  const captionIdx = lines.findIndex((l) => TABLE_CAPTION_RE.test(l));
  if (captionIdx === -1) return null;

  const caption = lines[captionIdx].trim();
  const dataLines: string[] = [];
  for (let i = captionIdx + 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    if (SECTION_EMOJI_RE.test(line)) break;
    if (isTableDataRow(line)) dataLines.push(line);
    else if (dataLines.length > 0) break;
  }

  if (dataLines.length === 0) return null;
  const rows = dataLines.map(splitWhitespaceRow).filter((r) => r.length > 0);
  if (rows.length === 0) return null;
  return { caption, rows };
}

export function parseToolOutputBlocks(text: string): ToolOutputBlock[] {
  const normalized = normalizeToolOutputText(text);
  const lines = normalized.split("\n");
  const table = parseTableLines(lines);
  const blocks: ToolOutputBlock[] = [];
  let buffer: string[] = [];

  const flushText = () => {
    const chunk = buffer.join("\n").trim();
    buffer = [];
    if (!chunk) return;
    blocks.push({ type: "text", lines: chunk.split("\n") });
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (table && (trimmed === table.caption || TABLE_CAPTION_RE.test(trimmed))) {
      flushText();
      blocks.push({ type: "table", caption: table.caption, rows: table.rows });
      const rowSet = new Set(table.rows.map((r) => r.join("\t")));
      while (i + 1 < lines.length) {
        const next = lines[i + 1].trim();
        if (!next) {
          i++;
          continue;
        }
        if (SECTION_EMOJI_RE.test(next)) break;
        if (isTableDataRow(next) && rowSet.has(splitWhitespaceRow(next).join("\t"))) {
          i++;
          continue;
        }
        if (isTableDataRow(next)) break;
        break;
      }
      continue;
    }

    const sectionMatch =
      !TABLE_CAPTION_RE.test(trimmed) && trimmed.match(SECTION_EMOJI_RE);
    if (sectionMatch) {
      flushText();
      const emoji = sectionMatch[1];
      const title = sectionMatch[2].trim() || emoji;
      const bodyLines: string[] = [];
      i++;
      while (i < lines.length) {
        const next = lines[i];
        const nextTrim = next.trim();
        if (SECTION_EMOJI_RE.test(nextTrim)) {
          i--;
          break;
        }
        if (table && nextTrim === table.caption) {
          i--;
          break;
        }
        bodyLines.push(next);
        i++;
      }
      blocks.push({
        type: "section",
        emoji,
        title,
        lines: bodyLines.filter((l) => l.trim() !== ""),
      });
      continue;
    }

    buffer.push(line);
  }

  flushText();
  if (blocks.length === 0 && normalized.trim()) {
    return [{ type: "text", lines: normalized.split("\n") }];
  }
  return blocks;
}

export function isTerminalLikeTool(toolName: string | undefined): boolean {
  if (!toolName?.trim()) return false;
  const n = toolName.toLowerCase();
  return /terminal|bash|shell|command|exec|run_|subprocess|pty/.test(n);
}

const PYTHON_TRACEBACK_RE = /Traceback\s*\(most recent call last\)/;
const PYTHON_ERROR_RE =
  /(?:^|\n)\s*(?:[A-Z][a-zA-Z]*Error|Exception|SyntaxError|TypeError|ValueError|ImportError|RuntimeError|KeyError|AttributeError|ModuleNotFoundError|IndentationError)(?::|\s)/;

/** Pick a Prism language id for tool detail INPUT/OUTPUT text. */
export function inferToolOutputLanguage(
  text: string,
  options?: {
    toolName?: string;
    tone?: "input" | "output" | "error";
  },
): "json" | "python" | "bash" | null {
  const sample = text.slice(0, 8000).trim();
  if (!sample) return null;

  if (
    PYTHON_TRACEBACK_RE.test(sample) ||
    (options?.tone === "error" && PYTHON_ERROR_RE.test(sample))
  ) {
    return "python";
  }

  if (
    (sample.startsWith("{") && sample.endsWith("}")) ||
    (sample.startsWith("[") && sample.endsWith("]"))
  ) {
    try {
      JSON.parse(sample);
      return "json";
    } catch {
      /* not valid JSON */
    }
  }

  if (isTerminalLikeTool(options?.toolName)) return "bash";
  if (/^(?:\$|#)\s/m.test(sample)) return "bash";
  if (
    /(?:^|\n)(?:\/bin\/(?:ba)?sh|sudo\s|npm\s|git\s|docker\s|curl\s|wget\s|python3?\s|pip\s)/m.test(
      sample,
    )
  ) {
    return "bash";
  }

  return null;
}
