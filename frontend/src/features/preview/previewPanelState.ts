export type PreviewPanelView =
  | "no-workspace"
  | "waiting-session"
  | "waiting-bind"
  | "loading"
  | "no-files"
  | "tree"
  | "error";

/** Resolve which empty/loading state the Generated Files panel should show. */
export function resolvePreviewPanelView(input: {
  chatId?: string | null;
  sessionReady: boolean;
  hasSessionWorkspace: boolean;
  /** Composer workspace selected — list directly without session bind. */
  hasComposerWorkspace?: boolean;
  /** Composer workspace selected but server session.workspace not synced yet. */
  workspaceBindPending?: boolean;
  isFilesLoading: boolean;
  fileCount: number;
  loadError: string | null;
}): PreviewPanelView {
  const {
    chatId,
    sessionReady,
    hasSessionWorkspace,
    hasComposerWorkspace = false,
    workspaceBindPending = false,
    isFilesLoading,
    fileCount,
    loadError,
  } = input;

  if (chatId && workspaceBindPending && !hasComposerWorkspace) {
    return "waiting-bind";
  }
  if (
    chatId &&
    sessionReady &&
    !hasSessionWorkspace &&
    !hasComposerWorkspace
  ) {
    return "no-workspace";
  }
  if (
    chatId &&
    hasSessionWorkspace &&
    !sessionReady &&
    !hasComposerWorkspace
  ) {
    return "waiting-session";
  }
  if (isFilesLoading) {
    return "loading";
  }
  if (loadError) {
    return "error";
  }
  if (fileCount === 0) {
    return "no-files";
  }
  return "tree";
}
