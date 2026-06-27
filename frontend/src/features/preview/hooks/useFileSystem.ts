import { useCallback, useEffect, useRef, useState } from "react";
import { HermesApiError } from "@/lib/api";
import { useLanguage } from "@/hooks/useLanguage";
import { FileNode } from "../components/FileTreeItem";
import {
  flattenVisibleFiles,
  rangeSelectPaths,
} from "../utils/fileTreeSelection";
import {
  listDirectory,
  mapEntriesToFileNodes,
  setTreeChildren,
  setTreeNodeContent,
} from "@/services/hermes/workspace";

export type FileSelectModifiers = {
  shiftKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
};

export type UseFileSystemOptions = {
  /** Hermes session id (sidebar chat id). */
  sessionId?: string | null;
  /** Workspace bound on the session server-side (fallback for GET /list). */
  sessionWorkspace?: string | null;
  /** Composer-selected workspace; lists directly without session bind. */
  workspacePath?: string | null;
  /** When false, skip loads until the session exists on the server. */
  sessionReady?: boolean;
  /** Poll interval while active (ms). 0 disables polling. */
  pollIntervalMs?: number;
  /** When false, skip loads (e.g. files tab inactive). */
  enabled?: boolean;
};

function treeStructureSignature(nodes: FileNode[]): string {
  return JSON.stringify(
    nodes.map((node) => ({
      id: node.id,
      name: node.name,
      type: node.type,
      children: node.children ? treeStructureSignature(node.children) : undefined,
    })),
  );
}

export const useFileSystem = (options: UseFileSystemOptions = {}) => {
  const { t } = useLanguage();
  const {
    sessionId,
    sessionWorkspace,
    workspacePath,
    sessionReady = true,
    pollIntervalMs = 3000,
    enabled = true,
  } = options;

  const composerWorkspace =
    typeof workspacePath === "string" ? workspacePath.trim() : "";
  const boundWorkspace =
    typeof sessionWorkspace === "string" ? sessionWorkspace.trim() : "";
  const listByWorkspace = Boolean(composerWorkspace);
  const listWorkspace = composerWorkspace || boundWorkspace;
  const canList =
    enabled &&
    Boolean(listWorkspace) &&
    (listByWorkspace || (Boolean(sessionId) && sessionReady));

  const [fileSystem, setFileSystem] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<FileNode | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(() => new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const dirCacheRef = useRef<Map<string, FileNode[]>>(new Map());
  const expandedPathsRef = useRef(expandedPaths);
  const fileSystemRef = useRef(fileSystem);
  const selectionAnchorRef = useRef<string | null>(null);
  expandedPathsRef.current = expandedPaths;
  fileSystemRef.current = fileSystem;

  const cacheKey = useCallback(
    (dirPath: string) => `${listWorkspace}:${dirPath}`,
    [listWorkspace],
  );

  useEffect(() => {
    setExpandedPaths(new Set());
    setSelectedFile(null);
    setSelectedNode(null);
    setSelectedPaths(new Set());
    selectionAnchorRef.current = null;
    dirCacheRef.current.clear();
  }, [composerWorkspace]);

  const loadDirectory = useCallback(
    async (dirPath: string, showSpinner: boolean): Promise<FileNode[]> => {
      if (!canList) return [];
      if (showSpinner) setIsLoading(true);
      try {
        const data = await listDirectory({
          workspace: listByWorkspace ? composerWorkspace : undefined,
          sessionId: listByWorkspace ? undefined : sessionId ?? undefined,
          path: dirPath,
        });
        const nodes = mapEntriesToFileNodes(data.entries);
        dirCacheRef.current.set(cacheKey(dirPath), nodes);
        setLoadError(null);
        return nodes;
      } catch (err) {
        console.error("Failed to list workspace directory", dirPath, err);
        const message =
          err instanceof HermesApiError && err.status === 403
            ? t("chat.workspaceNotAllowed")
            : err instanceof HermesApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Failed to load files";
        setLoadError(message);
        return [];
      } finally {
        if (showSpinner) setIsLoading(false);
      }
    },
    [canList, composerWorkspace, listByWorkspace, sessionId, cacheKey, t],
  );

  const refresh = useCallback(
    async (showSpinner = true, force = false) => {
      if (!canList) {
        setFileSystem([]);
        setSelectedFile(null);
        setSelectedNode(null);
        setSelectedPaths(new Set());
        selectionAnchorRef.current = null;
        setLoadError(null);
        dirCacheRef.current.clear();
        return;
      }
      setLoadError(null);
      if (showSpinner || force) {
        dirCacheRef.current.clear();
      }
      const rootNodes = await loadDirectory(".", showSpinner);
      const expanded = [...expandedPathsRef.current];

      let tree = rootNodes;
      for (const dirPath of expanded) {
        const children = await loadDirectory(dirPath, false);
        tree = setTreeChildren(tree, dirPath, children);
      }

      setFileSystem((prev) => {
        if (force) return tree;
        const prevSig = treeStructureSignature(prev);
        const nextSig = treeStructureSignature(tree);
        return prevSig === nextSig ? prev : tree;
      });
    },
    [canList, loadDirectory],
  );

  useEffect(() => {
    if (!enabled) {
      setFileSystem([]);
      setSelectedFile(null);
      setSelectedNode(null);
      setSelectedPaths(new Set());
      selectionAnchorRef.current = null;
      setLoadError(null);
      setIsLoading(false);
      dirCacheRef.current.clear();
      return;
    }
    void refresh(true);
  }, [
    composerWorkspace,
    sessionId,
    sessionWorkspace,
    sessionReady,
    enabled,
    refresh,
  ]);

  useEffect(() => {
    if (!canList || !pollIntervalMs) return;
    const interval = window.setInterval(() => {
      void refresh(false);
    }, pollIntervalMs);
    return () => window.clearInterval(interval);
  }, [canList, pollIntervalMs, refresh]);

  const ensureFolderChildren = useCallback(
    async (folderPath: string) => {
      if (dirCacheRef.current.has(cacheKey(folderPath))) {
        const cached = dirCacheRef.current.get(cacheKey(folderPath))!;
        setFileSystem((prev) => setTreeChildren(prev, folderPath, cached));
        return;
      }
      const children = await loadDirectory(folderPath, false);
      setFileSystem((prev) => setTreeChildren(prev, folderPath, children));
    },
    [loadDirectory, cacheKey],
  );

  const toggleFolder = useCallback(
    (path: string) => {
      setExpandedPaths((prev) => {
        const next = new Set(prev);
        const willExpand = !next.has(path);
        if (willExpand) {
          next.add(path);
          void ensureFolderChildren(path);
        } else {
          next.delete(path);
        }
        return next;
      });
    },
    [ensureFolderChildren],
  );

  const clearSelection = useCallback(() => {
    setSelectedPaths(new Set());
    selectionAnchorRef.current = null;
  }, []);

  const togglePathSelection = useCallback((path: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    selectionAnchorRef.current = path;
  }, []);

  const selectFile = useCallback(
    (path: string, node: FileNode, modifiers?: FileSelectModifiers) => {
      if (modifiers?.shiftKey) {
        const anchor = selectionAnchorRef.current ?? path;
        const visible = flattenVisibleFiles(
          fileSystemRef.current,
          expandedPathsRef.current,
        );
        const range = rangeSelectPaths(visible, anchor, path);
        setSelectedPaths((prev) => {
          const next =
            modifiers.ctrlKey || modifiers.metaKey
              ? new Set(prev)
              : new Set<string>();
          for (const item of range) next.add(item);
          return next;
        });
        selectionAnchorRef.current = anchor;
        return;
      }

      if (modifiers?.ctrlKey || modifiers?.metaKey) {
        togglePathSelection(path);
        selectionAnchorRef.current = path;
        return;
      }

      setSelectedFile(path);
      setSelectedNode(node);
      selectionAnchorRef.current = path;
      setSelectedPaths(new Set());
    },
    [togglePathSelection],
  );

  const patchNodeContent = useCallback((filePath: string, content: string) => {
    setFileSystem((prev) => setTreeNodeContent(prev, filePath, content));
    setSelectedNode((prev) => (prev?.id === filePath ? { ...prev, content } : prev));
  }, []);

  return {
    fileSystem,
    setFileSystem,
    selectedFile,
    selectedNode,
    selectedPaths,
    setSelectedFile,
    setSelectedNode,
    expandedPaths,
    isLoading,
    loadError,
    setLoadError,
    toggleFolder,
    selectFile,
    togglePathSelection,
    clearSelection,
    refresh,
    patchNodeContent,
    hasSessionWorkspace: Boolean(listWorkspace),
    hasComposerWorkspace: listByWorkspace,
    canAccessWorkspaceFiles: canList,
  };
};
