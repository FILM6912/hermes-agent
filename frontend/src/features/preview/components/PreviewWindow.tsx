import { ConfirmModal } from "@/components/ConfirmModal";
import { InputModal } from "@/components/InputModal";
import React, { useState } from "react";
import { createPortal } from "react-dom";
import {
  Share2,
  PanelRightClose,
  Check,
  ArrowLeft,
  Copy,
  Eye,
  Code,
  Download,
  Save,
  Trash2,
  Loader2,
  Edit2,
  FilePlus,
  FolderPlus,
  Upload,
  RefreshCw,
  ListTodo,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";
import { toastMessage, useToast } from "@/components/toast/ToastProvider";
import { FileTreeItem, FileNode } from "./FileTreeItem";
import { useFileSystem } from "../hooks/useFileSystem";
import { resolvePreviewPanelView } from "../previewPanelState";
import type { PreviewPanelContentState } from "../previewPanelContent";
import { TodosToolList } from "./TodosToolList";
import { ToolDetailPanel } from "./ToolDetailPanel";
import {
  createDirectory as hermesCreateDirectory,
  createFile as hermesCreateFile,
  createWorkspaceFileFromUpload,
  deleteFile as hermesDeleteFile,
  fetchFileBlob,
  fileOpenInBrowserUrl,
  fileRawUrl,
  moveFile as hermesMoveFile,
  readFile as hermesReadFile,
  renameFile as hermesRenameFile,
  saveFile as hermesSaveFile,
} from "@/services/hermes/workspace";
import { FileContentRenderer } from "./FileContentRenderer";
import { useClipboard } from "../hooks/useClipboard";
import { useWindowResize } from "../hooks/useWindowResize";
import { getLanguageConfig } from "@/lib/languageUtils";
import {
  isPreviewableExtension,
  shouldSkipTextContentLoad,
} from "../utils/fileSystemViewer";
import { findNodesByPaths } from "../utils/fileTreeSelection";

interface PreviewWindowProps {
  isOpen?: boolean;
  onToggle?: () => void;
  isMobile?: boolean;
  isSidebarOpen?: boolean;
  isLoading?: boolean;
  chatId?: string;
  sessionReady?: boolean;
  sessionWorkspace?: string;
  /** Composer-selected workspace; lists files without session bind. */
  workspacePath?: string;
  workspaceBindPending?: boolean;
  filesListEnabled?: boolean;
  /** Create/bind session when adding files without an active chat (legacy parity). */
  ensureComposerSession?: (options?: {
    navigate?: boolean;
    activate?: boolean;
  }) => Promise<string | undefined>;
  panelContent?: PreviewPanelContentState;
  onBackToFiles?: () => void;
}

export const PreviewWindow: React.FC<PreviewWindowProps> = ({
  isOpen = true,
  onToggle,
  isMobile = false,
  isSidebarOpen = true,
  isLoading = false,
  chatId,
  sessionReady = true,
  sessionWorkspace = "",
  workspacePath = "",
  workspaceBindPending = false,
  filesListEnabled = true,
  ensureComposerSession,
  panelContent = { mode: "files" },
  onBackToFiles,
}) => {
  const { t } = useLanguage();
  const { isDark } = useTheme();
  const toast = useToast();
  const {
    fileSystem,
    selectedNode: selectedFile,
    setSelectedNode: setSelectedFile,
    expandedPaths,
    isLoading: isFilesLoading,
    loadError,
    setLoadError,
    selectedPaths,
    toggleFolder,
    selectFile,
    clearSelection,
    refresh: refreshFileTree,
    patchNodeContent,
    hasSessionWorkspace,
    hasComposerWorkspace,
    canAccessWorkspaceFiles,
  } = useFileSystem({
    sessionId: chatId,
    sessionWorkspace,
    workspacePath,
    sessionReady,
    enabled: filesListEnabled && isOpen,
    pollIntervalMs: 3000,
  });
  const selectedFilePath = selectedFile?.id ?? null;

  React.useEffect(() => {
    if (
      panelContent.mode === "todos" ||
      panelContent.mode === "tool-detail"
    ) {
      setSelectedFile(null);
    }
  }, [panelContent.mode, setSelectedFile]);

  const panelView = resolvePreviewPanelView({
    chatId,
    sessionReady,
    hasSessionWorkspace,
    hasComposerWorkspace,
    workspaceBindPending,
    isFilesLoading,
    fileCount: fileSystem.length,
    loadError,
  });
  const [editContent, setEditContent] = useState<string>("");
  const [viewMode, setViewMode] = useState<"code" | "preview">("preview");
  const [showShareTooltip, setShowShareTooltip] = useState(false);
  const [showSaveCheck, setShowSaveCheck] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [renamingNodeId, setRenamingNodeId] = useState<string | null>(null);
  const uploadInputRef = React.useRef<HTMLInputElement>(null);
  const [workspaceActionError, setWorkspaceActionError] = useState<string | null>(
    null,
  );
  const [uploadingWorkspace, setUploadingWorkspace] = useState(false);

  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    type: "danger" | "info";
    confirmText?: string;
    cancelText?: string;
  }>({
    isOpen: false,
    title: "",
    message: "",
    onConfirm: () => {},
    type: "info",
  });

  const [inputModal, setInputModal] = useState<{
    isOpen: boolean;
    title: string;
    initialValue: string;
    onConfirm: (value: string) => void;
    placeholder?: string;
    confirmText?: string;
    cancelText?: string;
  }>({
    isOpen: false,
    title: "",
    initialValue: "",
    onConfirm: () => {},
  });

  const { copied, copyToClipboard } = useClipboard();
  const { width, isResizing, startResizing } = useWindowResize(
    450,
    isSidebarOpen,
  );

  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    node: FileNode;
  } | null>(null);
  const contextMenuRef = React.useRef<HTMLDivElement>(null);
  const pendingDeleteRef = React.useRef<FileNode | null>(null);
  const pendingBulkDeleteRef = React.useRef<FileNode[]>([]);
  const normalizeLineEndings = (value: string) =>
    value.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  const canMutateWorkspace = canAccessWorkspaceFiles;

  const resolveSessionId = React.useCallback(
    async (options?: { navigate?: boolean }): Promise<string | null> => {
      if (chatId?.trim()) return chatId.trim();
      if (ensureComposerSession) {
        try {
          const id = await ensureComposerSession({
            navigate: options?.navigate ?? false,
          });
          return id?.trim() || null;
        } catch {
          return null;
        }
      }
      return null;
    },
    [chatId, ensureComposerSession],
  );

  const composerWs = workspacePath.trim();
  const listByWorkspace = hasComposerWorkspace;
  const [resolvedSessionId, setResolvedSessionId] = React.useState<string | null>(
    null,
  );
  const [resolvingPreviewSession, setResolvingPreviewSession] =
    React.useState(false);

  React.useEffect(() => {
    if (chatId?.trim() || listByWorkspace || !selectedFile?.id) {
      setResolvedSessionId(null);
      setResolvingPreviewSession(false);
      return;
    }
    let cancelled = false;
    setResolvingPreviewSession(true);
    void resolveSessionId({ navigate: false })
      .then((id) => {
        if (!cancelled) setResolvedSessionId(id?.trim() || null);
      })
      .finally(() => {
        if (!cancelled) setResolvingPreviewSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chatId, listByWorkspace, selectedFile?.id, resolveSessionId]);

  const fileAccessSessionId = chatId?.trim() || resolvedSessionId || undefined;
  const fileAccessWorkspace = listByWorkspace ? composerWs : undefined;
  const canPreviewFile =
    Boolean(selectedFile?.id) &&
    Boolean(fileAccessWorkspace || fileAccessSessionId);

  const resolveWorkspaceMutationTarget = React.useCallback(async () => {
    const ws = workspacePath.trim();
    const mutationOpts = ws ? { workspace: ws } : undefined;
    const sessionId = ws
      ? undefined
      : chatId?.trim() ||
        (await resolveSessionId({ navigate: false }))?.trim() ||
        undefined;
    if (!mutationOpts?.workspace && !sessionId) {
      return null;
    }
    return { sessionId, mutationOpts };
  }, [chatId, resolveSessionId, workspacePath]);

  const deleteWorkspaceNode = React.useCallback(
    async (node: FileNode) => {
      const target = await resolveWorkspaceMutationTarget();
      if (!target) {
        throw new Error(t("preview.needSession"));
      }
      if (!node.id) return;
      await hermesDeleteFile(
        target.sessionId,
        node.id,
        node.type === "folder",
        target.mutationOpts,
      );
    },
    [resolveWorkspaceMutationTarget, t],
  );

  const handleConfirmPendingDelete = React.useCallback(async () => {
    const node = pendingDeleteRef.current;
    if (!node) return;
    pendingDeleteRef.current = null;
    setWorkspaceActionError(null);
    await deleteWorkspaceNode(node);
    if (selectedFile && selectedFile.id === node.id) {
      setSelectedFile(null);
    }
    await refreshFileTree(true, true);
  }, [deleteWorkspaceNode, refreshFileTree, selectedFile, setSelectedFile]);

  const handleConfirmBulkDelete = React.useCallback(async () => {
    const nodes = pendingBulkDeleteRef.current;
    pendingBulkDeleteRef.current = [];
    if (!nodes.length) return;
    setWorkspaceActionError(null);
    for (const node of nodes) {
      await deleteWorkspaceNode(node);
    }
    if (selectedFile && nodes.some((node) => node.id === selectedFile.id)) {
      setSelectedFile(null);
    }
    clearSelection();
    await refreshFileTree(true, true);
  }, [
    clearSelection,
    deleteWorkspaceNode,
    refreshFileTree,
    selectedFile,
    setSelectedFile,
  ]);

  const confirmPendingBulkDelete = React.useCallback(async () => {
    try {
      await handleConfirmBulkDelete();
    } catch (error) {
      const msg =
        error instanceof Error ? error.message : t("preview.deleteFailed");
      setWorkspaceActionError(msg);
      toast.error(toastMessage(error));
      throw error;
    }
  }, [handleConfirmBulkDelete, t, toast]);

  const confirmPendingDelete = React.useCallback(async () => {
    try {
      await handleConfirmPendingDelete();
    } catch (error) {
      const msg =
        error instanceof Error ? error.message : t("preview.deleteFailed");
      setWorkspaceActionError(msg);
      toast.error(toastMessage(error));
      throw error;
    }
  }, [handleConfirmPendingDelete, t, toast]);

  const handlePromptNewFile = () => {
    if (!canMutateWorkspace) return;
    setInputModal({
      isOpen: true,
      title: t("preview.newFilePrompt"),
      initialValue: "",
      placeholder: "filename.txt",
      confirmText: t("preview.create"),
      cancelText: t("preview.cancel"),
      onConfirm: async (name) => {
        const target = await resolveWorkspaceMutationTarget();
        if (!target) {
          setWorkspaceActionError(t("preview.needSession"));
          return;
        }
        try {
          setWorkspaceActionError(null);
          await hermesCreateFile(target.sessionId, name, "", target.mutationOpts);
          await refreshFileTree();
          const node: FileNode = {
            id: name,
            name: name.split("/").pop() ?? name,
            type: "file",
            content: "",
          };
          handleFileSelect(node);
        } catch (error) {
          setWorkspaceActionError(
            error instanceof Error ? error.message : t("preview.uploadFailed"),
          );
        }
      },
    });
  };

  const handlePromptNewFolder = () => {
    if (!canMutateWorkspace) return;
    setInputModal({
      isOpen: true,
      title: t("preview.newFolderPrompt"),
      initialValue: "",
      placeholder: "folder-name",
      confirmText: t("preview.create"),
      cancelText: t("preview.cancel"),
      onConfirm: async (name) => {
        const target = await resolveWorkspaceMutationTarget();
        if (!target) {
          setWorkspaceActionError(t("preview.needSession"));
          return;
        }
        try {
          setWorkspaceActionError(null);
          await hermesCreateDirectory(
            target.sessionId,
            name,
            target.mutationOpts,
          );
          await refreshFileTree();
        } catch (error) {
          setWorkspaceActionError(
            error instanceof Error ? error.message : t("preview.uploadFailed"),
          );
        }
      },
    });
  };

  const handleWorkspaceUploadChange = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length || !canMutateWorkspace) return;

    const target = await resolveWorkspaceMutationTarget();
    if (!target) {
      setWorkspaceActionError(t("preview.needSession"));
      return;
    }

    setUploadingWorkspace(true);
    setWorkspaceActionError(null);
    try {
      for (const file of files) {
        await createWorkspaceFileFromUpload(
          target.sessionId,
          file.name,
          file,
          target.mutationOpts,
        );
      }
      await refreshFileTree();
    } catch (error) {
      setWorkspaceActionError(
        error instanceof Error ? error.message : t("preview.uploadFailed"),
      );
    } finally {
      setUploadingWorkspace(false);
    }
  };

  const handleFileSelect = async (node: FileNode) => {
    setSelectedFile(node);
    setLoadError(null);
    setSaveStatus("idle");
    setSaveError(null);
    
    // Determine file type
    const ext = node.name.split(".").pop()?.toLowerCase();
    const isBinary = ["png", "jpg", "jpeg", "gif", "webp"].includes(ext || "");
    const isImage = ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext || "");
    const skipContentLoad = shouldSkipTextContentLoad(ext);
    
    const blobToDataURL = (blob: Blob): Promise<string> =>
      new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          const result = reader.result;
          if (typeof result === "string") resolve(result);
          else reject(new Error("Failed to convert blob to data URL"));
        };
        reader.onerror = () => reject(new Error("Failed to read blob"));
        reader.readAsDataURL(blob);
      });
    
    let content = node.content;
    
    // Check if we need to reload content
    // Reload if:
  // - No content
  // - Binary content is not a URL (blob:, http(s):, data:)
  const looksLikeUrl = (s: string) => s.startsWith("blob:") || s.startsWith("http://") || s.startsWith("https://") || s.startsWith("data:");
  const needsReload =
    !skipContentLoad &&
    (!content || (isBinary && !looksLikeUrl(content)));

    if (needsReload && node.id) {
      const access = listByWorkspace
        ? { workspace: composerWs }
        : {
            sessionId:
              chatId?.trim() || (await resolveSessionId({ navigate: false }))?.trim(),
          };
      if (!access.workspace && !access.sessionId) return;

      const relPath = node.id;
      const rawOptions = access.workspace ? { workspace: access.workspace } : undefined;

      try {
        if (isBinary) {
          const blob = await fetchFileBlob(access.sessionId, relPath, {
            inline: isImage,
            ...rawOptions,
          });
          
          if (blob.type === 'application/json') {
             // This suggests an error response that was returned as a blob
             const text = await blob.text();
             console.error("Failed to download file, received JSON:", text);
             try {
               const error = JSON.parse(text);
               throw new Error(error.detail || error.error || "Failed to download file");
             } catch (e) {
               throw new Error("Failed to download file: " + text);
             }
          }
          
          content = await blobToDataURL(blob);
        } else {
          const response = await hermesReadFile(access.sessionId, relPath, rawOptions);
          content = response.content;
        }

        patchNodeContent(node.id, content ?? "");

        const nodeWithContent = { ...node, content };
        setSelectedFile(nodeWithContent);
      } catch (error) {
        console.error("Failed to load file content:", error);
        setLoadError(error instanceof Error ? error.message : "Failed to load file");
      }
    }

    setEditContent(content ? normalizeLineEndings(content) : "");
    
    if (isPreviewableExtension(ext)) setViewMode("preview");
    else setViewMode("code");
  };

  const selectedExt =
    selectedFile?.name.split(".").pop()?.toLowerCase() ?? "";
  const openInBrowserUrl =
    canPreviewFile && selectedFile?.id
      ? fileOpenInBrowserUrl(fileAccessSessionId, selectedFile.id, fileAccessWorkspace
          ? { workspace: fileAccessWorkspace }
          : undefined)
      : null;
  const inlinePreviewUrl =
    canPreviewFile && selectedFile?.id
      ? fileRawUrl(fileAccessSessionId, selectedFile.id, {
          inline: true,
          ...(fileAccessWorkspace ? { workspace: fileAccessWorkspace } : {}),
        })
      : null;
  const htmlPreviewState: "ready" | "loading" | "unavailable" = inlinePreviewUrl
    ? "ready"
    : resolvingPreviewSession
      ? "loading"
      : "unavailable";
  const canOpenInBrowser = Boolean(
    openInBrowserUrl &&
      ["html", "htm", "pdf"].includes(selectedExt),
  );

  const handleSaveContent = async () => {
    if (!selectedFile?.id) return;

    const target = await resolveWorkspaceMutationTarget();
    if (!target) {
      setSaveStatus("error");
      setSaveError(t("preview.needSession"));
      return;
    }

    setSaveStatus("saving");
    setSaveError(null);

    try {
      const normalizedContent = normalizeLineEndings(editContent);
      await hermesSaveFile(
        target.sessionId,
        selectedFile.id,
        normalizedContent,
        target.mutationOpts,
      );

      const readOpts = target.mutationOpts?.workspace
        ? { workspace: target.mutationOpts.workspace }
        : undefined;
      const refreshed = await hermesReadFile(
        target.sessionId,
        selectedFile.id,
        readOpts,
      );
      const refreshedContent = normalizeLineEndings(refreshed.content || "");
      setEditContent(refreshedContent);
      patchNodeContent(selectedFile.id, refreshedContent);
      setSelectedFile((prev) => (prev ? { ...prev, content: refreshedContent } : null));
      setViewMode("code");
      setSaveStatus("saved");
      setShowSaveCheck(true);
      setTimeout(() => {
        setShowSaveCheck(false);
        setSaveStatus("idle");
      }, 2000);
    } catch (error) {
      console.error("Failed to save file:", error);
      setSaveStatus("error");
      setSaveError(error instanceof Error ? error.message : "Failed to save file");
    }
  };

  const handleDeleteFile = () => {
    if (!selectedFile) return;
    pendingDeleteRef.current = selectedFile;

    setConfirmModal({
      isOpen: true,
      title: t("preview.deleteFile"),
      message: t("preview.deleteFileConfirm").replace("{name}", selectedFile.name),
      type: "danger",
      confirmText: t("preview.delete"),
      cancelText: t("preview.cancel"),
      onConfirm: confirmPendingDelete,
    });
  };

  const handleCopy = async () => {
    const text =
      viewMode === "code"
        ? editContent
        : (selectedFile?.content ?? editContent);
    if (!text?.trim()) {
      toast.error(t("preview.copyEmpty"));
      return;
    }
    const ok = await copyToClipboard(text);
    if (!ok) {
      toast.error(t("preview.copyFailed"));
    }
  };

  const handleDownload = async (node: FileNode | null) => {
    if (!node?.id || !canPreviewFile) return;
    try {
      const blob = await fetchFileBlob(
        fileAccessSessionId,
        node.id,
        {
          download: true,
          ...(fileAccessWorkspace ? { workspace: fileAccessWorkspace } : {}),
        },
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = node.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Failed to download file:", error);
    }
  };

  const handleShare = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({
          title: t("preview.shareTitle"),
          text: t("preview.shareText"),
          url: url,
        });
        return;
      } catch (e) {
        // Fallback to clipboard
      }
    }

    const success = await copyToClipboard(url);
    if (success) {
      setShowShareTooltip(true);
      setTimeout(() => setShowShareTooltip(false), 2000);
    }
  };

  const handleRenameNode = (node: FileNode) => {
    if (!node) return;
    setRenamingNodeId(node.id || null);
  };

  const handleRenameCancel = () => {
    setRenamingNodeId(null);
  };

  const handleRenameSubmit = async (node: FileNode, newName: string) => {
    setRenamingNodeId(null);
    if (!node || !newName || newName === node.name) return;

    const target = await resolveWorkspaceMutationTarget();
    if (!target) {
      setWorkspaceActionError(t("preview.needSession"));
      return;
    }

    try {
      if (!node.id) return;
      setWorkspaceActionError(null);
      await hermesRenameFile(
        target.sessionId,
        node.id,
        newName,
        target.mutationOpts,
      );
      await refreshFileTree(true, true);
    } catch (error) {
      const msg =
        error instanceof Error ? error.message : t("preview.renameFailed");
      setWorkspaceActionError(msg);
      toast.error(toastMessage(error));
      console.error("Failed to rename node:", error);
    }
  };

  const handleDeleteNode = (node: FileNode) => {
    if (!node) return;
    pendingDeleteRef.current = node;

    setConfirmModal({
      isOpen: true,
      title: t("preview.deleteFile"),
      message: t("preview.deleteFileConfirm").replace("{name}", node.name),
      type: "danger",
      confirmText: t("preview.delete"),
      cancelText: t("preview.cancel"),
      onConfirm: confirmPendingDelete,
    });
  };

  const handleDeleteSelected = () => {
    if (selectedPaths.size === 0) return;
    const nodes = findNodesByPaths(fileSystem, selectedPaths);
    if (!nodes.length) return;
    pendingBulkDeleteRef.current = nodes;

    setConfirmModal({
      isOpen: true,
      title: t("preview.deleteSelected"),
      message: t("preview.deleteSelectedConfirm").replace(
        "{count}",
        String(nodes.length),
      ),
      type: "danger",
      confirmText: t("preview.delete"),
      cancelText: t("preview.cancel"),
      onConfirm: confirmPendingBulkDelete,
    });
  };



  const handleFileDrop = async (
    sourceNode: FileNode,
    targetNode: FileNode | null,
  ) => {
    if (!sourceNode) return;

    // Prevent moving to itself
    if (targetNode && targetNode.id === sourceNode.id) return;

    const sourcePath = sourceNode.id;
    if (!sourcePath) return;

    const lastSlashIndex = sourcePath.lastIndexOf("/");
    const sourceDir =
      lastSlashIndex > -1 ? sourcePath.substring(0, lastSlashIndex) : undefined;

    const destDir =
      targetNode?.type === "folder"
        ? targetNode.id
        : targetNode
          ? (() => {
              const idx = targetNode.id?.lastIndexOf("/") ?? -1;
              return idx > -1 ? targetNode.id!.substring(0, idx) : undefined;
            })()
          : undefined;

    if (sourceDir === destDir) return;

    // Prevent moving folder into itself or its children
    if (
      sourceNode.type === "folder" &&
      destDir &&
      destDir.startsWith(sourcePath + "/")
    )
      return;

    const target = await resolveWorkspaceMutationTarget();
    if (!target) {
      setWorkspaceActionError(t("preview.needSession"));
      return;
    }

    try {
      setWorkspaceActionError(null);
      await hermesMoveFile(
        target.sessionId,
        sourcePath,
        destDir,
        undefined,
        target.mutationOpts,
      );
      if (selectedFile?.id === sourcePath) {
        const movedName = sourcePath.split("/").pop() ?? sourcePath;
        const newPath = destDir ? `${destDir}/${movedName}` : movedName;
        setSelectedFile((prev) =>
          prev ? { ...prev, id: newPath } : null,
        );
      }
      await refreshFileTree(true, true);
    } catch (error) {
      const msg =
        error instanceof Error ? error.message : t("preview.moveFailed");
      setWorkspaceActionError(msg);
      toast.error(toastMessage(error));
      console.error("Failed to move file:", error);
    }
  };

  const handleContextMenu = (e: React.MouseEvent, node: FileNode) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
  };

  React.useEffect(() => {
    if (!contextMenu) return;
    const close = (event: Event) => {
      const target = event.target;
      if (
        target instanceof Node &&
        contextMenuRef.current?.contains(target)
      ) {
        return;
      }
      setContextMenu(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextMenu(null);
    };
    window.addEventListener("pointerdown", close, true);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("pointerdown", close, true);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [contextMenu]);

  const handleFileTreeSelect = async (
    path: string,
    node: FileNode,
    event?: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean },
  ) => {
    selectFile(path, node, event);
    if (!event?.shiftKey && !event?.ctrlKey && !event?.metaKey) {
      handleFileSelect(node);
    }
  };

  const mobileClasses = `fixed inset-y-0 right-0 z-50 w-72 bg-white dark:bg-black border-l border-zinc-200 dark:border-zinc-900 flex flex-col transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isOpen ? "translate-x-0 pointer-events-auto" : "translate-x-full pointer-events-none"}`;
  const desktopClasses = `relative z-0 h-full min-w-0 max-w-full bg-zinc-50 dark:bg-black border-l border-zinc-200 dark:border-zinc-800 flex min-h-0 flex-col shrink overflow-hidden ${isOpen ? "opacity-100 pointer-events-auto" : "border-l-0 opacity-0 pointer-events-none"} ${isResizing ? "" : "transition-[width,opacity] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"}`;

  const showAlternatePanel =
    !selectedFile &&
    panelContent.mode !== "files" &&
    (panelContent.mode === "todos" || panelContent.mode === "tool-detail");

  const alternatePanelTitle =
    panelContent.mode === "todos"
      ? t("preview.todosTitle")
      : panelContent.mode === "tool-detail"
        ? panelContent.step.title ||
          panelContent.step.toolName ||
          t("process.toolExecution")
        : t("preview.generatedFiles");

  const panel = (
    <div
      className={isMobile ? mobileClasses : desktopClasses}
      style={
        !isMobile
          ? { width: isOpen ? width : 0, maxWidth: isOpen ? "100%" : undefined }
          : undefined
      }
      aria-hidden={!isOpen}
    >
      {!isMobile && (
        <div
          className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 z-50 transition-colors"
          onMouseDown={startResizing}
        />
      )}
      <div className="flex min-h-0 h-full w-full min-w-0 flex-col overflow-hidden">
        <div className="h-14 flex items-center justify-end px-4 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleShare}
              className="text-muted-foreground hover:text-foreground relative"
              title={t("preview.share")}
            >
              {showShareTooltip ? (
                <Check className="w-4 h-4 text-emerald-500" />
              ) : (
                <Share2 className="w-4 h-4" />
              )}
              {showShareTooltip && (
                <div className="absolute top-full right-0 mt-2 px-3 py-1.5 bg-popover text-popover-foreground text-xs rounded-lg shadow-lg whitespace-nowrap z-50 animate-in fade-in slide-in-from-top-1">
                  {t("preview.shareSuccess")}
                </div>
              )}
            </button>
            <button
              type="button"
              onClick={onToggle}
              className="text-muted-foreground hover:text-foreground"
            >
              <PanelRightClose className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-4 bg-muted/30 transition-colors duration-200">
            <div className="flex min-h-0 h-full w-full min-w-0 max-w-full flex-col overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800 bg-background shadow-xl transition-colors duration-200">
              {selectedFile ? (
                <div className="flex min-h-0 h-full w-full min-w-0 flex-col overflow-hidden bg-background transition-colors">
                  <div className="relative z-50 flex shrink-0 flex-col gap-1.5 border-b border-zinc-200 dark:border-zinc-800 bg-muted px-3 py-2 transition-colors duration-200">
                    <div className="flex min-w-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setSelectedFile(null)}
                        className="flex shrink-0 items-center gap-1.5 rounded px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      >
                        <ArrowLeft className="w-3.5 h-3.5" /> {t("preview.back")}
                      </button>
                      <div className="flex shrink-0 rounded-lg border border-zinc-200 bg-muted p-0.5 dark:border-zinc-800">
                        <button
                          type="button"
                          onClick={() => setViewMode("code")}
                          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] transition-all ${viewMode === "code" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                        >
                          <Code className="w-3 h-3" /> {t("preview.code")}
                        </button>
                        {isPreviewableExtension(
                          selectedFile.name.split(".").pop()?.toLowerCase(),
                        ) && (
                          <button
                            type="button"
                            onClick={() => setViewMode("preview")}
                            className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] transition-all ${viewMode === "preview" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                          >
                            <Eye className="w-3 h-3" /> {t("preview.previewMode")}
                          </button>
                        )}
                      </div>
                      <div className="ml-auto flex shrink-0 items-center gap-0.5">
                        {viewMode === "code" && (
                          <>
                            {saveStatus === "error" && saveError && (
                              <span
                                className="hidden max-w-[100px] truncate text-[10px] text-red-500 sm:inline"
                                title={saveError}
                              >
                                {saveError}
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={handleSaveContent}
                              disabled={saveStatus === "saving"}
                              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-emerald-500 disabled:opacity-50"
                              title={t("preview.save")}
                            >
                              {saveStatus === "saving" ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : showSaveCheck || saveStatus === "saved" ? (
                                <Check className="w-3.5 h-3.5 text-emerald-500" />
                              ) : (
                                <Save className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </>
                        )}
                        <button
                          type="button"
                          onClick={() => handleDownload(selectedFile)}
                          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          title={t("preview.download")}
                        >
                          <Download className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={handleCopy}
                          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          title={t("preview.copy")}
                        >
                          {copied ? (
                            <Check className="w-3.5 h-3.5 text-emerald-500" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={handleDeleteFile}
                          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                          title={t("preview.deleteFile")}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="flex min-w-0 items-center gap-1.5 px-1 text-xs font-mono text-muted-foreground">
                      {canOpenInBrowser && openInBrowserUrl ? (
                        <a
                          href={openInBrowserUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex min-w-0 items-center gap-1.5 hover:text-foreground"
                          title={selectedFile.name}
                        >
                          {(() => {
                            const config = getLanguageConfig(selectedExt);
                            return (
                              <span
                                className={`shrink-0 ${
                                  !config.color ? "text-zinc-500 dark:text-zinc-400" : ""
                                }`}
                                style={{ color: config.color }}
                              >
                                {config.icon}
                              </span>
                            );
                          })()}
                          <span className="min-w-0 truncate underline-offset-2 group-hover:underline">
                            {selectedFile.name}
                          </span>
                        </a>
                      ) : (
                        <>
                          {(() => {
                            const config = getLanguageConfig(selectedExt);
                            return (
                              <span
                                className={`shrink-0 ${
                                  !config.color ? "text-zinc-500 dark:text-zinc-400" : ""
                                }`}
                                style={{ color: config.color }}
                              >
                                {config.icon}
                              </span>
                            );
                          })()}
                          <span className="min-w-0 truncate" title={selectedFile.name}>
                            {selectedFile.name}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="relative z-0 flex min-h-0 flex-1 flex-col overflow-hidden bg-background transition-colors duration-200">
                    <FileContentRenderer
                      selectedFile={selectedFile}
                      editContent={editContent}
                      viewMode={viewMode}
                      isDark={isDark}
                      onEditContentChange={setEditContent}
                      error={loadError}
                      inlinePreviewUrl={inlinePreviewUrl}
                      htmlPreviewState={htmlPreviewState}
                      openInBrowserUrl={openInBrowserUrl}
                    />
                  </div>
                </div>
              ) : showAlternatePanel ? (
                <div className="flex min-h-0 h-full w-full min-w-0 flex-col overflow-hidden">
                  <div className="sticky top-0 z-10 flex shrink-0 min-w-0 items-center gap-2 border-b border-zinc-200 bg-muted px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground transition-colors duration-200 dark:border-zinc-800">
                    <button
                      type="button"
                      onClick={onBackToFiles}
                      className="flex shrink-0 items-center gap-1.5 rounded px-2 py-1 text-xs normal-case text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      <ArrowLeft className="w-3.5 h-3.5" /> {t("preview.back")}
                    </button>
                    {panelContent.mode === "todos" ? (
                      <ListTodo className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                    ) : null}
                    <span className="min-w-0 truncate normal-case">{alternatePanelTitle}</span>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto bg-background">
                    {panelContent.mode === "todos" ? (
                      <div className="p-4">
                        <TodosToolList items={panelContent.items} />
                      </div>
                    ) : panelContent.mode === "tool-detail" ? (
                      <div className="p-4">
                        <ToolDetailPanel step={panelContent.step} />
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="flex min-h-0 h-full w-full min-w-0 flex-col overflow-hidden">
                  <div className="sticky top-0 z-10 flex shrink-0 min-w-0 items-center justify-between gap-2 border-b border-zinc-200 bg-muted px-3 py-2 text-xs font-medium uppercase tracking-wider text-muted-foreground transition-colors duration-200 dark:border-zinc-800 pointer-events-auto">
                    <span className="truncate">
                      {t("preview.generatedFiles")}
                    </span>
                    <div className="relative z-[60] flex shrink-0 items-center gap-0.5 pointer-events-auto">
                      {isLoading && (
                        <div className="flex items-center gap-1 text-primary animate-pulse mr-1">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          <span className="text-[10px] normal-case">
                            {t("preview.generating")}
                          </span>
                        </div>
                      )}
                      <button
                        type="button"
                        disabled={!canMutateWorkspace || uploadingWorkspace}
                        onClick={(e) => {
                          e.stopPropagation();
                          handlePromptNewFile();
                        }}
                        className="touch-manipulation p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed pointer-events-auto"
                        title={t("preview.newFile")}
                      >
                        <FilePlus className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={!canMutateWorkspace || uploadingWorkspace}
                        onClick={(e) => {
                          e.stopPropagation();
                          handlePromptNewFolder();
                        }}
                        className="touch-manipulation p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed pointer-events-auto"
                        title={t("preview.newFolder")}
                      >
                        <FolderPlus className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={!canMutateWorkspace || uploadingWorkspace}
                        onClick={(e) => {
                          e.stopPropagation();
                          uploadInputRef.current?.click();
                        }}
                        className="touch-manipulation p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed pointer-events-auto"
                        title={t("preview.uploadFile")}
                      >
                        {uploadingWorkspace ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Upload className="w-3.5 h-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void refreshFileTree(true, true);
                        }}
                        className="touch-manipulation p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent pointer-events-auto"
                        title={t("preview.refreshFiles")}
                      >
                        <RefreshCw
                          className={`w-3.5 h-3.5 ${isFilesLoading ? "animate-spin" : ""}`}
                        />
                      </button>
                      <input
                        ref={uploadInputRef}
                        type="file"
                        multiple
                        className="hidden"
                        onChange={(e) => void handleWorkspaceUploadChange(e)}
                      />
                    </div>
                  </div>
                  {workspaceActionError && (
                    <div className="px-3 py-1.5 text-[11px] text-red-600 dark:text-red-400 bg-red-500/5 border-b border-red-500/20">
                      {workspaceActionError}
                    </div>
                  )}
                  {selectedPaths.size > 0 && (
                    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-zinc-200 bg-indigo-500/5 px-3 py-1.5 text-[11px] text-indigo-700 dark:border-zinc-800 dark:text-indigo-300">
                      <span>
                        {t("preview.selectedCount").replace(
                          "{count}",
                          String(selectedPaths.size),
                        )}
                      </span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={handleDeleteSelected}
                          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-400"
                        >
                          <Trash2 className="h-3 w-3" />
                          {t("preview.deleteSelected")}
                        </button>
                        <button
                          type="button"
                          onClick={clearSelection}
                          className="rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                        >
                          {t("preview.clearSelection")}
                        </button>
                      </div>
                    </div>
                  )}
                  <div
                    className="relative z-0 min-h-0 min-w-0 max-w-full flex-1 overflow-x-hidden overflow-y-auto bg-background p-2 font-mono [contain:layout] transition-colors duration-200"
                    onDragOver={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      try {
                        const sourceNode = JSON.parse(
                          e.dataTransfer.getData("application/json"),
                        );
                        handleFileDrop(sourceNode, null);
                      } catch (err) {}
                    }}
                  >
                    {panelView === "no-workspace" ? (
                      <div className="text-xs text-zinc-500 text-center py-8 px-4 italic">
                        {t("chat.noWorkspace") || "No workspace bound to this session"}
                      </div>
                    ) : panelView === "waiting-session" ||
                      panelView === "waiting-bind" ||
                      panelView === "loading" ? (
                      <div className="space-y-1 p-2">
                        {[1, 2, 3, 4, 5].map((i) => (
                          <div
                            key={i}
                            className="flex items-center gap-2 py-1.5 px-2"
                          >
                            <div className="w-4 h-4 rounded bg-zinc-200 dark:bg-zinc-700 animate-pulse" />
                            <div
                              className="h-3 rounded bg-zinc-200 dark:bg-zinc-700 animate-pulse"
                              style={{ width: `${60 + Math.random() * 80}px` }}
                            />
                          </div>
                        ))}
                      </div>
                    ) : panelView === "no-files" ? (
                      <div className="text-xs text-zinc-500 text-center py-8 px-4 italic">
                        {t("preview.noFiles") || "No files in workspace"}
                      </div>
                    ) : panelView === "error" ? (
                      <div className="text-xs text-red-500 text-center py-8 px-4">
                        {loadError}
                      </div>
                    ) : (
                      fileSystem.map((node, idx) => (
                        <FileTreeItem
                          key={node.id || idx}
                          node={node}
                          level={0}
                          path={node.id ?? node.name}
                          selectedFile={selectedFilePath}
                          selectedPaths={selectedPaths}
                          onToggle={toggleFolder}
                          onSelect={handleFileTreeSelect}
                          onDelete={handleDeleteNode}
                          onRename={handleRenameNode}
                          onDownload={handleDownload}
                          onFileDrop={handleFileDrop}
                          onContextMenu={handleContextMenu}
                          expandedPaths={expandedPaths}
                          renamingNodeId={renamingNodeId}
                          onRenameSubmit={handleRenameSubmit}
                          onRenameCancel={handleRenameCancel}
                        />
                      ))
                    )}
                  </div>
                  
                  {contextMenu && createPortal(
                      <div
                        ref={contextMenuRef}
                        data-file-tree-context-menu
                        className="fixed z-[9999] min-w-[160px] bg-white dark:bg-zinc-800 rounded-lg shadow-xl border border-zinc-200 dark:border-zinc-700 py-1 animate-in fade-in zoom-in-95 duration-100"
                        style={{ left: contextMenu.x, top: contextMenu.y }}
                      >
                        {contextMenu.node.type === "file" && (
                          <button
                            onClick={() => {
                              handleDownload(contextMenu.node);
                              setContextMenu(null);
                            }}
                            className="w-full px-3 py-1.5 text-left text-sm text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-700 flex items-center gap-2"
                          >
                            <Download className="w-4 h-4 text-zinc-500" />
                            {t("preview.download")}
                          </button>
                        )}
                        
                        <button
                          onClick={() => {
                            handleRenameNode(contextMenu.node);
                            setContextMenu(null);
                          }}
                          className="w-full px-3 py-1.5 text-left text-sm text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-700 flex items-center gap-2"
                        >
                          <Edit2 className="w-4 h-4 text-zinc-500" />
                          {t("preview.rename")}
                        </button>
                        
                        <div className="my-1 border-t border-zinc-200 dark:border-zinc-700" />
                        
                        <button
                          onClick={() => {
                            handleDeleteNode(contextMenu.node);
                            setContextMenu(null);
                          }}
                          className="w-full px-3 py-1.5 text-left text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                        >
                          <Trash2 className="w-4 h-4" />
                          {t("preview.delete")}
                        </button>
                      </div>,
                    document.body
                  )}
                </div>
              )}
            </div>
        </div>
      </div>
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        onClose={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
        onConfirm={confirmModal.onConfirm}
        title={confirmModal.title}
        message={confirmModal.message}
        type={confirmModal.type}
        confirmText={confirmModal.confirmText}
        cancelText={confirmModal.cancelText}
      />
      <InputModal
        isOpen={inputModal.isOpen}
        onClose={() => setInputModal((prev) => ({ ...prev, isOpen: false }))}
        onConfirm={inputModal.onConfirm}
        title={inputModal.title}
        initialValue={inputModal.initialValue}
        placeholder={inputModal.placeholder}
        confirmText={inputModal.confirmText}
        cancelText={inputModal.cancelText}
      />
    </div>
  );

  // Overlay drawer must mount on body so fixed positioning is viewport-relative.
  if (isMobile && typeof document !== "undefined") {
    return createPortal(panel, document.body);
  }

  return panel;
};
