/**
 * Hermes workspace + file browser API (M18–M21).
 * Session-scoped listing uses GET /list; files use /file, /file/raw, /file/view, /file/save.
 */
import { buildApiUrl, fetchBlob, fetchJson } from "@/lib/api";
import type { FileNode } from "@/features/preview/components/FileTreeItem";
import type { ModelConfig } from "@/types";
import { modelProviderForHermes } from "@/services/hermes/models";
import { updateSession } from "@/services/hermes/sessions";

/** Workspace registry row from GET /workspaces. */
export type HermesWorkspace = {
  path: string;
  name: string;
  [key: string]: unknown;
};

export type HermesWorkspacesResponse = {
  workspaces: HermesWorkspace[];
  last: string;
  /** When true, POST /workspaces/add can create sub-folders under /workspace. */
  nested_workspaces?: boolean;
  path?: string;
};

export type HermesDirEntry = {
  name: string;
  path: string;
  type: "dir" | "file" | "symlink";
  size?: number | null;
  mtime_ns?: number | null;
  is_dir?: boolean;
  target?: string;
};

export type HermesListDirResponse = {
  entries: HermesDirEntry[];
  signature: string;
  path: string;
};

export type HermesReadFileResponse = {
  path: string;
  content: string;
  size: number;
  lines: number;
};

export type HermesFileMutationResponse = {
  ok: boolean;
  path?: string;
  old_path?: string;
  new_path?: string;
  size?: number;
  [key: string]: unknown;
};

export type WorkspaceFileRawOptions = {
  inline?: boolean;
  download?: boolean;
  /** List/preview files without session bind (parity with GET /list?workspace=). */
  workspace?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function isDirectoryEntry(entry: HermesDirEntry): boolean {
  if (entry.type === "dir") return true;
  if (entry.type === "symlink" && entry.is_dir) return true;
  return false;
}

/** Map one Hermes list entry to Agent-UI `FileNode` (children loaded lazily). */
export function mapEntryToFileNode(entry: HermesDirEntry): FileNode {
  const isFolder = isDirectoryEntry(entry);
  return {
    id: entry.path,
    name: entry.name,
    type: isFolder ? "folder" : "file",
    children: isFolder ? [] : undefined,
  };
}

/** Map a directory listing to sorted file nodes (folders first). */
export function mapEntriesToFileNodes(entries: HermesDirEntry[]): FileNode[] {
  const sorted = [...entries].sort((a, b) => {
    const aDir = isDirectoryEntry(a);
    const bDir = isDirectoryEntry(b);
    if (aDir !== bDir) return aDir ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });
  return sorted.map(mapEntryToFileNode);
}

function normalizeWorkspacePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").replace(/^\.\//, "");
}

/** Match a candidate path against registry rows (path, disk_path, normalized). */
export function findWorkspaceInRegistry(
  workspaces: HermesWorkspace[],
  candidate: string,
): HermesWorkspace | undefined {
  const target = candidate.trim();
  if (!target) return undefined;

  const exact = workspaces.find((w) => w.path === target);
  if (exact) return exact;

  for (const w of workspaces) {
    const diskPath = asString(w.disk_path);
    if (diskPath && diskPath === target) return w;
  }

  const normalizedTarget = normalizeWorkspacePath(target);
  for (const w of workspaces) {
    if (normalizeWorkspacePath(w.path) === normalizedTarget) return w;
    const diskPath = asString(w.disk_path);
    if (diskPath && normalizeWorkspacePath(diskPath) === normalizedTarget) return w;
  }

  return undefined;
}

export type ResolveAllowedComposerWorkspaceResult = {
  path: string;
  /** True when *preferred* matched a registry row. */
  matched: boolean;
};

/**
 * Pick a composer workspace path allowed for GET /list?workspace=.
 * Falls back to registry.last, then the first workspace row.
 */
export function resolveAllowedComposerWorkspace(
  preferred: string,
  registry: HermesWorkspacesResponse,
): ResolveAllowedComposerWorkspaceResult {
  const { workspaces, last } = registry;
  const match = findWorkspaceInRegistry(workspaces, preferred);
  if (match) {
    return { path: match.path, matched: true };
  }

  const lastTrimmed = last.trim();
  if (lastTrimmed) {
    const lastMatch = findWorkspaceInRegistry(workspaces, lastTrimmed);
    if (lastMatch) {
      return { path: lastMatch.path, matched: false };
    }
  }

  const first = workspaces[0];
  if (first?.path) {
    return { path: first.path, matched: false };
  }

  return { path: "", matched: false };
}

export function narrowWorkspacesResponse(value: unknown): HermesWorkspacesResponse {
  if (!isRecord(value) || !Array.isArray(value.workspaces)) {
    return { workspaces: [], last: "" };
  }
  const workspaces = value.workspaces
    .filter(isRecord)
    .map((w) => ({
      ...w,
      path: asString(w.path),
      name: asString(w.name, asString(w.path)),
    }))
    .filter((w) => w.path);
  return {
    workspaces,
    last: asString(value.last),
    nested_workspaces:
      typeof value.nested_workspaces === "boolean" ? value.nested_workspaces : undefined,
    path: asString(value.path) || undefined,
  };
}

export function narrowListDirResponse(value: unknown): HermesListDirResponse {
  if (!isRecord(value) || !Array.isArray(value.entries)) {
    return { entries: [], signature: "", path: "." };
  }
  const entries = value.entries.filter(isRecord).map((e) => ({
    name: asString(e.name),
    path: asString(e.path),
    type: (asString(e.type, "file") as HermesDirEntry["type"]) || "file",
    size: typeof e.size === "number" ? e.size : e.size === null ? null : undefined,
    mtime_ns: typeof e.mtime_ns === "number" ? e.mtime_ns : undefined,
    is_dir: typeof e.is_dir === "boolean" ? e.is_dir : undefined,
    target: typeof e.target === "string" ? e.target : undefined,
  }));
  return {
    entries,
    signature: asString(value.signature),
    path: asString(value.path, "."),
  };
}

import { seedDisplayPathRegistry } from "@/services/hermes/displayVirtualPaths";

/** GET /api/v1/workspaces — profile workspace registry. */
export async function listWorkspaces(): Promise<HermesWorkspacesResponse> {
  const raw = await fetchJson<unknown>("/workspaces");
  const result = narrowWorkspacesResponse(raw);
  seedDisplayPathRegistry(result.workspaces);
  return result;
}

/** GET /api/v1/workspaces/suggest — path autocomplete for add-workspace UI. */
export async function suggestWorkspaces(prefix = ""): Promise<{
  suggestions: string[];
  prefix: string;
}> {
  const raw = await fetchJson<unknown>("/workspaces/suggest", {
    query: { prefix },
  });
  if (!isRecord(raw)) return { suggestions: [], prefix };
  const suggestions = Array.isArray(raw.suggestions)
    ? raw.suggestions.map((s) => String(s))
    : [];
  return { suggestions, prefix: asString(raw.prefix, prefix) };
}

export type SwitchComposerWorkspaceOptions = {
  path: string;
  name?: string;
  sessionId?: string;
  modelConfig?: ModelConfig;
};

export type SwitchComposerWorkspaceResult = {
  path: string;
  name: string;
  workspaces: HermesWorkspace[];
};

/**
 * Composer workspace switch: register path when needed, then bind active session.
 * When no session is active, only updates the workspace registry (if required).
 */
export async function switchComposerWorkspace(
  options: SwitchComposerWorkspaceOptions,
): Promise<SwitchComposerWorkspaceResult> {
  const trimmed = options.path.trim();
  if (!trimmed) {
    throw new Error("Workspace path is required");
  }

  let registry = await listWorkspaces();
  let targetPath = trimmed;
  let targetName = options.name?.trim() || trimmed;

  const existing = findWorkspaceInRegistry(registry.workspaces, trimmed);
  if (!existing) {
    registry = await addWorkspace(trimmed, targetName);
    const added =
      findWorkspaceInRegistry(registry.workspaces, trimmed) ??
      registry.workspaces[registry.workspaces.length - 1];
    if (!added) {
      throw new Error("Workspace was not added");
    }
    targetPath = added.path;
    targetName = added.name || added.path;
  } else if (existing.name) {
    targetName = existing.name;
  }

  if (options.sessionId) {
    const modelId = options.modelConfig?.modelId;
    await updateSession(options.sessionId, {
      workspace: targetPath,
      model: modelId || undefined,
      modelProvider: modelId && options.modelConfig
        ? modelProviderForHermes(options.modelConfig)
        : undefined,
    });
  }

  return {
    path: targetPath,
    name: targetName,
    workspaces: registry.workspaces,
  };
}

/** POST /api/v1/workspaces/add */
export async function addWorkspace(
  path: string,
  name?: string,
  create = false,
  parent = "",
): Promise<HermesWorkspacesResponse> {
  const raw = await fetchJson<unknown>("/workspaces/add", {
    method: "POST",
    body: { path, name: name ?? "", create, parent },
  });
  if (isRecord(raw) && Array.isArray(raw.workspaces)) {
    return narrowWorkspacesResponse(raw);
  }
  return listWorkspaces();
}

/** Create a nested sub-workspace folder (multi-user / nested_workspaces mode). */
export async function createNestedWorkspace(
  folderName: string,
  options?: { displayName?: string; parent?: string },
): Promise<HermesWorkspacesResponse> {
  const segment = folderName.trim();
  if (!segment) {
    throw new Error("Workspace name is required");
  }
  const displayName = options?.displayName?.trim() || segment;
  const parent = options?.parent?.trim() || "";
  return addWorkspace(segment, displayName, true, parent);
}

/** True for the auto-managed profile workspace root (not editable/removable). */
export function isProtectedWorkspaceRoot(path: string): boolean {
  const token = path.trim().replace(/\/+$/, "") || "/workspace";
  return token === "/workspace";
}

/** POST /api/v1/workspaces/rename */
export async function renameWorkspace(
  path: string,
  name: string,
): Promise<HermesWorkspacesResponse> {
  const raw = await fetchJson<unknown>("/workspaces/rename", {
    method: "POST",
    body: { path, name },
  });
  if (isRecord(raw) && Array.isArray(raw.workspaces)) {
    return narrowWorkspacesResponse(raw);
  }
  return listWorkspaces();
}

/** POST /api/v1/workspaces/remove */
export async function removeWorkspace(path: string): Promise<HermesWorkspacesResponse> {
  const raw = await fetchJson<unknown>("/workspaces/remove", {
    method: "POST",
    body: { path },
  });
  if (isRecord(raw) && Array.isArray(raw.workspaces)) {
    return narrowWorkspacesResponse(raw);
  }
  return listWorkspaces();
}

/** POST /api/v1/workspaces/reorder */
export async function reorderWorkspaces(paths: string[]): Promise<HermesWorkspacesResponse> {
  const raw = await fetchJson<unknown>("/workspaces/reorder", {
    method: "POST",
    body: { paths },
  });
  if (isRecord(raw) && Array.isArray(raw.workspaces)) {
    return narrowWorkspacesResponse(raw);
  }
  return listWorkspaces();
}

/** GET /api/v1/list — one directory level in a session or composer workspace. */
export type ListDirectoryOptions = {
  sessionId?: string;
  workspace?: string;
  path?: string;
};

export async function listDirectory(
  options: ListDirectoryOptions | string,
  pathArg = ".",
): Promise<HermesListDirResponse> {
  let sessionId: string | undefined;
  let workspace: string | undefined;
  let path = pathArg;
  if (typeof options === "string") {
    sessionId = options;
  } else {
    sessionId = options.sessionId;
    workspace = options.workspace;
    path = options.path ?? ".";
  }
  const query: Record<string, string> = { path };
  const ws = workspace?.trim();
  if (ws) {
    query.workspace = ws;
  } else if (sessionId) {
    query.session_id = sessionId;
  }
  const raw = await fetchJson<unknown>("/list", { query });
  return narrowListDirResponse(raw);
}

/** Narrow GET /file JSON to a typed text read response (M20). */
export function narrowReadFileResponse(
  value: unknown,
  fallbackPath = "",
): HermesReadFileResponse | null {
  if (!isRecord(value) || typeof value.content !== "string") return null;
  const content = value.content;
  return {
    path: asString(value.path, fallbackPath),
    content,
    size: typeof value.size === "number" ? value.size : content.length,
    lines: typeof value.lines === "number" ? value.lines : content.split("\n").length,
  };
}

/** GET /api/v1/file — UTF-8 text file contents (M20). */
export async function readWorkspaceFile(
  sessionId: string | undefined,
  path: string,
  options?: Pick<WorkspaceFileRawOptions, "workspace">,
): Promise<HermesReadFileResponse> {
  const query: Record<string, string> = { path };
  const ws = options?.workspace?.trim();
  if (ws) {
    query.workspace = ws;
  } else if (sessionId?.trim()) {
    query.session_id = sessionId.trim();
  }
  const raw = await fetchJson<unknown>("/file", { query });
  const narrowed = narrowReadFileResponse(raw, path);
  if (!narrowed) {
    throw new Error("Invalid file read response");
  }
  return narrowed;
}

/** @deprecated Prefer `readWorkspaceFile`. */
export const readFile = readWorkspaceFile;

/** POST /api/v1/file/save — overwrite an existing workspace file. */
export async function saveFile(
  sessionId: string | undefined,
  path: string,
  content: string,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  const body: Record<string, unknown> = { path, content };
  applyWorkspaceMutationTarget(body, sessionId, options);
  return fetchJson<HermesFileMutationResponse>("/file/save", {
    method: "POST",
    body,
  });
}

export type WorkspaceFileMutationOptions = {
  workspace?: string;
};

function applyWorkspaceMutationTarget(
  body: Record<string, unknown>,
  sessionId: string | undefined,
  options?: WorkspaceFileMutationOptions,
): void {
  const ws = options?.workspace?.trim();
  if (ws) {
    body.workspace = ws;
  } else if (sessionId?.trim()) {
    body.session_id = sessionId.trim();
  }
}

/** POST /api/v1/file/delete */
export async function deleteFile(
  sessionId: string | undefined,
  path: string,
  recursive = false,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  const body: Record<string, unknown> = { path, recursive };
  applyWorkspaceMutationTarget(body, sessionId, options);
  return fetchJson<HermesFileMutationResponse>("/file/delete", {
    method: "POST",
    body,
  });
}

/** POST /api/v1/file/rename — same-directory rename only. */
export async function renameFile(
  sessionId: string | undefined,
  path: string,
  newName: string,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  const body: Record<string, unknown> = { path, new_name: newName };
  applyWorkspaceMutationTarget(body, sessionId, options);
  return fetchJson<HermesFileMutationResponse>("/file/rename", {
    method: "POST",
    body,
  });
}

/** POST /api/v1/file/create */
export async function createFile(
  sessionId: string | undefined,
  path: string,
  content = "",
  options?: ({ encoding?: "utf-8" | "base64" } & WorkspaceFileMutationOptions),
): Promise<HermesFileMutationResponse> {
  const body: Record<string, string> = { path, content };
  applyWorkspaceMutationTarget(body, sessionId, options);
  if (options?.encoding === "base64") {
    body.encoding = "base64";
  }
  return fetchJson<HermesFileMutationResponse>("/file/create", {
    method: "POST",
    body,
  });
}

function isLikelyTextUpload(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return [
    "md",
    "markdown",
    "txt",
    "json",
    "yaml",
    "yml",
    "xml",
    "html",
    "htm",
    "css",
    "js",
    "ts",
    "tsx",
    "jsx",
    "py",
    "sh",
    "bash",
    "csv",
    "env",
    "toml",
    "ini",
    "log",
  ].includes(ext);
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Failed to read file"));
        return;
      }
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

/** Create a workspace file from a browser File (text or binary via base64). */
export async function createWorkspaceFileFromUpload(
  sessionId: string | undefined,
  relPath: string,
  file: File,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  if (isLikelyTextUpload(file)) {
    const content = await file.text();
    return createFile(sessionId, relPath, content, options);
  }
  const content = await readFileAsBase64(file);
  return createFile(sessionId, relPath, content, { encoding: "base64", ...options });
}

/** POST /api/v1/file/create-dir */
export async function createDirectory(
  sessionId: string | undefined,
  path: string,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  const body: Record<string, unknown> = { path };
  applyWorkspaceMutationTarget(body, sessionId, options);
  return fetchJson<HermesFileMutationResponse>("/file/create-dir", {
    method: "POST",
    body,
  });
}

function buildFileQuery(
  sessionId: string | undefined,
  path: string,
  options?: WorkspaceFileRawOptions,
): Record<string, string> {
  const query: Record<string, string> = { path };
  const ws = options?.workspace?.trim();
  if (ws) {
    query.workspace = ws;
  } else if (sessionId?.trim()) {
    query.session_id = sessionId.trim();
  }
  if (options?.inline) query.inline = "1";
  if (options?.download) query.download = "1";
  return query;
}

/** Build same-origin URL for GET /file/raw (binary download / inline preview). */
export function fileRawUrl(
  sessionId: string | undefined,
  path: string,
  options?: WorkspaceFileRawOptions,
): string {
  return buildApiUrl("/file/raw", buildFileQuery(sessionId, path, options));
}

/** Build same-origin URL for GET /file/view (HTML/PDF top-level inline tab). */
export function fileViewUrl(
  sessionId: string | undefined,
  path: string,
  options?: Pick<WorkspaceFileRawOptions, "workspace">,
): string {
  const query: Record<string, string> = { path };
  const ws = options?.workspace?.trim();
  if (ws) {
    query.workspace = ws;
  } else if (sessionId?.trim()) {
    query.session_id = sessionId.trim();
  }
  return buildApiUrl("/file/view", query);
}

/** URL to open a workspace file in a new browser tab (HTML via /file/view, PDF via /file/raw). */
export function fileOpenInBrowserUrl(
  sessionId: string | undefined,
  path: string,
  options?: Pick<WorkspaceFileRawOptions, "workspace">,
): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") {
    return fileRawUrl(sessionId, path, { inline: true, ...options });
  }
  return fileViewUrl(sessionId, path, options);
}

/** GET /api/v1/file/raw — binary bytes for preview or download (M20). */
export async function readWorkspaceFileRaw(
  sessionId: string | undefined,
  path: string,
  options?: WorkspaceFileRawOptions,
): Promise<Blob> {
  return fetchBlob("/file/raw", {
    query: buildFileQuery(sessionId, path, options),
  });
}

/** GET /api/v1/file/view — inline HTML/PDF for top-level browser tab (M20). */
export async function readWorkspaceFileView(
  sessionId: string,
  path: string,
): Promise<Blob> {
  return fetchBlob("/file/view", {
    query: { session_id: sessionId, path },
  });
}

/** @deprecated Prefer `readWorkspaceFileRaw`. */
export const fetchFileBlob = readWorkspaceFileRaw;

/** Split workspace-relative path into parent dir + basename. */
export function splitWorkspacePath(relPath: string): { dirPath?: string; name: string } {
  const normalized = relPath.replace(/\\/g, "/").replace(/^\.\//, "");
  const lastSlash = normalized.lastIndexOf("/");
  if (lastSlash === -1) {
    return { name: normalized };
  }
  const dir = normalized.slice(0, lastSlash);
  return {
    dirPath: dir || undefined,
    name: normalized.slice(lastSlash + 1),
  };
}

/** POST /api/v1/file/move — move a file or folder to another directory. */
export async function moveFile(
  sessionId: string | undefined,
  sourcePath: string,
  destDirPath: string | undefined,
  destName?: string,
  options?: WorkspaceFileMutationOptions,
): Promise<HermesFileMutationResponse> {
  const source = splitWorkspacePath(sourcePath);
  const targetName = destName ?? source.name;
  const destParent = destDirPath?.replace(/^\.\//, "").replace(/\/$/, "") ?? "";
  const sourceParent = source.dirPath ?? "";

  if (destParent === sourceParent && targetName === source.name) {
    return { ok: true, path: sourcePath };
  }

  if (destParent === sourceParent) {
    return renameFile(sessionId, sourcePath, targetName, options);
  }

  const body: Record<string, unknown> = {
    path: sourcePath,
    dest_dir: destParent || undefined,
  };
  if (destName) {
    body.new_name = destName;
  }
  applyWorkspaceMutationTarget(body, sessionId, options);
  return fetchJson<HermesFileMutationResponse>("/file/move", {
    method: "POST",
    body,
  });
}

/** Immutably attach loaded children to a folder node in the tree. */
export function setTreeChildren(
  nodes: FileNode[],
  folderPath: string,
  children: FileNode[],
): FileNode[] {
  return nodes.map((node) => {
    if (node.id === folderPath) {
      return { ...node, children };
    }
    if (node.children?.length) {
      return {
        ...node,
        children: setTreeChildren(node.children, folderPath, children),
      };
    }
    return node;
  });
}

/** Update cached content on a file node after read. */
export function setTreeNodeContent(
  nodes: FileNode[],
  filePath: string,
  content: string,
): FileNode[] {
  return nodes.map((node) => {
    if (node.id === filePath) {
      return { ...node, content };
    }
    if (node.children?.length) {
      return { ...node, children: setTreeNodeContent(node.children, filePath, content) };
    }
    return node;
  });
}
