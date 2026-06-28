import { buildApiUrl, fetchBlob, fetchJson, HermesApiError } from "@/lib/api";
import type { FileNode } from "@/features/preview/components/FileTreeItem";
import type { ModelConfig } from "@/types";
import { modelProviderForHermes } from "@/services/hermes/models";

export type HermesWorkspace = {
  path: string;
  name?: string | null;
  [key: string]: unknown;
};

export type HermesDirEntry = {
  name: string;
  path: string;
  type: "file" | "dir" | "symlink";
  size?: number | null;
  mtime_ns?: number | null;
  is_dir?: boolean;
  target?: string;
};

export type WorkspaceMutationOpts = {
  workspace?: string;
};

const SAFE_WORKSPACES: { workspaces: HermesWorkspace[]; nested_workspaces?: boolean } = {
  workspaces: [],
};

export function isDirectoryEntry(entry: HermesDirEntry): boolean {
  return entry.type === "dir" || entry.is_dir === true;
}

export async function listWorkspaces() {
  try {
    return await fetchJson<{ workspaces: HermesWorkspace[]; nested_workspaces?: boolean }>(
      "/workspaces",
    );
  } catch {
    return SAFE_WORKSPACES;
  }
}

export function findWorkspaceInRegistry(
  workspaces: HermesWorkspace[] | undefined,
  target: string,
): HermesWorkspace | null {
  if (!Array.isArray(workspaces) || !target) return null;
  const normalized = target.trim();
  return (
    workspaces.find((w) => w.path === normalized || w.path === target) ?? null
  );
}

export function resolveAllowedComposerWorkspace(
  value?: string | null,
  registry?: { workspaces?: HermesWorkspace[] },
) {
  const path = value?.trim() ?? "";
  if (!path) return { path: "", matched: false };
  const match = findWorkspaceInRegistry(registry?.workspaces, path);
  return { path: match?.path ?? path, matched: Boolean(match) };
}

export function applyWorkspaceMutationTarget(
  sessionId: string | undefined,
  opts?: WorkspaceMutationOpts,
): Record<string, unknown> {
  const ws = opts?.workspace?.trim();
  if (ws) return { workspace: ws };
  const sid = sessionId?.trim();
  if (sid) return { session_id: sid };
  return {};
}

function mutationBody(
  sessionId: string | undefined,
  path: string,
  extra: Record<string, unknown> = {},
  opts?: WorkspaceMutationOpts,
): Record<string, unknown> {
  const base = applyWorkspaceMutationTarget(sessionId, opts);
  if (!base.workspace && !base.session_id) {
    throw new HermesApiError("session_id or workspace is required", 400);
  }
  return { ...base, path, ...extra };
}

export async function switchComposerWorkspace(opts: {
  path?: string;
  sessionId?: string;
  name?: string;
  modelConfig?: ModelConfig;
}) {
  const sessionId = opts.sessionId?.trim();
  const path = opts.path?.trim() ?? "";
  if (!sessionId) {
    throw new HermesApiError("session_id is required", 400);
  }
  if (!path) {
    return { path: "" };
  }
  const body: Record<string, unknown> = {
    session_id: sessionId,
    workspace: path,
  };
  const modelConfig = opts.modelConfig;
  const modelId = modelConfig?.modelId?.trim();
  if (modelId) body.model = modelId;
  const provider = modelConfig ? modelProviderForHermes(modelConfig) : undefined;
  if (provider) body.model_provider = provider;
  const data = await fetchJson<{ session?: { workspace?: string } }>("/session/update", {
    method: "POST",
    body,
  });
  const resolved =
    typeof data.session?.workspace === "string"
      ? data.session.workspace.trim()
      : path;
  return { path: resolved || path };
}

export async function createNestedWorkspace(name: string, payload: Record<string, unknown>) {
  return fetchJson("/workspaces/add", { method: "POST", body: { name, ...payload } });
}

export async function addWorkspace() {
  return {};
}

export async function removeWorkspace(path: string) {
  return fetchJson("/workspaces/remove", { method: "POST", body: { path } });
}

export async function renameWorkspace(path: string, name: string) {
  return fetchJson("/workspaces/rename", { method: "POST", body: { path, name } });
}

export function isProtectedWorkspaceRoot(path: string): boolean {
  return path === "/workspace" || path === "/";
}

export async function listDirectory(opts: {
  workspace?: string;
  sessionId?: string;
  path?: string;
} = {}) {
  const query: Record<string, string> = { path: opts.path ?? "." };
  const ws = opts.workspace?.trim();
  const sid = opts.sessionId?.trim();
  if (ws) query.workspace = ws;
  else if (sid) query.session_id = sid;
  return fetchJson<{ entries: HermesDirEntry[] }>("/list", { query });
}

export function fileRawUrl(
  sessionId: string | undefined,
  filePath: string,
  opts?: { workspace?: string; inline?: boolean; download?: boolean },
): string {
  const query: Record<string, string | boolean | undefined> = { path: filePath };
  const ws = opts?.workspace?.trim();
  const sid = sessionId?.trim();
  if (ws) query.workspace = ws;
  else if (sid) query.session_id = sid;
  if (opts?.inline) query.inline = "1";
  if (opts?.download) query.download = "1";
  return buildApiUrl("/file/raw", query);
}

export function fileOpenInBrowserUrl(
  sessionId: string | undefined,
  filePath: string,
  opts?: { workspace?: string },
): string {
  return fileRawUrl(sessionId, filePath, { ...opts, inline: true });
}

export async function readWorkspaceFile(
  sessionId: string | undefined,
  rel: string,
  opts?: WorkspaceMutationOpts,
) {
  return readFile(sessionId, rel, opts);
}

export async function readFile(
  sessionId: string | undefined,
  path: string,
  opts?: WorkspaceMutationOpts,
) {
  const query: Record<string, string> = { path };
  const ws = opts?.workspace?.trim();
  const sid = sessionId?.trim();
  if (ws) query.workspace = ws;
  else if (sid) query.session_id = sid;
  return fetchJson<{ content?: string; path?: string }>("/file", { query });
}

export async function fetchFileBlob(
  sessionId: string | undefined,
  path: string,
  opts?: { workspace?: string; inline?: boolean; download?: boolean },
) {
  const query: Record<string, string | boolean | undefined> = { path };
  const ws = opts?.workspace?.trim();
  const sid = sessionId?.trim();
  if (ws) query.workspace = ws;
  else if (sid) query.session_id = sid;
  if (opts?.inline) query.inline = "1";
  if (opts?.download) query.download = "1";
  return fetchBlob("/file/raw", { query });
}

export async function saveFile(
  sessionId: string | undefined,
  path: string,
  content: string,
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/save", {
    method: "POST",
    body: mutationBody(sessionId, path, { content }, opts),
  });
}

export async function createFile(
  sessionId: string | undefined,
  path: string,
  content = "",
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/create", {
    method: "POST",
    body: mutationBody(sessionId, path, { content }, opts),
  });
}

export async function createDirectory(
  sessionId: string | undefined,
  path: string,
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/create-dir", {
    method: "POST",
    body: mutationBody(sessionId, path, {}, opts),
  });
}

export async function deleteFile(
  sessionId: string | undefined,
  path: string,
  recursive = false,
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/delete", {
    method: "POST",
    body: mutationBody(sessionId, path, recursive ? { recursive: true } : {}, opts),
  });
}

export async function renameFile(
  sessionId: string | undefined,
  path: string,
  newName: string,
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/rename", {
    method: "POST",
    body: {
      ...applyWorkspaceMutationTarget(sessionId, opts),
      path,
      new_name: newName,
    },
  });
}

export async function moveFile(
  sessionId: string | undefined,
  path: string,
  destDir: string,
  _newName?: string,
  opts?: WorkspaceMutationOpts,
) {
  await fetchJson("/file/move", {
    method: "POST",
    body: {
      ...applyWorkspaceMutationTarget(sessionId, opts),
      path,
      dest_dir: destDir,
    },
  });
}

export async function createWorkspaceFileFromUpload(
  sessionId: string | undefined,
  path: string,
  file: File,
  opts?: WorkspaceMutationOpts,
) {
  const content = await file.text();
  await createFile(sessionId, path, content, opts);
}

function normalizeTreePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/$/, "");
}

export function mapEntriesToFileNodes(entries: HermesDirEntry[]): FileNode[] {
  return [...entries]
    .sort((a, b) => {
      const aDir = isDirectoryEntry(a);
      const bDir = isDirectoryEntry(b);
      if (aDir !== bDir) return aDir ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    })
    .map((entry) => ({
      id: entry.path,
      name: entry.name,
      type: isDirectoryEntry(entry) ? "folder" : "file",
      children: isDirectoryEntry(entry) ? [] : undefined,
    }));
}

export function setTreeChildren(
  tree: FileNode[],
  dirPath: string,
  children: FileNode[],
): FileNode[] {
  const target = normalizeTreePath(dirPath);
  if (!target || target === ".") return children;
  const update = (nodes: FileNode[]): FileNode[] =>
    nodes.map((node) => {
      const nodePath = normalizeTreePath(node.id ?? node.name);
      if (nodePath === target) {
        return { ...node, children, isOpen: true };
      }
      if (node.children?.length) {
        return { ...node, children: update(node.children) };
      }
      return node;
    });
  return update(tree);
}

export function setTreeNodeContent(
  tree: FileNode[],
  filePath: string,
  content: string,
): FileNode[] {
  const target = normalizeTreePath(filePath);
  const update = (nodes: FileNode[]): FileNode[] =>
    nodes.map((node) => {
      const nodePath = normalizeTreePath(node.id ?? node.name);
      if (nodePath === target) {
        return { ...node, content };
      }
      if (node.children?.length) {
        return { ...node, children: update(node.children) };
      }
      return node;
    });
  return update(tree);
}
