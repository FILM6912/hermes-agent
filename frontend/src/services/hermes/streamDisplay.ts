/** Assistant stream display helpers (SSE token → visible bubble / reasoning). */

const THINK_PAIRS: ReadonlyArray<{ open: string; close: string }> = [
  { open: "<think>", close: "</think>" },
  { open: "<|channel>thought\n", close: "<channel|>" },
  { open: "<|turn|>thinking\n", close: "<turn|>" },
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Return assistant text safe to show in the main bubble while thinking streams separately.
 */
export function stripThinkingFromAssistantStream(raw: string): string {
  let s = String(raw ?? "");
  for (const { open, close } of THINK_PAIRS) {
    const trimmed = s.trimStart();
    if (trimmed.startsWith(open)) {
      const closeIndex = trimmed.indexOf(close, open.length);
      if (closeIndex !== -1) {
        s = trimmed.slice(closeIndex + close.length).replace(/^\s+/, "");
        continue;
      }
      return "";
    }
    if (open.startsWith(trimmed)) {
      return "";
    }
  }
  for (const { open, close } of THINK_PAIRS) {
    s = s.replace(
      new RegExp(`${escapeRegExp(open)}[\\s\\S]*?${escapeRegExp(close)}`, "g"),
      "",
    );
    s = s.replace(new RegExp(`${escapeRegExp(open)}[\\s\\S]*$`), "");
  }
  return s.trimStart();
}

export function normalizeThinkingCompare(text: string): string {
  return String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\*\*/g, "")
    .replace(/[#*_`>]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

const PLACEHOLDER_THINKING = new Set([
  "thinking",
  "thinking…",
  "thinking...",
  "กำลังคิด",
  "กำลังคิด...",
]);

/** True when thinking content is non-empty and not the same as the visible answer. */
export function isDistinctThinking(thinking: string, answer: string): boolean {
  const t = normalizeThinkingCompare(thinking);
  if (!t || PLACEHOLDER_THINKING.has(t)) return false;
  const a = normalizeThinkingCompare(answer);
  if (!a) return true;
  if (t === a) return false;
  if (a.startsWith(t)) return false;
  if (t.startsWith(a)) {
    const remainder = t.slice(a.length).trim();
    if (remainder.length >= 80) return true;
    return false;
  }
  const shorter = Math.min(t.length, a.length);
  const longer = Math.max(t.length, a.length);
  if (shorter === 0) return false;
  if (t.includes(a) || a.includes(t)) {
    if (shorter / longer >= 0.82) return false;
  }
  return true;
}

export function combinedReasoningText(
  committed: string[],
  live: string,
): string {
  return [...committed, live].map((s) => s.trim()).filter(Boolean).join("\n\n");
}
