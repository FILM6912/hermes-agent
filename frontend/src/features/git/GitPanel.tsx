import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  GitBranch,
  Loader2,
  RefreshCw,
  Upload,
  Download,
  Check,
  Undo2,
} from "lucide-react";
import { HermesApiError } from "@/lib/api";
import {
  fetchGitBranches,
  fetchGitDiff,
  fetchGitStatus,
  gitCommit,
  gitCommitMessage,
  gitDiscard,
  gitCheckout,
  gitFetch,
  gitPull,
  gitPush,
  gitStage,
  gitUnstage,
  type GitFileEntry,
  type GitStatusPayload,
} from "./gitApi";

interface GitPanelProps {
  onBack: () => void;
  sessionId: string;
}

export const GitPanel: React.FC<GitPanelProps> = ({ onBack, sessionId }) => {
  const [status, setStatus] = useState<GitStatusPayload | null>(null);
  const [currentBranch, setCurrentBranch] = useState<string>("");
  const [branches, setBranches] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [diffText, setDiffText] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setError("No active session — open a chat first.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [statusRes, branchRes] = await Promise.all([
        fetchGitStatus(sessionId),
        fetchGitBranches(sessionId),
      ]);
      if (statusRes.error) throw new Error(statusRes.error);
      const git = statusRes.git;
      if (!git?.is_git) {
        setStatus(git ?? { is_git: false });
        setBranches([]);
        setCurrentBranch("");
        return;
      }
      setStatus(git);
      setCurrentBranch(git.branch ?? branchRes.branches?.current ?? "");
      const local = (branchRes.branches?.local ?? []).map((b) => b.name);
      setBranches(local);
    } catch (err) {
      const message =
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to load git status";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const loadDiff = useCallback(
    async (path: string, file?: GitFileEntry) => {
      setSelectedPath(path);
      setDiffText("");
      try {
        const kind = file?.staged && !file?.unstaged ? "staged" : "unstaged";
        const res = await fetchGitDiff(sessionId, path, kind);
        setDiffText(res.diff ?? res.error ?? "(no diff)");
      } catch (err) {
        setDiffText(err instanceof Error ? err.message : "Failed to load diff");
      }
    },
    [sessionId],
  );

  const runAction = async (action: () => Promise<unknown>) => {
    setActionPending(true);
    setError(null);
    try {
      await action();
      await refresh();
      if (selectedPath) {
        const file = status?.files?.find((f) => f.path === selectedPath);
        await loadDiff(selectedPath, file);
      }
    } catch (err) {
      setError(
        err instanceof HermesApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Git operation failed",
      );
    } finally {
      setActionPending(false);
    }
  };

  const files = status?.files ?? [];
  const totals = status?.totals;

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <GitBranch className="h-5 w-5 text-indigo-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Git</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            {status?.is_git
              ? `${currentBranch || "HEAD"} · ${totals?.changed ?? 0} changed`
              : "Workspace source control"}
          </p>
        </div>
        {status?.is_git && branches.length > 0 && (
          <select
            value={currentBranch}
            onChange={(e) => {
              const ref = e.target.value;
              void runAction(() => gitCheckout(sessionId, ref));
            }}
            disabled={actionPending}
            className="max-w-[160px] rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            aria-label="Branch"
          >
            {branches.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          onClick={() => void runAction(() => gitFetch(sessionId))}
          disabled={actionPending || !status?.is_git}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-2 py-1.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Fetch
        </button>
        <button
          type="button"
          onClick={() => void runAction(() => gitPull(sessionId))}
          disabled={actionPending || !status?.is_git}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-2 py-1.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          <Download className="h-3.5 w-3.5" />
          Pull
        </button>
        <button
          type="button"
          onClick={() => void runAction(() => gitPush(sessionId))}
          disabled={actionPending || !status?.is_git}
          className="inline-flex items-center gap-1 rounded-lg border border-zinc-200 px-2 py-1.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          <Upload className="h-3.5 w-3.5" />
          Push
        </button>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
          aria-label="Refresh"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </header>

      {!sessionId ? (
        <div className="flex flex-1 items-center justify-center p-8 text-sm text-zinc-500">
          Open a chat session to view workspace Git status.
        </div>
      ) : loading && !status ? (
        <div className="flex flex-1 items-center justify-center text-zinc-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading git status…
        </div>
      ) : !status?.is_git ? (
        <div className="flex flex-1 items-center justify-center p-8 text-sm text-zinc-500">
          This workspace is not a Git repository.
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="flex w-full shrink-0 flex-col border-b border-zinc-200 dark:border-zinc-800 lg:w-72 lg:border-b-0 lg:border-r">
            {error && (
              <div className="border-b border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
                {error}
              </div>
            )}
            <div className="overflow-y-auto p-2">
              {files.length === 0 ? (
                <div className="px-2 py-4 text-xs text-zinc-500">Working tree clean.</div>
              ) : (
                files.map((file) => (
                  <div
                    key={file.path}
                    className={`mb-1 rounded-lg border px-2 py-1.5 text-xs ${
                      selectedPath === file.path
                        ? "border-indigo-500/50 bg-indigo-500/10"
                        : "border-transparent hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void loadDiff(file.path, file)}
                      className="w-full text-left"
                    >
                      <span className="font-mono">{file.path}</span>
                      <span className="ml-2 text-zinc-500">
                        {file.status}
                        {file.staged ? " · staged" : ""}
                        {file.unstaged ? " · unstaged" : ""}
                      </span>
                    </button>
                    <div className="mt-1 flex gap-1">
                      {!file.staged && !file.ignored && (
                        <button
                          type="button"
                          disabled={actionPending}
                          onClick={() =>
                            void runAction(() => gitStage(sessionId, [file.path]))
                          }
                          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] hover:bg-zinc-200 dark:hover:bg-zinc-700"
                        >
                          <Check className="h-3 w-3" />
                          Stage
                        </button>
                      )}
                      {file.staged && (
                        <button
                          type="button"
                          disabled={actionPending}
                          onClick={() =>
                            void runAction(() => gitUnstage(sessionId, [file.path]))
                          }
                          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] hover:bg-zinc-200 dark:hover:bg-zinc-700"
                        >
                          <Undo2 className="h-3 w-3" />
                          Unstage
                        </button>
                      )}
                      {(file.unstaged || file.untracked) && (
                        <button
                          type="button"
                          disabled={actionPending}
                          onClick={() =>
                            void runAction(() => gitDiscard(sessionId, [file.path]))
                          }
                          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] text-rose-600 hover:bg-rose-500/10 dark:text-rose-400"
                        >
                          Discard
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="mt-auto border-t border-zinc-200 p-3 dark:border-zinc-800">
              <textarea
                value={commitMessage}
                onChange={(e) => setCommitMessage(e.target.value)}
                placeholder="Commit message"
                rows={3}
                className="mb-2 w-full resize-none rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={actionPending}
                  onClick={() =>
                    void runAction(async () => {
                      const res = await gitCommitMessage(sessionId);
                      if (res.message) setCommitMessage(res.message);
                    })
                  }
                  className="flex-1 rounded-lg border border-zinc-200 px-2 py-1.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                >
                  Suggest
                </button>
                <button
                  type="button"
                  disabled={actionPending || !commitMessage.trim()}
                  onClick={() =>
                    void runAction(async () => {
                      await gitCommit(sessionId, commitMessage.trim());
                      setCommitMessage("");
                    })
                  }
                  className="flex-1 rounded-lg bg-indigo-600 px-2 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  Commit
                </button>
              </div>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-4">
            {selectedPath ? (
              <pre className="whitespace-pre-wrap break-all font-mono text-xs text-zinc-700 dark:text-zinc-300">
                {diffText || "Select a file to view diff."}
              </pre>
            ) : (
              <div className="text-sm text-zinc-500">Select a changed file to view its diff.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
