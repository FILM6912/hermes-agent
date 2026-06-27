import React, { useRef, useEffect, useState, useMemo } from "react";
import { Settings, ArrowDown, Menu, PanelRight } from "lucide-react";
import { Message, ModelConfig, AIProvider, Attachment, ProcessStep, SessionContextUsage, SessionCompressionAnchor } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { WelcomeScreen } from "./WelcomeScreen";
import { MessageItem } from "./MessageItem";
import { CompressionReferenceCard } from "./CompressionReferenceCard";
import { buildTranscriptItems } from "../utils/compressionAnchor";
import { LoadingIndicator } from "./LoadingIndicator";
import { ImageLightbox, type ImagePreviewSource } from "./ImageLightbox";
import { ChatInput } from "./ChatInput";
import { ModelSelector } from "./ModelSelector";
import { ProfileChip } from "@/components/shell/ProfileChip";
import type { PickerModel } from "@/services/hermes/models";
import { useToast } from "@/components/toast/ToastProvider";
import { copyTextToClipboard } from "@/lib/clipboard";
import { ChatLoadingSkeleton } from "./ChatLoadingSkeleton";
import type { HermesProfileSwitchResponse } from "@/services/hermes/profiles";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useFileHandling } from "../hooks/useFileHandling";
import { useMarkdownComponents } from "../hooks/useMarkdownComponents";
export const getPresetModels = (
  t: (key: string) => string,
): Record<AIProvider, { id: string; name: string; desc: string }[]> => ({
  google: [
    {
      id: "gemini-3-flash-preview",
      name: "Gemini 3.0 Flash",
      desc: t("models.gemini-3-flash-preview"),
    },
    {
      id: "gemini-3-pro-preview",
      name: "Gemini 3.0 Pro",
      desc: t("models.gemini-3-pro-preview"),
    },
    {
      id: "gemini-2.5-flash-lite-latest",
      name: "Flash Lite",
      desc: t("models.gemini-2.5-flash-lite-latest"),
    },
  ],
  openai: [
    { id: "gpt-4o", name: "GPT-4o", desc: t("models.gpt-4o") },
    { id: "gpt-4-turbo", name: "GPT-4 Turbo", desc: t("models.gpt-4-turbo") },
    {
      id: "gpt-3.5-turbo",
      name: "GPT-3.5 Turbo",
      desc: t("models.gpt-3.5-turbo"),
    },
  ],
});

interface ChatInterfaceProps {
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  onSend: (
    message: string,
    attachments: Attachment[],
    sessionId?: string,
  ) => void | Promise<void>;
  onRegenerate: (messageId: string) => void;
  onEdit?: (messageId: string, newContent: string) => void;
  isLoading: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
  agentModels: PickerModel[];
  pinnedAgentId: string | null;
  onPinAgent: (modelId: string) => void;
  onProviderChange?: (provider: AIProvider) => void;
  onVersionChange?: (messageId: string, newIndex: number) => void;
  onAIVersionChange?: (messageId: string, newIndex: number) => void;
  onRegenVersionChange?: (messageId: string, aiIndex: number, regenIndex: number) => void;
  isPreviewOpen?: boolean;
  onPreviewRequest?: (content: string) => void;
  /** Open the workspace / files preview panel (shell chrome). */
  onOpenPreview?: () => void;
  onOpenToolInPreview?: (step: ProcessStep) => void;
  onOpenSettings?: () => void;
  onLogout?: () => void;
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
  isMobile?: boolean;
  onToggleSidebar?: () => void;
  loadingChatId?: string | null;
  activeChatId?: string;
  /** Resolved agent name for current chat (avoids "Select Agent" flash on refresh) */
  resolvedAgentName?: string;
  /** Agent description from same source as dropdown (agentModels) so welcome screen matches */
  resolvedAgentDescription?: string;
  composerWorkspace?: string;
  onComposerWorkspaceChange?: (path: string, name: string) => void | Promise<void>;
  onProfileSwitched?: (result: HermesProfileSwitchResponse) => void;
  workspaceNeedsBind?: boolean;
  /** Ensure a server-backed session exists (for uploads before first send). */
  ensureComposerSession?: (options?: {
    navigate?: boolean;
    activate?: boolean;
  }) => Promise<string>;
  onClarifyAnswered?: (payload: {
    question: string;
    answer: string;
    displayContent: string;
  }) => void;
  /** Context window usage for the active session (composer ring). */
  contextUsage?: SessionContextUsage;
  /** Compacted earlier-turn reference card from session metadata. */
  compressionAnchor?: SessionCompressionAnchor;
}

export const ChatInterface: React.FC<ChatInterfaceProps> = ({
  messages,
  input,
  setInput,
  onSend,
  onStop,
  onRegenerate,
  onEdit,
  isLoading,
  isStreaming,
  modelConfig,
  onModelConfigChange,
  agentModels,
  pinnedAgentId,
  onPinAgent,
  onVersionChange,
  onAIVersionChange,
  onRegenVersionChange,
  isPreviewOpen: _isPreviewOpen = false,
  onPreviewRequest,
  onOpenPreview,
  onOpenToolInPreview,
  onOpenSettings,
  onLogout: _onLogout,
  textareaRef: externalTextareaRef,
  isMobile = false,
  onToggleSidebar,
  loadingChatId,
  activeChatId = "",
  resolvedAgentName,
  resolvedAgentDescription,
  composerWorkspace,
  onComposerWorkspaceChange,
  onProfileSwitched,
  workspaceNeedsBind = false,
  ensureComposerSession,
  onClarifyAnswered,
  contextUsage,
  compressionAnchor,
}) => {
  const { t, language } = useLanguage();
  const toast = useToast();
  const scrollRef = useRef<HTMLDivElement>(null);
  const internalTextareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = externalTextareaRef || internalTextareaRef;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const shouldFocusRef = useRef(false);

  // Menu Refs for click outside handling
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const modelMenuPanelRef = useRef<HTMLDivElement>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [viewingImage, setViewingImage] = useState<ImagePreviewSource | null>(null);
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [userHasScrolledUp, setUserHasScrolledUp] = useState(false);
  /** Suppress auto-scroll-to-bottom for a short window after clicking an in-page anchor */
  const suppressAutoScrollUntilRef = useRef<number>(0);

  // Edit State
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const transcriptItems = useMemo(
    () => buildTranscriptItems(messages, compressionAnchor),
    [messages, compressionAnchor],
  );
  const lastMessageId = messages.length > 0 ? messages[messages.length - 1].id : null;

  // Custom Hooks
  const { isListening, speechError, toggleListening } = useSpeechRecognition({
    language,
    input,
    setInput,
  });

  const {
    attachments,
    isDragging,
    isUploading,
    uploadError,
    handleFileSelect,
    handlePaste,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    removeAttachment,
    clearAttachments,
    flushUploads,
  } = useFileHandling({
    sessionId: activeChatId || undefined,
    workspace: composerWorkspace,
    ensureSessionId: ensureComposerSession,
  });

  const markdownComponents = useMarkdownComponents({
    onPreviewRequest,
    onViewImage: setViewingImage,
    scrollRootRef: scrollRef,
    onAnchorNavigation: () => {
      suppressAutoScrollUntilRef.current = Date.now() + 4000;
      setUserHasScrolledUp(true);
    },
  });

  // Auto-scroll to bottom (smooth while AI is streaming for a smoother feel)
  useEffect(() => {
    if (!scrollRef.current || userHasScrolledUp) return;
    if (Date.now() < suppressAutoScrollUntilRef.current) return;
    const el = scrollRef.current;
    const target = el.scrollHeight;
    if (isStreaming) {
      el.scrollTo({ top: target, behavior: "smooth" });
    } else {
      el.scrollTop = target;
    }
  }, [messages, isLoading, isStreaming, editingId, input, userHasScrolledUp]);

  const handleScroll = () => {
    if (scrollRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
      if (isAtBottom && userHasScrolledUp) {
        if (Date.now() < suppressAutoScrollUntilRef.current) return;
        setUserHasScrolledUp(false);
      } else if (!isAtBottom && !userHasScrolledUp) {
        setUserHasScrolledUp(true);
      }
    }
  };

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
      setUserHasScrolledUp(false);
    }
  };

  // Auto-focus textarea after sending message
  useEffect(() => {
    if (shouldFocusRef.current && textareaRef.current) {
      // Use requestAnimationFrame to ensure DOM is fully updated
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          textareaRef.current?.focus();
          shouldFocusRef.current = false;
        });
      });
    }
  });

  // Click outside handler for menus
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;

      if (
        showModelMenu &&
        !modelMenuRef.current?.contains(target) &&
        !modelMenuPanelRef.current?.contains(target)
      ) {
        setShowModelMenu(false);
      }
      if (showProfileMenu && profileMenuRef.current && !profileMenuRef.current.contains(target)) {
        setShowProfileMenu(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showModelMenu, showProfileMenu]);

  const handleCopy = async (id: string, text: string) => {
    const ok = await copyTextToClipboard(text);
    if (ok) {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } else {
      toast.error("Copy failed.");
    }
  };

  const handleSendClick = async () => {
    if ((!input.trim() && attachments.length === 0) || isLoading || isStreaming || isUploading)
      return;

    console.log("🚀 Sending message, will focus after render");
    shouldFocusRef.current = true;
    setUserHasScrolledUp(false);

    try {
      const sessionId = ensureComposerSession
        ? await ensureComposerSession()
        : activeChatId;
      if (!sessionId) {
        toast.error(t("chat.sendFailedNoSession"));
        return;
      }
      const finalAttachments = await flushUploads(sessionId);
      // Clear composer chips immediately after upload handoff (legacy: renderTray on send).
      clearAttachments();
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await onSend(input, finalAttachments, sessionId);
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    } catch (err) {
      console.error("Failed to prepare or send message:", err);
      toast.error(err instanceof Error ? err.message : t("chat.sendFailed"));
    }
  };

  const startEditing = (msg: Message) => {
    setEditingId(msg.id);
    setEditValue(msg.content);
  };

  const submitEdit = (id: string) => {
    if (editValue.trim() && onEdit) {
      onEdit(id, editValue);
      setEditingId(null);
      setEditValue("");
    }
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditValue("");
  };

  const handleSuggestionClick = async (prompt: string) => {
    setUserHasScrolledUp(false);
    try {
      const sessionId = ensureComposerSession
        ? await ensureComposerSession({ navigate: false })
        : activeChatId;
      if (!sessionId) {
        toast.error(t("chat.sendFailedNoSession"));
        return;
      }
      await onSend(prompt, [], sessionId);
      shouldFocusRef.current = true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("chat.sendFailed"));
    }
  };

  const showPreviewToggle = Boolean(onOpenPreview) && !_isPreviewOpen;

  return (
    <div className="flex flex-col h-full min-h-0 bg-zinc-50 dark:bg-zinc-950 relative transition-colors duration-200">
      <header className="shrink-0 z-30 flex flex-wrap items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2 min-h-12 border-b border-zinc-200/80 dark:border-zinc-800/80 bg-zinc-50/95 dark:bg-zinc-950/95 backdrop-blur-sm overflow-visible">
        {isMobile && onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="shrink-0 p-2 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
            title={t("chat.toggleSidebar") || "Toggle Sidebar"}
          >
            <Menu className="w-5 h-5" />
          </button>
        )}
        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2 min-w-0 flex-1">
          <ModelSelector
            isOpen={showModelMenu}
            onToggle={() => {
              setShowModelMenu(!showModelMenu);
              setShowProfileMenu(false);
            }}
            modelConfig={modelConfig}
            agentModels={agentModels}
            pinnedAgentId={pinnedAgentId}
            onModelSelect={(id, name) => {
              const picked = agentModels.find((m) => m.id === id);
              onModelConfigChange({
                ...modelConfig,
                modelId: id,
                name,
                modelProvider: picked?.hermesProvider,
              });
            }}
            onPinAgent={onPinAgent}
            menuRef={modelMenuRef as React.RefObject<HTMLDivElement>}
            menuPanelRef={modelMenuPanelRef}
            resolvedAgentName={resolvedAgentName}
          />
          <ProfileChip
            menuRef={profileMenuRef}
            isOpen={showProfileMenu}
            onToggle={() => {
              setShowProfileMenu((open) => !open);
              setShowModelMenu(false);
            }}
            onProfileSwitched={onProfileSwitched}
          />
        </div>
        {showPreviewToggle && (
          <button
            type="button"
            onClick={onOpenPreview}
            className="shrink-0 p-2 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg transition-colors"
            title={t("preview.openPanel") || "Open files"}
          >
            <PanelRight className="w-4 h-4" />
          </button>
        )}
      </header>

      <div
        className="flex-1 min-h-0 overflow-y-auto scroll-smooth"
        ref={scrollRef}
        data-chat-scroll-root
        onScroll={handleScroll}
      >
        <div className="max-w-5xl mx-auto px-3 sm:px-4 pb-36 sm:pb-40 pt-4 space-y-8">
          {loadingChatId ? (
            <div className="animate-content-fade-in">
              <ChatLoadingSkeleton />
            </div>
          ) : (
            <div key={activeChatId ?? "empty"} className="animate-content-fade-in">
            <>
              {messages.length === 0 && (() => {
                const name = resolvedAgentName || modelConfig.name;
                const isSelectAgentPlaceholder = !name || name === "Select Agent" || name === "เลือก Agent";
                const agentKey = modelConfig.modelId || "no-agent";
                
                return (
                  <WelcomeScreen
                    key={agentKey}
                    language={language}
                    onSuggestionClick={handleSuggestionClick}
                    hasSelectedAgent={!isSelectAgentPlaceholder}
                    agentName={isSelectAgentPlaceholder ? undefined : name}
                    agentDescription={(() => {
                      if (isSelectAgentPlaceholder) return undefined;
                      // Prefer description from same source as dropdown (agentModels) so it always matches
                      if (resolvedAgentDescription) return resolvedAgentDescription;
                      // Fallback: try localStorage
                      try {
                        const savedAgents = localStorage.getItem("agent_flows");
                        if (savedAgents && modelConfig.modelId) {
                          const parsed = JSON.parse(savedAgents);
                          if (Array.isArray(parsed)) {
                            const agent = parsed.find((a: any) => a.id === modelConfig.modelId);
                            if (agent?.description) return agent.description;
                          }
                        }
                      } catch {}
                      return undefined;
                    })()}
                  />
                );
              })()}

          {/* Agent Warning - Show if selected model is an agent but not enabled */}
          {messages.length > 0 &&
            (() => {
              const savedAgents = localStorage.getItem("agent_flows");
              let isAgentDisabled = false;

              if (savedAgents && modelConfig.modelId) {
                try {
                  const parsed = JSON.parse(savedAgents);
                  if (Array.isArray(parsed)) {
                    const agent = parsed.find(
                      (a: any) => a.id === modelConfig.modelId,
                    );
                    if (agent && agent.enabled !== true) {
                      isAgentDisabled = true;
                    }
                  }
                } catch (e) {
                  console.error("Failed to parse saved agents:", e);
                }
              }

              if (isAgentDisabled) {
                return (
                  <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-xl p-4 flex items-start gap-3 animate-in fade-in slide-in-from-top-2 duration-300">
                    <div className="p-2 bg-amber-100 dark:bg-amber-900/40 rounded-lg">
                      <Settings className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                    </div>
                    <div className="flex-1">
                      <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200 mb-1">
                        {language === "th"
                          ? "เอเจนต์ถูกปิดใช้งาน"
                          : "Agent Disabled"}
                      </h3>
                      <p className="text-xs text-amber-700 dark:text-amber-300 mb-3">
                        {language === "th"
                          ? `เอเจนต์ "${modelConfig.name}" ถูกปิดใช้งาน กรุณาเปิดใช้งานในหน้าตั้งค่าหรือเลือก model อื่น`
                          : `Agent "${modelConfig.name}" is disabled. Please enable it in settings or select another model.`}
                      </p>
                      <button
                        onClick={() => onOpenSettings?.()}
                        className="text-xs font-medium text-amber-600 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-300 underline"
                      >
                        {language === "th"
                          ? "ไปที่การตั้งค่า"
                          : "Go to Settings"}
                      </button>
                    </div>
                  </div>
                );
              }
              return null;
            })()}

          {/* Messages */}
          {transcriptItems.map((item, index) => {
            if (item.kind === "compression") {
              return (
                <CompressionReferenceCard
                  key={`compression-${item.anchor.summary.slice(0, 48)}-${index}`}
                  anchor={item.anchor}
                />
              );
            }

            const msg = item.message;

            return (
              <MessageItem
                key={msg.id}
                message={msg}
                isLastMessage={msg.id === lastMessageId}
                isLoading={isLoading}
                isStreaming={isStreaming || false}
                copiedId={copiedId}
                modelConfig={modelConfig}
                onCopy={handleCopy}
                onRegenerate={onRegenerate}
                onEdit={onEdit}
                onVersionChange={onVersionChange}
                onAIVersionChange={onAIVersionChange}
                onRegenVersionChange={onRegenVersionChange}
                onViewImage={setViewingImage}
                editingId={editingId}
                editValue={editValue}
                onStartEdit={startEditing}
                onSubmitEdit={submitEdit}
                onCancelEdit={cancelEdit}
                setEditValue={setEditValue}
                markdownComponents={markdownComponents}
                resolvedAgentName={resolvedAgentName}
                sessionId={activeChatId || undefined}
                composerWorkspace={composerWorkspace}
                onOpenToolInPreview={onOpenToolInPreview}
              />
            );
          })}

          {/* Loading Indicator */}
          {isLoading && <LoadingIndicator modelConfig={modelConfig} />}
            </>
            </div>
          )}
        </div>
      </div >

      {/* Scroll to Bottom Button */}
      {userHasScrolledUp && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-[calc(9.5rem+env(safe-area-inset-bottom,0px))] right-3 sm:right-6 p-2.5 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-full shadow-lg text-zinc-600 dark:text-zinc-400 hover:text-[#1447E6] dark:hover:text-blue-400 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-all animate-in fade-in slide-in-from-bottom-2 duration-300 z-20 group"
          title={language === "th" ? "เลื่อนลงล่างสุด" : "Scroll to bottom"}
        >
          <ArrowDown className="w-5 h-5 group-hover:animate-bounce" />
        </button>
      )}

      {/* Image Lightbox */}
      <ImageLightbox
        imageUrl={viewingImage}
        onClose={() => setViewingImage(null)}
      />

      {/* Input Area */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileSelect}
        className="hidden"
        multiple
      />
      <ChatInput
        input={input}
        setInput={setInput}
        attachments={attachments}
        onRemoveAttachment={removeAttachment}
        onSend={handleSendClick}
        onStop={onStop}
        onFileSelect={() => fileInputRef.current?.click()}
        onPaste={handlePaste}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        isDragging={isDragging}
        isLoading={isLoading}
        isStreaming={isStreaming || false}
        isListening={isListening}
        speechError={speechError}
        onToggleListening={toggleListening}
        isUploading={isUploading}
        uploadError={uploadError ?? undefined}
        textareaRef={textareaRef as React.RefObject<HTMLTextAreaElement>}
        composerWorkspace={composerWorkspace}
        onComposerWorkspaceChange={onComposerWorkspaceChange}
        workspaceNeedsBind={workspaceNeedsBind}
        sessionId={activeChatId || undefined}
        clarifyEnabled={Boolean(activeChatId) && (isStreaming || isLoading)}
        approvalEnabled={Boolean(activeChatId)}
        onClarifyAnswered={onClarifyAnswered}
        contextUsage={contextUsage}
      />
    </div >
  );
};
