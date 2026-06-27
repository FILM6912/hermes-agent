import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw, Terminal as TerminalIcon } from "lucide-react";
import { getSession } from "@/services/hermes/sessions";
import {
  closeTerminal,
  resizeTerminal,
  sendTerminalInput,
  startTerminal,
} from "./terminalApi";
import { createTerminal, ensureXtermLoaded, terminalTheme, type XtermFitAddon, type XtermTerminal } from "./loadXterm";
import { setupTerminalClipboard, normalizeTerminalPaste } from "./terminalClipboard";
import { TerminalPasteOverlay } from "./TerminalPasteOverlay";
import { isClipboardPasteBlocked } from "@/lib/clipboard";
import { useTerminalOutput } from "./useTerminalOutput";

interface ShellTerminalPanelProps {
  sessionId: string;
  onBack: () => void;
}

function workspaceLabel(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

export const ShellTerminalPanel: React.FC<ShellTerminalPanelProps> = ({
  sessionId,
  onBack,
}) => {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XtermTerminal | null>(null);
  const fitRef = useRef<XtermFitAddon | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const clipboardCleanupRef = useRef<(() => void) | null>(null);
  const sendInputRef = useRef<(data: string) => void>(() => {});
  const openPastePromptRef = useRef<() => void>(() => {});

  const [workspace, setWorkspace] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [streamEnabled, setStreamEnabled] = useState(false);
  const [pastePromptOpen, setPastePromptOpen] = useState(false);

  openPastePromptRef.current = () => setPastePromptOpen(true);

  const fitTerminal = useCallback(() => {
    const term = termRef.current;
    const fit = fitRef.current;
    if (!term || !fit) return;
    try {
      fit.fit();
    } catch {
      /* viewport not ready */
    }
  }, []);

  const scheduleResize = useCallback(() => {
    const term = termRef.current;
    if (!term || !sessionId) return;
    if (resizeTimerRef.current) window.clearTimeout(resizeTimerRef.current);
    resizeTimerRef.current = window.setTimeout(() => {
      fitTerminal();
      const rows = term.rows || 24;
      const cols = term.cols || 80;
      resizeTerminal({ session_id: sessionId, rows, cols }).catch(() => {});
    }, 120);
  }, [fitTerminal, sessionId]);

  const handleOutput = useCallback((text: string) => {
    termRef.current?.write(text);
  }, []);

  const handleClosed = useCallback(() => {
    termRef.current?.writeln("\r\n[terminal closed]\r\n");
    setRunning(false);
    setStreamEnabled(false);
  }, []);

  const handleStreamError = useCallback((message: string) => {
    termRef.current?.writeln(`\r\n[terminal error] ${message}\r\n`);
    setError(message);
    setRunning(false);
    setStreamEnabled(false);
  }, []);

  useTerminalOutput({
    sessionId: streamEnabled ? sessionId : null,
    enabled: streamEnabled,
    onOutput: handleOutput,
    onClosed: handleClosed,
    onError: handleStreamError,
  });

  const bootTerminal = useCallback(
    async (restart = false) => {
      if (!sessionId) return;
      setLoading(true);
      setError(null);
      try {
        await ensureXtermLoaded();
        const { session } = await getSession(sessionId);
        const ws = session.workspace?.trim() || "";
        if (!ws) {
          setError("This session has no workspace — select a workspace first.");
          setWorkspace(null);
          setRunning(false);
          return;
        }
        setWorkspace(ws);

        const surface = surfaceRef.current;
        if (!surface) return;

        if (!termRef.current) {
          const { term, fitAddon } = createTerminal(surface);
          termRef.current = term;
          fitRef.current = fitAddon;
          const sendInput = (data: string) => {
            sendTerminalInput(sessionId, data).catch((err) => {
              const msg = err instanceof Error ? err.message : "Input failed";
              term.writeln(`\r\n[input error] ${msg}\r\n`);
            });
          };
          sendInputRef.current = sendInput;
          term.onData(sendInput);
          clipboardCleanupRef.current?.();
          clipboardCleanupRef.current = setupTerminalClipboard(term, surface, {
            onPaste: (text) => sendInputRef.current(text),
            onPasteBlocked: () => openPastePromptRef.current(),
          });
        } else {
          termRef.current.options.theme = terminalTheme();
        }

        fitTerminal();
        const term = termRef.current;
        const rows = term.rows || 24;
        const cols = term.cols || 80;
        await startTerminal({ session_id: sessionId, rows, cols, restart });
        setRunning(true);
        setStreamEnabled(true);
        term.focus();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to start terminal");
        setRunning(false);
        setStreamEnabled(false);
      } finally {
        setLoading(false);
      }
    },
    [fitTerminal, sessionId],
  );

  useEffect(() => {
    void bootTerminal(false);
    return () => {
      setStreamEnabled(false);
      if (sessionId) {
        closeTerminal(sessionId).catch(() => {});
      }
      if (resizeTimerRef.current) window.clearTimeout(resizeTimerRef.current);
      clipboardCleanupRef.current?.();
      clipboardCleanupRef.current = null;
      termRef.current?.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps -- boot once per session

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface || !running) return;
    const observer = new ResizeObserver(() => scheduleResize());
    observer.observe(surface);
    return () => observer.disconnect();
  }, [running, scheduleResize]);

  const handleRestart = () => {
    setStreamEnabled(false);
    void bootTerminal(true);
  };

  const handleClose = async () => {
    setStreamEnabled(false);
    if (sessionId) await closeTerminal(sessionId).catch(() => {});
    setRunning(false);
    onBack();
  };

  return (
    <div className="flex h-full w-full flex-col bg-zinc-50 text-zinc-900 dark:bg-[#09090b] dark:text-zinc-200">
      <header className="flex shrink-0 items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg p-2 text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
          aria-label="Back to chat"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <TerminalIcon className="h-5 w-5 text-emerald-500" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">Terminal</h1>
          <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">
            {workspace ? workspaceLabel(workspace) : "Workspace shell"}
            {running ? " · running" : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={handleRestart}
          disabled={loading || !workspace}
          className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Restart
        </button>
        <button
          type="button"
          onClick={() => void handleClose()}
          className="rounded-lg border border-zinc-200 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          Close
        </button>
      </header>

      {error && (
        <div className="mx-4 mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      <div className="relative min-h-0 flex-1 p-4">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-zinc-50/80 dark:bg-[#09090b]/80">
            <Loader2 className="h-8 w-8 animate-spin text-emerald-500" aria-label="Starting terminal" />
          </div>
        )}
        <div
          ref={surfaceRef}
          className="h-full min-h-[280px] overflow-hidden rounded-xl border border-zinc-200 bg-[#1A1A2E] p-2 dark:border-zinc-800"
          role="application"
          aria-label="Terminal emulator"
        />
        {isClipboardPasteBlocked() && running && (
          <p className="pointer-events-none absolute bottom-6 left-6 right-6 text-center text-[11px] text-zinc-400">
            HTTP/IP: ใช้ Ctrl+V หรือคลิกขวาเพื่อเปิดกล่องวางข้อความ
          </p>
        )}
        <TerminalPasteOverlay
          open={pastePromptOpen}
          onClose={() => setPastePromptOpen(false)}
          onSubmit={(text) => sendInputRef.current(normalizeTerminalPaste(text))}
        />
      </div>
    </div>
  );
};
