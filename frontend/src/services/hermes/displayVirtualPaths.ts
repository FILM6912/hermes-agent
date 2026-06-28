import type { HermesWorkspace } from "@/services/hermes/workspace";

let displayPathRegistry: HermesWorkspace[] = [];

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").replace(/^\.\//, "");
}

/** Keep registry rows in sync for command/approval display without prop drilling. */
export function seedDisplayPathRegistry(workspaces: HermesWorkspace[]): void {
  displayPathRegistry = workspaces;
}

function buildDiskReplacements(workspaces: HermesWorkspace[]): Array<{ disk: string; virtual: string }> {
  const pairs: Array<{ disk: string; virtual: string }> = [];
  for (const row of workspaces) {
    const disk = normalizePath(asString(row.disk_path));
    const virt = normalizePath(row.path) || "/workspace";
    if (disk && virt && disk !== virt) {
      pairs.push({ disk, virtual: virt });
    }
  }
  pairs.sort((a, b) => b.disk.length - a.disk.length);
  return pairs;
}

/** Map on-disk workspace paths in command text to UI virtual ``/workspace/...`` paths. */
export function displayVirtualPathsInText(
  text: string,
  workspaces?: HermesWorkspace[],
): string {
  const raw = text.trim();
  if (!raw) return text;

  const rows = workspaces ?? displayPathRegistry;
  if (!rows.length) return text;

  let out = text;
  for (const { disk, virtual } of buildDiskReplacements(rows)) {
    if (out.includes(disk)) {
      out = out.split(disk).join(virtual);
    }
  }
  return out;
}

const TOOL_DISPLAY_PATH_KEYS = new Set([
  "command",
  "cmd",
  "script",
  "code",
  "input",
  "shell",
  "path",
  "file",
  "filepath",
  "file_path",
  "target",
  "dest",
  "destination",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Rewrite path-like tool args before JSON formatting for timeline/history display. */
export function displayVirtualPathsInToolArgs(
  args: unknown,
  workspaces?: HermesWorkspace[],
): unknown {
  if (typeof args === "string") {
    return displayVirtualPathsInText(args, workspaces);
  }
  if (!isRecord(args)) return args;

  const out: Record<string, unknown> = { ...args };
  for (const [key, value] of Object.entries(out)) {
    if (typeof value === "string" && TOOL_DISPLAY_PATH_KEYS.has(key.toLowerCase())) {
      out[key] = displayVirtualPathsInText(value, workspaces);
    }
  }
  return out;
}
