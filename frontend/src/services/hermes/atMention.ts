/**
 * Composer `@path` mention — workspace file/folder autocomplete (legacy drag-drop parity).
 */
import {
  isDirectoryEntry,
  listDirectory,
  type HermesDirEntry,
} from "@/services/hermes/workspace";

export type AtTokenRange = {
  start: number;
  end: number;
  /** Full token including `@`, e.g. `@src/foo` */
  token: string;
  parentDir: string;
  namePrefix: string;
};

export type AtMentionMatch = {
  path: string;
  name: string;
  type: "file" | "folder";
  label: string;
};

export type AtMentionListOptions = {
  sessionId?: string;
  workspace?: string;
  parentDir: string;
  namePrefix: string;
  limit?: number;
};

const listCache = new Map<string, { entries: HermesDirEntry[]; at: number }>();
const CACHE_MS = 8000;

function cacheKey(
  sessionId: string | undefined,
  workspace: string | undefined,
  parentDir: string,
): string {
  return `${workspace?.trim() || ""}:${sessionId?.trim() || ""}:${parentDir}`;
}

function normalizeParentDir(dir: string): string {
  const trimmed = dir.replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+$/, "");
  return trimmed || ".";
}

function joinWorkspacePath(parentDir: string, name: string): string {
  const parent = normalizeParentDir(parentDir);
  if (parent === ".") return name;
  return `${parent}/${name}`;
}

/** Active `@path` token at the cursor (after whitespace, no spaces in path). */
export function extractAtToken(text: string, cursor: number): AtTokenRange | null {
  if (text.includes("\n")) return null;
  const pos = Math.max(0, Math.min(cursor, text.length));

  let atIdx = -1;
  for (let i = pos - 1; i >= 0; i--) {
    if (text[i] === "\n") return null;
    if (text[i] === "@") {
      if (i === 0 || /\s/.test(text[i - 1] ?? "")) {
        atIdx = i;
        break;
      }
    }
  }
  if (atIdx < 0 || pos <= atIdx) return null;

  const rawQuery = text.slice(atIdx + 1, pos);
  if (!rawQuery.length && pos === atIdx + 1) {
    return {
      start: atIdx,
      end: pos,
      token: "@",
      parentDir: ".",
      namePrefix: "",
    };
  }
  if (/\s/.test(rawQuery)) return null;

  const segments = rawQuery.split("/");
  const namePrefix = segments.pop() ?? "";
  const parentDir = normalizeParentDir(segments.join("/"));

  return {
    start: atIdx,
    end: pos,
    token: text.slice(atIdx, pos),
    parentDir,
    namePrefix,
  };
}

export function buildAtReplacement(match: AtMentionMatch): string {
  if (match.type === "folder") {
    return `@${match.path}/`;
  }
  return `@${match.path} `;
}

export function applyAtMatchToInput(
  input: string,
  range: AtTokenRange,
  match: AtMentionMatch,
): { value: string; cursor: number } {
  const replacement = buildAtReplacement(match);
  const before = input.slice(0, range.start);
  const after = input.slice(range.end);
  const value = before + replacement + after;
  return { value, cursor: before.length + replacement.length };
}

function entryToMatch(entry: HermesDirEntry, parentDir: string): AtMentionMatch {
  const isFolder = isDirectoryEntry(entry);
  const path = joinWorkspacePath(parentDir, entry.name);
  return {
    path,
    name: entry.name,
    type: isFolder ? "folder" : "file",
    label: isFolder ? `${entry.name}/` : entry.name,
  };
}

/** List one directory level and filter by name prefix for `@` autocomplete. */
export async function listAtMentionMatches(
  options: AtMentionListOptions,
): Promise<AtMentionMatch[]> {
  const workspace = options.workspace?.trim();
  const sessionId = options.sessionId?.trim();
  if (!workspace && !sessionId) return [];

  const parentDir = normalizeParentDir(options.parentDir);
  const prefix = options.namePrefix.toLowerCase();
  const limit = options.limit ?? 24;
  const key = cacheKey(sessionId, workspace, parentDir);
  const cached = listCache.get(key);
  let entries: HermesDirEntry[];

  if (cached && Date.now() - cached.at < CACHE_MS) {
    entries = cached.entries;
  } else {
    const data = await listDirectory({
      workspace: workspace || undefined,
      sessionId: workspace ? undefined : sessionId,
      path: parentDir,
    });
    entries = data.entries ?? [];
    listCache.set(key, { entries, at: Date.now() });
  }

  const matches: AtMentionMatch[] = [];
  for (const entry of entries) {
    if (prefix && !entry.name.toLowerCase().startsWith(prefix)) continue;
    matches.push(entryToMatch(entry, parentDir));
    if (matches.length >= limit) break;
  }

  matches.sort((a, b) => {
    if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });

  return matches;
}

export function invalidateAtMentionListCache(): void {
  listCache.clear();
}
