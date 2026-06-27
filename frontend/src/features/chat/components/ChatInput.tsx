import React from "react";
import {
  Send,
  Paperclip,
  Mic,
  MicOff,
  X,
  File as FileIcon,
  Square,
} from "lucide-react";
import { Attachment, SessionContextUsage } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { composerAttachmentImageSrc } from "@/services/hermes/attachments";
import { applySlashMatchToInput, type SlashCommandMatch } from "@/services/hermes/commands";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useResizeObserver } from "@/hooks/useResizeObserver";
import { MCPServerList } from "./MCPServerList";
import { WorkspacePicker } from "./WorkspacePicker";
import {
  AtMentionPalette,
  applyAtMatchToInput,
  handleAtPaletteKeyDown,
  useAtMentionPalette,
} from "./AtMentionPalette";
import type { AtMentionMatch } from "@/services/hermes/atMention";
import {
  SlashCommandPalette,
  handleSlashPaletteKeyDown,
  useSlashCommandPalette,
} from "./SlashCommandPalette";
import { ClarifyComposerPanel } from "@/features/clarify/components/ClarifyComposerPanel";
import { useClarifyStream } from "@/features/clarify/hooks/useClarifyStream";
import { ApprovalComposerPanel } from "@/features/approval/components/ApprovalComposerPanel";
import { useApprovalStream } from "@/features/approval/hooks/useApprovalStream";
import { ContextUsageIndicator } from "./ContextUsageIndicator";

interface ChatInputProps {
  input: string;
  setInput: (value: string) => void;
  attachments: Attachment[];
  onRemoveAttachment: (index: number) => void;
  onSend: () => void;
  onFileSelect: () => void;
  onPaste: (e: React.ClipboardEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  isDragging: boolean;
  isLoading: boolean;
  isStreaming: boolean;
  onStop?: () => void;
  isListening: boolean;
  speechError: string | null;
  onToggleListening: () => void;
  isUploading?: boolean;
  uploadError?: string | null;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  composerWorkspace?: string;
  onComposerWorkspaceChange?: (path: string, name: string) => void | Promise<void>;
  workspaceNeedsBind?: boolean;
  /** Active Hermes session — resolves uploaded attachment previews via /file/raw. */
  sessionId?: string;
  /** Subscribe to clarify SSE while the agent is running. */
  clarifyEnabled?: boolean;
  /** Subscribe to approval SSE for the active chat (execute_code / terminal). */
  approvalEnabled?: boolean;
  /** Echo Q/A transcript line after a successful clarify response. */
  onClarifyAnswered?: (payload: {
    question: string;
    answer: string;
    displayContent: string;
  }) => void;
  contextUsage?: SessionContextUsage;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  input,
  setInput,
  attachments,
  onRemoveAttachment,
  onSend,
  onStop,
  onFileSelect,
  onPaste,
  onDragOver,
  onDragLeave,
  onDrop,
  isDragging,
  isLoading,
  isStreaming,
  isListening,
  speechError,
  onToggleListening,
  isUploading = false,
  uploadError = null,
  textareaRef,
  composerWorkspace = "",
  onComposerWorkspaceChange,
  workspaceNeedsBind = false,
  sessionId,
  clarifyEnabled = false,
  approvalEnabled = false,
  onClarifyAnswered,
  contextUsage,
}) => {
  const { t } = useLanguage();
  const {
    pending: clarifyPending,
    isResponding: clarifyResponding,
    error: clarifyError,
    respond: respondClarify,
  } = useClarifyStream({
    sessionId,
    enabled: clarifyEnabled && Boolean(sessionId),
    onAnswered: onClarifyAnswered,
  });
  const {
    pending: approvalPending,
    pendingCount: approvalPendingCount,
    isResponding: approvalResponding,
    respond: respondApproval,
  } = useApprovalStream({
    sessionId,
    enabled: approvalEnabled && Boolean(sessionId),
  });
  const clarifyActive = Boolean(clarifyPending);
  const approvalActive = Boolean(approvalPending);
  const composerLocked = clarifyActive || approvalActive;

  React.useEffect(() => {
    if (clarifyPending) {
      textareaRef.current?.focus({ preventScroll: true });
    }
  }, [clarifyPending?.clarify_id, textareaRef]);

  const isSmallScreen = useMediaQuery("(max-width: 1024px)");
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mcpMenuRef = React.useRef<HTMLDivElement>(null);
  const workspaceMenuRef = React.useRef<HTMLDivElement>(null);
  const [showMcpMenu, setShowMcpMenu] = React.useState(false);
  const [showWorkspaceMenu, setShowWorkspaceMenu] = React.useState(false);
  const [cursor, setCursor] = React.useState(0);
  const { width: containerWidth } = useResizeObserver(containerRef);
  const {
    matches,
    open: slashOpen,
    selectedIndex,
    setSelectedIndex,
    close: closeSlash,
    tokenRange,
  } = useSlashCommandPalette(input, cursor);
  const {
    matches: atMatches,
    open: atOpen,
    selectedIndex: atSelectedIndex,
    setSelectedIndex: setAtSelectedIndex,
    close: closeAt,
    tokenRange: atTokenRange,
    loading: atLoading,
    canList: atCanList,
  } = useAtMentionPalette(input, cursor, {
    sessionId,
    workspace: composerWorkspace,
  });

  React.useEffect(() => {
    if (atOpen) closeSlash();
  }, [atOpen, closeSlash]);

  React.useEffect(() => {
    if (slashOpen) closeAt();
  }, [slashOpen, closeAt]);

  const syncCursor = React.useCallback(() => {
    const el = textareaRef.current;
    if (el) setCursor(el.selectionStart ?? 0);
  }, [textareaRef]);

  const applySlashMatch = React.useCallback(
    (match: SlashCommandMatch) => {
      if (!tokenRange) return;
      const { value, cursor: nextCursor } = applySlashMatchToInput(input, tokenRange, match);
      setInput(value);
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
        setCursor(nextCursor);
      });
    },
    [tokenRange, input, setInput, textareaRef],
  );

  const applyAtMatch = React.useCallback(
    (match: AtMentionMatch) => {
      if (!atTokenRange) return;
      const { value, cursor: nextCursor } = applyAtMatchToInput(
        input,
        atTokenRange,
        match,
      );
      setInput(value);
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
        setCursor(nextCursor);
      });
    },
    [atTokenRange, input, setInput, textareaRef],
  );

  // Stack composer controls when the chat column is narrow (preview open, split layout).
  const isNarrowContainer =
    containerWidth !== undefined && containerWidth < 520;
  const isResponsiveSmall = isSmallScreen || isNarrowContainer;

  // Persistent state for layout mode to prevent flickering
  const [isModeMulti, setModeMulti] = React.useState(false);
  const isModeMultiRef = React.useRef(isModeMulti);

  // Derived state for layout
  const isStacked = isModeMulti || isResponsiveSmall;

  const autoResize = React.useCallback(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      const newHeight = textareaRef.current.scrollHeight;
      textareaRef.current.style.height = newHeight + "px";

      // Manage overflow
      if (!isStacked) {
        textareaRef.current.style.overflowY = "hidden";
      } else {
        if (newHeight > textareaRef.current.clientHeight) {
          textareaRef.current.style.overflowY = "auto";
        } else {
          textareaRef.current.style.overflowY = "hidden";
        }
      }
    }
  }, [isStacked, textareaRef]);

  // Handle auto-resize on any state change that affects layout or content
  React.useLayoutEffect(() => {
    autoResize();
  }, [input, isStacked, autoResize]);

  const submitClarifyFromInput = React.useCallback(async () => {
    const text = input.trim();
    if (!text || clarifyResponding) return;
    const ok = await respondClarify(text);
    if (ok) setInput("");
  }, [input, clarifyResponding, respondClarify, setInput]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (approvalActive) return;
    if (clarifyActive) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void submitClarifyFromInput();
      }
      return;
    }
    if (
      handleAtPaletteKeyDown(e, {
        open: atOpen && atCanList,
        matches: atMatches,
        selectedIndex: atSelectedIndex,
        setSelectedIndex: setAtSelectedIndex,
        onApplyMatch: applyAtMatch,
        onClose: closeAt,
      })
    ) {
      return;
    }
    if (
      handleSlashPaletteKeyDown(e, {
        open: slashOpen,
        matches,
        selectedIndex,
        setSelectedIndex,
        onApplyMatch: applySlashMatch,
        onClose: closeSlash,
      })
    ) {
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
      setTimeout(() => {
        textareaRef.current?.focus();
      }, 0);
    }
  };

  const handlePrimaryAction = React.useCallback(() => {
    if (clarifyActive) {
      void submitClarifyFromInput();
      return;
    }
    if (approvalActive && !isStreaming) {
      return;
    }
    if (isStreaming) {
      onStop?.();
      return;
    }
    onSend();
    setTimeout(() => {
      textareaRef.current?.focus();
    }, 0);
  }, [
    approvalActive,
    clarifyActive,
    submitClarifyFromInput,
    isStreaming,
    onStop,
    onSend,
    textareaRef,
  ]);

  const primaryDisabled =
    approvalActive && !isStreaming
      ? true
      : clarifyActive
        ? !input.trim() || clarifyResponding
        : !isStreaming &&
          ((!input.trim() && attachments.length === 0) || isLoading || isUploading);

  const primaryShowsSend = clarifyActive || !isStreaming;
  const primaryGlowActive =
    !approvalActive &&
    ((clarifyActive && input.trim() && !clarifyResponding) ||
      (!composerLocked && (input.trim() || attachments.length > 0) && !isLoading));

  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (showMcpMenu && mcpMenuRef.current && !mcpMenuRef.current.contains(target)) {
        setShowMcpMenu(false);
      }
      if (
        showWorkspaceMenu &&
        workspaceMenuRef.current &&
        !workspaceMenuRef.current.contains(target)
      ) {
        setShowWorkspaceMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showMcpMenu, showWorkspaceMenu]);

  // Sync ref
  React.useEffect(() => {
    isModeMultiRef.current = isModeMulti;
  }, [isModeMulti]);

  // Check layout on input change
  React.useEffect(() => {
    if (!textareaRef.current) return;

    // Use ref to check current mode to avoid adding isModeMulti to dependency array
    const currentMode = isModeMultiRef.current;

    const hasNewline = input.includes("\n");
    const isOverflowing = textareaRef.current.scrollHeight > 76;

    if (!currentMode) {
      // Currently in Single-line mode
      if (hasNewline || isOverflowing) {
        setModeMulti(true);
      }
    } else {
      // Currently in Multi-line mode
      // Switch back ONLY if empty to prevent flickering due to width differences
      if (input.trim().length === 0) {
        setModeMulti(false);
      }
    }
  }, [input]); // Only depend on input changing

  // Cosmic CSS Styles
  const cosmicStyles = `
    .cosmic-container {
      --bg-deep: #0a0e1a;
      --accent-light: #3d6ff7;
      --accent-main: #1447E6;
      --accent-dim: #0d35b8;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      width: 100%;
      border-radius: 16px;
      isolation: isolate;
    }

    .stardust, .cosmic-ring, .starfield, .nebula {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      z-index: -1;
      border-radius: 16px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.5s ease-out;
    }

    .stardust { filter: blur(1px); }
    .cosmic-ring { filter: blur(0.3px); }
    .starfield { filter: blur(8px); }
    .nebula { filter: blur(60px); }

    /* Show effects only on hover and focus - with reduced opacity for light mode */
    .cosmic-container:hover .stardust,
    .cosmic-container:hover .cosmic-ring,
    .cosmic-container:focus-within .stardust,
    .cosmic-container:focus-within .cosmic-ring {
      opacity: 0.4;
    }

    .cosmic-container:hover .starfield,
    .cosmic-container:hover .nebula,
    .cosmic-container:focus-within .starfield,
    .cosmic-container:focus-within .nebula {
      opacity: 0.15;
    }

    /* Dark mode - full opacity */
    .dark .cosmic-container:hover .stardust,
    .dark .cosmic-container:hover .cosmic-ring,
    .dark .cosmic-container:focus-within .stardust,
    .dark .cosmic-container:focus-within .cosmic-ring {
      opacity: 1;
    }

    .dark .cosmic-container:hover .starfield,
    .dark .cosmic-container:hover .nebula,
    .dark .cosmic-container:focus-within .starfield,
    .dark .cosmic-container:focus-within .nebula {
      opacity: 0.5;
    }

    .cosmic-container:focus-within .nebula {
      opacity: 0.08;
    }

    .dark .cosmic-container:focus-within .nebula {
      opacity: 0.3;
    }

    .stardust::before, .cosmic-ring::before, .starfield::before, .nebula::before {
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 200vmax;
      height: 200vmax;
      background-repeat: no-repeat;
      background-position: center;
      transition: transform 2s ease-out;
      will-change: transform;
    }

    .stardust::before {
      transform: translate(-50%, -50%) rotate(83deg);
      filter: brightness(1.4);
      background-image: conic-gradient(rgba(0,0,0,0) 0%, var(--accent-main), rgba(0,0,0,0) 12%, rgba(0,0,0,0) 50%, var(--accent-dim), rgba(0,0,0,0) 62%);
    }

    .cosmic-ring::before {
      transform: translate(-50%, -50%) rotate(70deg);
      filter: brightness(1.3);
      background-image: conic-gradient(var(--bg-deep), var(--accent-main) 8%, var(--bg-deep) 18%, var(--bg-deep) 50%, var(--accent-dim) 65%, var(--bg-deep) 72%);
    }

    .starfield::before {
      transform: translate(-50%, -50%) rotate(82deg);
      background-image: conic-gradient(rgba(0,0,0,0), #2563eb, rgba(0,0,0,0) 10%, rgba(0,0,0,0) 50%, #1d4ed8, rgba(0,0,0,0) 60%);
    }

    .nebula::before {
      transform: translate(-50%, -50%) rotate(60deg);
      background-image: conic-gradient(#000, #1447E6 5%, #000 38%, #000 50%, #0d35b8 60%, #000 87%);
    }

    .cosmic-container:hover .starfield::before { transform: translate(-50%, -50%) rotate(-98deg); }
    .cosmic-container:hover .nebula::before { transform: translate(-50%, -50%) rotate(-120deg); }
    .cosmic-container:hover .stardust::before { transform: translate(-50%, -50%) rotate(-97deg); }
    .cosmic-container:hover .cosmic-ring::before { transform: translate(-50%, -50%) rotate(-110deg); }

    .cosmic-container:focus-within .starfield::before { transform: translate(-50%, -50%) rotate(442deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .nebula::before { transform: translate(-50%, -50%) rotate(420deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .stardust::before { transform: translate(-50%, -50%) rotate(443deg); transition: transform 4s ease-out; }
    .cosmic-container:focus-within .cosmic-ring::before { transform: translate(-50%, -50%) rotate(430deg); transition: transform 4s ease-out; }

    #cosmic-glow {
      pointer-events: none;
      width: 40px;
      height: 25px;
      position: absolute;
      background: var(--accent-main);
      top: 20px;
      left: 20px;
      filter: blur(25px);
      opacity: 0;
      transition: opacity 0.3s ease-out;
    }
    
    .cosmic-container:hover #cosmic-glow,
    .cosmic-container:focus-within #cosmic-glow {
      opacity: 0.15;
      transition: opacity 0.3s ease-in, all 2s;
    }

    .dark .cosmic-container:hover #cosmic-glow,
    .dark .cosmic-container:focus-within #cosmic-glow {
      opacity: 0.6;
    }
    
    .cosmic-container:hover #cosmic-glow {
      opacity: 0;
      transition: all 2s;
    }

    @keyframes wormhole-rotate {
      100% { transform: translate(-50%, -50%) rotate(450deg); }
    }
    .wormhole-spin::before {
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) rotate(90deg);
      width: 400px;
      height: 400px;
      background-image: conic-gradient(rgba(0,0,0,0), var(--accent-main), rgba(0,0,0,0) 50%, rgba(0,0,0,0) 50%, var(--accent-dim), rgba(0,0,0,0) 100%);
      animation: wormhole-rotate 4s linear infinite;
      filter: brightness(1.2);
      opacity: 0.35;
    }

    .dark .wormhole-spin::before {
      opacity: 0.8;
      filter: brightness(1.3);
    }

    .action-bar-transition {
      transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }
  `;

  const singleLineTextareaClass =
    "min-h-[56px] py-3.5 leading-relaxed px-4 box-border";
  const stackedTextareaClass = "min-h-[56px] leading-relaxed px-4 py-4";

  return (
    <>
      <style>{cosmicStyles}</style>
      <div className="absolute left-0 w-full px-3 sm:px-4 pt-2 z-20 pointer-events-none bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] sm:bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))]">
        <div className="max-w-5xl mx-auto pointer-events-auto min-w-0">
          <div
            ref={containerRef}
            className="cosmic-container relative w-full group transition-all duration-500"
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {/* Background Layers */}
            <div className="nebula"></div>
            <div className="starfield"></div>
            <div className="stardust"></div>
            <div className="stardust opacity-50 translate-x-1"></div>
            <div className="cosmic-ring"></div>
            <div id="cosmic-glow"></div>

            {/* Inner Content Wrapper - removed overflow-hidden */}
            <div className="relative z-10 w-full flex flex-col bg-white dark:bg-zinc-900 backdrop-blur-md rounded-2xl border border-zinc-200/60 dark:border-zinc-700/50 shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:shadow-zinc-950/50">
              {/* Drag Overlay */}
              {isDragging && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-blue-50/95 dark:bg-blue-950/95 backdrop-blur-sm rounded-2xl">
                  <div className="flex flex-col items-center gap-3 text-[#1447E6] dark:text-blue-400">
                    <div className="relative">
                      <div className="absolute inset-0 bg-[#1447E6] blur-xl opacity-40 rounded-full animate-pulse"></div>
                      <Paperclip className="w-10 h-10 relative z-10" />
                    </div>
                    <span className="font-semibold tracking-wide text-sm">
                      {t("chat.dropFiles") || "Drop files here"}
                    </span>
                  </div>
                </div>
              )}

              {approvalPending && (
                <ApprovalComposerPanel
                  pending={approvalPending}
                  pendingCount={approvalPendingCount}
                  isResponding={approvalResponding}
                  onRespond={respondApproval}
                />
              )}

              {clarifyPending && (
                <ClarifyComposerPanel
                  pending={clarifyPending}
                  isResponding={clarifyResponding}
                  error={clarifyError}
                  onRespond={respondClarify}
                  onFocusInput={() => textareaRef.current?.focus()}
                />
              )}

              {/* Attachments Area */}
              {!composerLocked && (attachments.length > 0 || isUploading || uploadError) && (
                <div className="flex flex-col gap-2 px-4 pt-4 pb-0 max-h-32 overflow-y-auto custom-scrollbar relative z-20">
                  {uploadError && (
                    <div className="text-xs text-red-400 bg-red-950/40 rounded-lg px-3 py-1.5">
                      {uploadError}
                    </div>
                  )}
                  {isUploading && (
                    <div className="text-xs text-zinc-500 dark:text-zinc-400 px-1">
                      {t("chat.uploading") || "Uploading…"}
                    </div>
                  )}
                  {attachments.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                  {attachments.map((file, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2 bg-zinc-50 dark:bg-zinc-800 rounded-lg pl-2 pr-2 py-1.5 border border-zinc-200 dark:border-zinc-700 text-xs text-zinc-700 dark:text-zinc-300 animate-in fade-in zoom-in-95 group/file relative overflow-hidden"
                    >
                      {file.type === "image" ? (
                        <div className="relative w-8 h-8 rounded overflow-hidden shrink-0">
                          <img
                            src={composerAttachmentImageSrc(sessionId, file, {
                              workspace: composerWorkspace?.trim() || undefined,
                            })}
                            alt={file.name}
                            className="w-full h-full object-cover"
                          />
                        </div>
                      ) : (
                        <FileIcon className="w-3.5 h-3.5 text-[#1447E6] dark:text-blue-400" />
                      )}
                      <span className="max-w-[150px] truncate">
                        {file.name}
                      </span>
                      <button
                        onClick={() => onRemoveAttachment(index)}
                        className="p-1 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-md text-zinc-500 dark:text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                    </div>
                  )}
                </div>
              )}

              {/* Input Area */}
              <div
                className={`w-full flex min-w-0 transition-all duration-500 ease-in-out ${
                  isStacked
                    ? "flex-col"
                    : "flex-wrap items-center gap-x-1 gap-y-1 -translate-y-0.5"
                }`}
              >

                {/* Left Actions - Rendered first in Single Line mode, or inside wrapper in Multi Line */}
                {!isStacked && (
                  <div className="flex items-center gap-1.5 sm:gap-2 pl-2 sm:pl-3 shrink-0 flex-wrap max-w-full animate-in fade-in slide-in-from-left-2 duration-500">
                    <button
                      onClick={onFileSelect}
                      disabled={composerLocked}
                      className="p-2 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 rounded-xl transition-colors disabled:opacity-40"
                      title={t("chat.attachFile") || "Attach File"}
                    >
                      <Paperclip className="w-5 h-5" />
                    </button>
                    {onComposerWorkspaceChange && (
                      <WorkspacePicker
                        value={composerWorkspace}
                        onChange={onComposerWorkspaceChange}
                        allowReselect={workspaceNeedsBind}
                        menuRef={workspaceMenuRef}
                        isOpen={showWorkspaceMenu}
                        onToggle={() => {
                          setShowWorkspaceMenu((prev) => !prev);
                          setShowMcpMenu(false);
                        }}
                      />
                    )}
                    <MCPServerList
                      isOpen={showMcpMenu}
                      onToggle={() => {
                        setShowMcpMenu((prev) => !prev);
                        setShowWorkspaceMenu(false);
                      }}
                      menuRef={mcpMenuRef}
                    />
                  </div>
                )}

                <div
                  className={`relative min-w-0 ${
                    isStacked ? "flex-1" : "flex flex-1 items-center"
                  }`}
                >
                  {!composerLocked && (
                    <>
                      <AtMentionPalette
                        input={input}
                        cursor={cursor}
                        sessionId={sessionId}
                        workspace={composerWorkspace}
                        matches={atMatches}
                        open={atOpen}
                        loading={atLoading}
                        canList={atCanList}
                        selectedIndex={atSelectedIndex}
                        onSelectedIndexChange={setAtSelectedIndex}
                        onClose={closeAt}
                        tokenRange={atTokenRange}
                        onApplyMatch={applyAtMatch}
                      />
                      <SlashCommandPalette
                        input={input}
                        setInput={setInput}
                        matches={matches}
                        open={slashOpen && !atOpen}
                        selectedIndex={selectedIndex}
                        onSelectedIndexChange={setSelectedIndex}
                        onClose={closeSlash}
                        tokenRange={tokenRange}
                        onApplyMatch={applySlashMatch}
                      />
                    </>
                  )}
                  <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    setCursor(e.target.selectionStart ?? 0);
                  }}
                  onSelect={syncCursor}
                  onClick={syncCursor}
                  onKeyUp={syncCursor}
                  onKeyDown={handleKeyDown}
                  onPaste={composerLocked ? undefined : onPaste}
                  placeholder={
                    approvalActive
                      ? "Choose Allow or Deny above"
                      : clarifyActive
                        ? "Type your response…"
                        : t("chat.placeholder")
                  }
                  readOnly={approvalActive}
                  aria-labelledby={
                    approvalActive
                      ? "approval-composer-heading"
                      : clarifyActive
                        ? "clarify-composer-heading"
                        : undefined
                  }
                  className={`w-full bg-transparent text-zinc-700 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-500 outline-none resize-none max-h-[30vh] text-base ${
                    isStacked ? stackedTextareaClass : singleLineTextareaClass
                  }`}
                  rows={1}
                />
                </div>

                {/* Right Actions - Rendered last in Single Line mode */}
                {!isStacked && (
                  <div className="flex items-center gap-1.5 sm:gap-2 pr-2 sm:pr-3 shrink-0 ml-auto animate-in fade-in slide-in-from-right-2 duration-500">

                    <ContextUsageIndicator
                      usage={contextUsage}
                      onCompressHint={() => {
                        setInput("/compress ");
                        textareaRef.current?.focus();
                      }}
                    />

                    {/* Speech Button */}
                    <div className="relative">
                      {speechError && (
                        <div className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2 whitespace-nowrap bg-red-500/90 text-white text-[10px] px-2 py-1 rounded border border-red-400 backdrop-blur-sm z-50">
                          {speechError}
                        </div>
                      )}
                      <button
                        onClick={onToggleListening}
                        className={`p-2 rounded-xl transition-all duration-300 ${isListening
                          ? "bg-red-500/20 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.4)] animate-pulse border border-red-500/50"
                          : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                          }`}
                        title={
                          isListening
                            ? t("chat.stopRecording") || "Stop recording"
                            : t("chat.startRecording") || "Start recording"
                        }
                      >
                        {isListening ? (
                          <MicOff className="w-5 h-5" />
                        ) : (
                          <Mic className="w-5 h-5" />
                        )}
                      </button>
                    </div>

                    {/* Wormhole Send Button */}
                    <div className="relative w-10 h-10 flex items-center justify-center">
                      <div
                        className={`absolute inset-0 rounded-xl overflow-hidden pointer-events-none transition-opacity duration-300 ${
                          primaryGlowActive ? "opacity-100" : "opacity-0"
                        }`}
                      >
                        <div className="wormhole-spin w-full h-full relative"></div>
                      </div>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          handlePrimaryAction();
                        }}
                        disabled={primaryDisabled}
                        className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-[10px] transition-all duration-300 ${
                          !primaryShowsSend && isStreaming
                            ? "bg-red-500 text-white shadow-lg shadow-red-500/30 hover:shadow-xl hover:shadow-red-500/40 hover:scale-105"
                            : primaryGlowActive
                              ? "bg-linear-to-br from-[#1447E6] to-[#0d35b8] text-white shadow-lg shadow-blue-500/30 hover:shadow-xl hover:shadow-blue-500/40 hover:scale-105"
                              : "bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600"
                        }`}
                        title={
                          clarifyActive
                            ? "Send clarification"
                            : isStreaming
                              ? "Stop"
                              : t("chat.send") || "Send"
                        }
                      >
                        {primaryShowsSend ? (
                          <Send className="w-4 h-4" />
                        ) : (
                          <Square className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                )}

                {/* Multi-line Action Bar (Bottom) */}
                {isStacked && (
                  <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-3 animate-in fade-in slide-in-from-bottom-2 duration-500">
                    {/* Left Actions Group */}
                    <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap min-w-0 max-w-full">
                      <button
                        onClick={onFileSelect}
                        disabled={isUploading || composerLocked}
                        className="p-2 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 rounded-xl transition-colors disabled:opacity-50"
                        title={t("chat.attachFile") || "Attach File"}
                      >
                        <Paperclip className="w-5 h-5" />
                      </button>
                      {onComposerWorkspaceChange && (
                        <WorkspacePicker
                          value={composerWorkspace}
                          onChange={onComposerWorkspaceChange}
                          allowReselect={workspaceNeedsBind}
                          menuRef={workspaceMenuRef}
                          isOpen={showWorkspaceMenu}
                          onToggle={() => {
                            setShowWorkspaceMenu((prev) => !prev);
                            setShowMcpMenu(false);
                          }}
                        />
                      )}
                      <MCPServerList
                        isOpen={showMcpMenu}
                        onToggle={() => {
                          setShowMcpMenu((prev) => !prev);
                          setShowWorkspaceMenu(false);
                        }}
                        menuRef={mcpMenuRef}
                      />
                    </div>

                    {/* Right Actions Group */}
                    <div className="flex items-center gap-2">

                      <ContextUsageIndicator
                        usage={contextUsage}
                        onCompressHint={() => {
                          setInput("/compress ");
                          textareaRef.current?.focus();
                        }}
                      />

                      {/* Speech Button */}
                      <div className="relative">
                        {speechError && (
                          <div className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2 whitespace-nowrap bg-red-500/90 text-white text-[10px] px-2 py-1 rounded border border-red-400 backdrop-blur-sm z-50">
                            {speechError}
                          </div>
                        )}
                        <button
                          onClick={onToggleListening}
                          className={`p-2 rounded-xl transition-all duration-300 ${isListening
                            ? "bg-red-500/20 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.4)] animate-pulse border border-red-500/50"
                            : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
                            }`}
                          title={
                            isListening
                              ? t("chat.stopRecording") || "Stop recording"
                              : t("chat.startRecording") || "Start recording"
                          }
                        >
                          {isListening ? (
                            <MicOff className="w-5 h-5" />
                          ) : (
                            <Mic className="w-5 h-5" />
                          )}
                        </button>
                      </div>

                      {/* Wormhole Send Button */}
                      <div className="relative w-10 h-10 flex items-center justify-center">
                        <div
                          className={`absolute inset-0 rounded-xl overflow-hidden pointer-events-none transition-opacity duration-300 ${
                            primaryGlowActive ? "opacity-100" : "opacity-0"
                          }`}
                        >
                          <div className="wormhole-spin w-full h-full relative"></div>
                        </div>

                        <button
                          onClick={handlePrimaryAction}
                          disabled={primaryDisabled}
                          className={`relative z-10 w-9 h-9 flex items-center justify-center rounded-[10px] transition-all duration-300 ${
                            !primaryShowsSend && isStreaming
                              ? "bg-red-500 text-white shadow-lg shadow-red-500/30 hover:shadow-xl hover:shadow-red-500/40 hover:scale-105"
                              : primaryGlowActive
                                ? "bg-linear-to-br from-[#1447E6] to-[#0d35b8] text-white shadow-lg shadow-blue-500/30 hover:shadow-xl hover:shadow-blue-500/40 hover:scale-105"
                                : "bg-zinc-100 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600"
                          }`}
                          title={
                            clarifyActive
                              ? "Send clarification"
                              : isStreaming
                                ? "Stop"
                                : t("chat.send") || "Send"
                          }
                        >
                          {primaryShowsSend ? (
                            <Send className="w-4 h-4" />
                          ) : (
                            <Square className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};
