import { fetchJson } from "@/lib/api";

export type HermesWorkspace = {
  path: string;
  name?: string | null;
  [key: string]: unknown;
};

export type HermesDirectoryEntry = {
  path: string;
  name: string;
  [key: string]: unknown;
};

const SAFE_WORKSPACES: { workspaces: HermesWorkspace[]; nested_workspaces?: boolean } = { workspaces: [] };

export async function listWorkspaces() {
  try {
    return await fetchJson<{ workspaces: HermesWorkspace[]; nested_workspaces?: boolean }>("/workspaces");
  } catch {
    return SAFE_WORKSPACES;
  }
}

export async function createFile() { return {}; }
export async function createDirectory() { return {}; }
export async function createWorkspaceFileFromUpload() { return {}; }
export async function deleteFile() { return {}; }
export async function fetchFileBlob() { return new Blob(); }
export function fileOpenInBrowserUrl() { return ""; }
export async function moveFile() { return {}; }
export async function readFile() { return ""; }
export async function renameFile() { return {}; }
export async function saveFile() { return {}; }

export async function createNestedWorkspace(name: string, payload: Record<string, unknown>) {
  return fetchJson("/workspaces/add", { method: "POST", body: { name, ...payload } });
}

export async function addWorkspace() { return {}; }

export function findWorkspaceInRegistry(workspaces: HermesWorkspace[] | undefined, target: string): HermesWorkspace | null {
  if (!Array.isArray(workspaces) || !target) return null;
  return workspaces.find((w) => w.path === target) ?? null;
}

export function resolveAllowedComposerWorkspace(value?: string | null, registry?: { workspaces?: HermesWorkspace[] }) {
  const path = value?.trim() ?? "";
  if (!path) return { path: "", matched: false };
  const match = findWorkspaceInRegistry(registry?.workspaces, path);
  return { path: match?.path ?? path, matched: Boolean(match) };
}

export async function switchComposerWorkspace(opts: { path?: string; [key: string]: unknown }) {
  return { path: opts.path ?? "" };
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

export async function listDirectory() {
  return fetchJson("/workspace/list-directory");
}

export function fileRawUrl(_sessionId: string | undefined, filePath: string, _opts?: Record<string, unknown>) {
  return filePath;
}

export async function readWorkspaceFile(_sessionId: string | undefined, rel: string, _opts?: Record<string, unknown>) {
  return fetchJson("/workspace/read-file", { query: { path: rel } });
}

export function setTreeNodeContent<T>(tree: T, _filePath: string, _content: string): T {
  return tree;
}

export function mapEntriesToFileNodes<T>(entries: T): T {
  return entries;
}

export function setTreeChildren<T>(tree: T): T {
  return tree;
}
