import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  Routes,
  Route,
  Navigate,
  useNavigate,
  useLocation,
  NavigateFunction,
} from "react-router-dom";
import { Sidebar, useSessionEvents } from "@/features/sidebar";
import { ChatInterface, getPresetModels } from "@/features/chat";
import { PreviewWindow } from "@/features/preview";
import { useWorkspaceHtmlBridge } from "@/features/preview/hooks/useWorkspaceHtmlBridge";
import { SettingsView, type SettingsTab } from "@/features/settings";
import { ErrorModal } from "@/components/ErrorModal";
import { OfflineBanner } from "@/components/OfflineBanner";
import { toastMessage, useToast } from "@/components/toast/ToastProvider";
import {
  Message,
  ChatSession,
  ModelConfig,
  AIProvider,
  MessageVersion,
  Attachment,
  ProcessStep,
  SessionCompressionAnchor,
} from "@/types";
import {
  listSessions,
  getSession,
  deleteSession,
  deleteAllSessions,
  renameSessionOnFirstMessage,
  ensureServerSessionId,
  isSessionNotFoundError,
  pickFirstUsableSessionId,
} from "@/services/hermes/sessions";
import { fetchSettings } from "@/features/settings/services/hermesSettings";
import {
  listWorkspaces,
  findWorkspaceInRegistry,
  resolveAllowedComposerWorkspace,
  switchComposerWorkspace,
} from "@/services/hermes/workspace";
import { composerNeedsServerWorkspaceBind } from "@/services/hermes/workspaceBind";
import {
  mapSessionDetailToChatSession,
  mapSessionSummariesToChatSessions,
  mapHermesMessagesToMessages,
} from "@/services/hermes/mappers";
import { reconcileSessionStreamMetadata } from "@/features/sidebar/utils/sessionRuntime";
import { modelProviderForHermes } from "@/services/hermes/models";
import {
  type HermesProfileSwitchResponse,
} from "@/services/hermes/profiles";
import type { HermesChatStartResult } from "@/types/hermes/chat";
import {
  cancelChatStream,
  reattachHermesChatStream,
  streamHermesChat,
} from "@/services/hermes/streamChat";
import { formatChatError } from "@/features/chat/utils/chatErrors";
import { consumeHermesStream } from "@/features/chat/utils/consumeHermesStream";
import {
  contextUsageFromHermesSession,
  mergeContextUsage,
  type SessionContextUsage,
} from "@/features/chat/utils/contextUsage";
import { finalizeRunningStepsInMessage } from "@/features/chat/utils/finalizeRunningProcessSteps";
import {
  FILES_PANEL_CONTENT,
  type PreviewPanelContentState,
  resolvePreviewPanelContentForStep,
} from "@/features/preview/previewPanelContent";
import { reduceClarifyEchoToSession } from "@/services/hermes/reduceStreamChunk";
import {
  mergePendingUserMessage,
  readActiveStreamId,
  resolveAssistantForReattach,
} from "@/features/chat/utils/sessionStreamReattach";
import {
  dedupeTranscriptMessages,
  mergeLocalAndServerTranscript,
} from "@/features/chat/utils/transcriptMerge";
import { Trash2 } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useUiPreferencesSync } from "@/hooks/useUiPreferencesSync";
import { useSessionStore } from "@/hooks/useSessionStore";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useAppearance } from "@/hooks/useAppearance";
import { useAgentModels } from "@/features/chat/hooks/useAgentModels";
import { generateUUID } from "@/lib/utils";
import { useAuthBoot, AuthPage, type AuthStatus } from "@/features/auth";
import { PostLoginRedirect } from "@/features/auth/components/PostLoginRedirect";
import { OnboardingOverlay, useOnboardingGate } from "@/features/onboarding";
import {
  ShellInsightsPanel,
  ShellKanbanPanel,
  ShellLogsPanel,
  ShellMemoryPanel,
  ShellPanelRoutes,
  ShellRouter,
  ShellSkillsPanel,
  ShellTasksPanel,
  ShellTerminalRoute,
} from "@/routes/ShellRouter";
import type { ShellPanelId } from "@/routes/ShellRouter";

// Define AppLayout props interface
type ShellPanel = Exclude<ShellPanelId, "chat">;

interface AppLayoutProps {
  shellPanel?: ShellPanel;
  /** @deprecated use shellPanel === "settings" */
  showSettings?: boolean;
  isMobile: boolean;
  /** Use full-screen files panel (tablet / narrow desktop). */
  isPreviewOverlay?: boolean;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
  history: ChatSession[];
  activeChatId: string;
  handleNewChat: () => void;
  handleSelectChat: (id: string) => void;
  onRequestDeleteChat: (id: string) => void;
  onPinSession: (id: string, pinned: boolean) => void;
  modelConfig: ModelConfig;
  handleProviderChange: (provider: AIProvider) => void;
  navigate: NavigateFunction;
  onAuthRefresh: () => void;
  settingsTab: SettingsTab;
  setModelConfig: React.Dispatch<React.SetStateAction<ModelConfig>>;
  chatHistory: ChatSession[];
  handleClearAllChats: () => Promise<boolean>;
  currentMessages: Message[];
  contextUsage?: SessionContextUsage;
  compressionAnchor?: SessionCompressionAnchor;
  inputValue: string;
  setInputValue: (value: string) => void;
  handleSend: (
    message: string,
    attachments?: Attachment[],
    preferredSessionId?: string,
  ) => Promise<void>;
  handleStop: () => void;
  handleRegenerate: (messageId: string) => Promise<void>;
  handleEditUserMessage: (
    messageId: string,
    newContent: string,
  ) => Promise<void>;
  isLoading: boolean;
  isStreaming: boolean;
  loadingChatId: string | null;
  onCancelSession: (sessionId: string) => void;
  handleVersionChange: (messageId: string, newIndex: number) => void;
  handleAIVersionChange: (messageId: string, newIndex: number) => void;
  handleRegenVersionChange: (messageId: string, aiIndex: number, regenIndex: number) => void;
  isPreviewOpen: boolean;
  handlePreviewRequest: (html: string) => void;
  setIsPreviewOpen: (open: boolean) => void;
  previewPanelContent: PreviewPanelContentState;
  onBackToPreviewFiles: () => void;
  onOpenToolInPreview: (step: ProcessStep) => void;
  chatToDelete: string | null;
  setChatToDelete: (id: string | null) => void;
  t: (key: string) => string;
  confirmDeleteChat: () => void;
  chatInputRef: React.RefObject<HTMLTextAreaElement | null>;
  agentModels: { id: string; name: string; desc: string }[];
  pinnedAgentId: string | null;
  onPinAgent: (modelId: string) => void;
  /** Resolved name for current chat's agent (avoids "Select Agent" flash on refresh) */
  resolvedAgentName?: string;
  authStatus?: AuthStatus | null;
  composerWorkspace?: string;
  onComposerWorkspaceChange?: (path: string, name: string) => void | Promise<void>;
  onProfileSwitched?: (result: HermesProfileSwitchResponse) => void;
  sessionReady?: boolean;
  sessionWorkspace?: string;
  /** Ensure server session for composer uploads (legacy newSession parity). */
  ensureComposerSession?: (options?: {
    navigate?: boolean;
    activate?: boolean;
  }) => Promise<string>;
  /** Composer shows a workspace but session is not bound yet (re-enable picker reselect). */
  workspaceNeedsBind?: boolean;
  workspaceBindPending?: boolean;
  filesListEnabled?: boolean;
  onClarifyAnswered?: (payload: {
    question: string;
    answer: string;
    displayContent: string;
  }) => void;
}

// AppLayout component extracted outside to prevent recreation
const AppLayout: React.FC<AppLayoutProps> = React.memo(
  ({
    shellPanel,
    showSettings = false,
    isMobile,
    isPreviewOverlay = false,
    isSidebarOpen,
    setIsSidebarOpen,
    history,
    activeChatId,
    handleNewChat,
    handleSelectChat,
    onRequestDeleteChat,
    onPinSession,
    modelConfig,
    handleProviderChange,
    navigate,
    onAuthRefresh,
    settingsTab,
    setModelConfig,
    chatHistory,
    handleClearAllChats,
    currentMessages,
    contextUsage,
    compressionAnchor,
    inputValue,
    setInputValue,
    handleSend,
    handleStop,
    handleRegenerate,
    handleEditUserMessage,
    isLoading,
    isStreaming,
    loadingChatId,
    onCancelSession,
    handleVersionChange,
    handleAIVersionChange,
    handleRegenVersionChange,
    isPreviewOpen,
    handlePreviewRequest,
    setIsPreviewOpen,
    previewPanelContent,
    onBackToPreviewFiles,
    onOpenToolInPreview,
    chatToDelete,
    setChatToDelete,
    t,
    confirmDeleteChat,
    chatInputRef,
    agentModels = [],
    pinnedAgentId = null,
    onPinAgent,
    resolvedAgentName,
    authStatus = null,
    composerWorkspace = "",
    onComposerWorkspaceChange,
    onProfileSwitched,
    ensureComposerSession,
    sessionReady = true,
    sessionWorkspace = "",
    workspaceNeedsBind = false,
    workspaceBindPending = false,
    onClarifyAnswered,
  }) => {
    const composerWs = composerWorkspace.trim();
    const sessionWs = sessionWorkspace.trim();
    const filesListEnabled =
      Boolean(composerWs) || (sessionReady && Boolean(sessionWs));
    const activePanel: ShellPanel | undefined =
      shellPanel ?? (showSettings ? "settings" : undefined);
    const isSettingsOverlay = activePanel === "settings";
    return (
    <div className="flex h-screen w-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-50 overflow-hidden relative transition-colors duration-200">
      {/* Mobile Sidebar Backdrop */}
      {isMobile && isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* Narrow-viewport files panel backdrop (mirrors left sidebar drawer) */}
      {(isMobile || isPreviewOverlay) && isPreviewOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setIsPreviewOpen(false)}
        />
      )}

      {/* Settings is full-width overlay; workspace panels keep the chat sidebar */}
        {!isSettingsOverlay && (
        <Sidebar
          history={history}
          activeChatId={activeChatId}
          agentModels={agentModels}
          loadingChatId={loadingChatId}
          isActivePaneStreaming={isStreaming}
          onCancelSession={onCancelSession}
          onNewChat={handleNewChat}
          onSelectChat={handleSelectChat}
          onDeleteChat={onRequestDeleteChat}
          onPinSession={onPinSession}
          activeProvider={modelConfig.provider}
          onProviderChange={handleProviderChange}
          onOpenSettings={() => {
            navigate("/settings/general");
          }}
          isOpen={isSidebarOpen}
          toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          isMobile={isMobile}
          onLogout={() => {
            onAuthRefresh();
            navigate("/login");
          }}
          modelConfig={modelConfig}
          onModelConfigChange={setModelConfig}
        // Assuming App.tsx doesn't natively have mcpServers state pulled out yet
        />
      )}

      <div className="flex-1 flex flex-col h-full min-w-0 relative z-0 overflow-hidden isolate">
        {activePanel === "settings" ? (
          <div key="settings" className="h-full w-full animate-page-enter-left">
          <SettingsView
            modelConfig={modelConfig}
            onModelConfigChange={setModelConfig}
            onBack={() => navigate("/chat")}
            chatHistory={chatHistory}
            onDeleteChat={onRequestDeleteChat}
            onClearAllChats={handleClearAllChats}
            initialTab={settingsTab}
            onTabChange={(tab) => navigate(`/settings/${tab}`)}
          />
          </div>
        ) : activePanel === "kanban" ? (
          <div key="kanban" className="h-full w-full animate-page-enter-left">
            <ShellKanbanPanel onBack={() => navigate("/chat")} />
          </div>
        ) : activePanel === "tasks" ? (
          <div key="tasks" className="h-full w-full animate-page-enter-left">
            <ShellTasksPanel onBack={() => navigate("/chat")} />
          </div>
        ) : activePanel === "skills" ? (
          <div key="skills" className="h-full w-full animate-page-enter-left">
            <ShellSkillsPanel onBack={() => navigate("/chat")} />
          </div>
        ) : activePanel === "terminal" ? (
          <div key="terminal" className="h-full w-full animate-page-enter-left">
            <ShellTerminalRoute
              sessionId={activeChatId}
              workspacePath={composerWorkspace}
              ensureSession={ensureComposerSession}
              onBack={() => navigate("/chat")}
            />
          </div>
        ) : activePanel === "memory" ? (
          <div key="memory" className="h-full w-full animate-page-enter-left">
            <ShellMemoryPanel onBack={() => navigate("/chat")} />
          </div>
        ) : activePanel === "insights" ? (
          <div key="insights" className="h-full w-full animate-page-enter-left">
            <ShellInsightsPanel onBack={() => navigate("/chat")} authStatus={authStatus} />
          </div>
        ) : activePanel === "logs" ? (
          <div key="logs" className="h-full w-full animate-page-enter-left">
            <ShellLogsPanel onBack={() => navigate("/chat")} authStatus={authStatus} />
          </div>
        ) : (
          <div className="flex min-h-0 min-w-0 flex-1 flex-row overflow-hidden">
          <div key="chat" className="flex min-h-0 min-w-0 flex-1 flex-col h-full w-full animate-page-enter">
          <>
            <ChatInterface
              messages={currentMessages}
              contextUsage={contextUsage}
              compressionAnchor={compressionAnchor}
              input={inputValue}
              setInput={setInputValue}
              onSend={handleSend}
              onStop={handleStop}
              onRegenerate={handleRegenerate}
              onEdit={handleEditUserMessage}
              isLoading={isLoading}
              isStreaming={isStreaming}
              modelConfig={modelConfig}
              onModelConfigChange={setModelConfig}
              agentModels={agentModels}
              pinnedAgentId={pinnedAgentId}
              onPinAgent={onPinAgent}
              onProviderChange={handleProviderChange}
              onVersionChange={handleVersionChange}
              onAIVersionChange={handleAIVersionChange}
              onRegenVersionChange={handleRegenVersionChange}
              isPreviewOpen={isPreviewOpen}
              onPreviewRequest={handlePreviewRequest}
              onOpenSettings={() => navigate("/settings/general")}
              onLogout={() => {
                onAuthRefresh();
                navigate("/login");
              }}
              textareaRef={chatInputRef}
              isMobile={isMobile}
              onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
              loadingChatId={loadingChatId}
              activeChatId={activeChatId}
              resolvedAgentName={resolvedAgentName}
              resolvedAgentDescription={agentModels.find((a) => a.id === modelConfig.modelId)?.desc}
              composerWorkspace={composerWorkspace}
              onComposerWorkspaceChange={onComposerWorkspaceChange}
              onProfileSwitched={onProfileSwitched}
              ensureComposerSession={ensureComposerSession}
              workspaceNeedsBind={workspaceNeedsBind}
              onClarifyAnswered={onClarifyAnswered}
              onOpenPreview={() => setIsPreviewOpen(true)}
              onOpenToolInPreview={onOpenToolInPreview}
            />

          </>
          </div>
          <div className="flex min-h-0 min-w-0 shrink overflow-hidden">
            <PreviewWindow
              isOpen={isPreviewOpen}
              onToggle={() => setIsPreviewOpen(!isPreviewOpen)}
              isMobile={isMobile || isPreviewOverlay}
              isSidebarOpen={isSidebarOpen}
              isLoading={isLoading || isStreaming}
              chatId={activeChatId}
              sessionReady={sessionReady}
              sessionWorkspace={sessionWorkspace}
              workspacePath={composerWorkspace}
              workspaceBindPending={workspaceBindPending}
              filesListEnabled={filesListEnabled}
              ensureComposerSession={ensureComposerSession}
              panelContent={previewPanelContent}
              onBackToFiles={onBackToPreviewFiles}
            />
          </div>
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      {chatToDelete && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-modal-backdrop"
          onClick={() => setChatToDelete(null)}
        >
          <div
            className="bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 w-full max-w-sm rounded-xl shadow-2xl overflow-hidden animate-modal-content"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 text-center">
              <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-500" />
              </div>
              <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mb-2">
                {t("common.deleteTitle")}
              </h3>
              <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
                {t("common.deleteWarning")}
              </p>

              <div className="flex gap-3">
                <button
                  onClick={() => setChatToDelete(null)}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                >
                  {t("common.cancel")}
                </button>
                <button
                  onClick={confirmDeleteChat}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white transition-colors"
                >
                  {t("common.delete")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
    );
  },
);

export default function App() {
  const { t } = useLanguage();
  const toast = useToast();
  const { autoExpandSidebarOnTool } = useAppearance();
  const navigate = useNavigate();
  const location = useLocation();
  const chatInputRef = useRef<HTMLTextAreaElement>(null);

  // Auth boot — Hermes GET /api/v1/auth/status (M01 / M33-App)
  const { ready: authBootReady, isAuthenticated, status: authStatus, refresh: refreshAuth, establishSession } =
    useAuthBoot();
  const { showOnboarding, dismissOnboarding } = useOnboardingGate(isAuthenticated);
  useUiPreferencesSync(isAuthenticated);
  useWorkspaceHtmlBridge();

  const {
    sessions,
    setSessions,
    activeChatId,
    activeChatIdRef,
    setActiveChat: setActiveChatIdSynced,
    confirmedSessionIds,
    serverSessionIdsRef,
    rejectedSessionIdsRef,
    confirmSessionId,
    syncConfirmedSessionIds,
    rejectStaleSessionId,
    clearRejectedSessionIds,
    resetSessions,
  } = useSessionStore({ navigate, pathname: location.pathname });
  const [inputValue, setInputValue] = useState("");
  const [composerWorkspace, setComposerWorkspace] = useState("");
  /** Workspace bound on the active Hermes session (required for GET /list). */
  const [activeSessionWorkspace, setActiveSessionWorkspace] = useState("");
  const composerWorkspaceRef = useRef(composerWorkspace);
  /** Chat id for which composerWorkspace was last hydrated from server session. */
  const composerHydratedForChatRef = useRef<string>("");
  /** Server session created for pre-send uploads without switching the active chat. */
  const composerDraftSessionIdRef = useRef<string | null>(null);
  /** Hydrate model picker from session.flowId only when switching chats, not after user picks a model. */
  const modelSyncedForChatRef = useRef<string | null>(null);
  useEffect(() => {
    composerWorkspaceRef.current = composerWorkspace;
  }, [composerWorkspace]);
  const { activeProfile } = useActiveProfile();
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [chatToDelete, setChatToDelete] = useState<string | null>(null);
  const [loadingChatId, setLoadingChatId] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeReattachKeysRef = useRef<Set<string>>(new Set());

  // Error Modal State
  const [showErrorModal, setShowErrorModal] = useState(false);
  const [errorModalConfig, setErrorModalConfig] = useState({
    title: "",
    message: "",
    type: "error" as "error" | "warning",
  });


  // View State
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("general");

  // Responsive State — initialize from viewport so docked preview never paints on first frame
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < 1024 : false,
  );
  /** Full-screen files panel below this width (avoids squeezing chat beside preview). */
  const [isPreviewOverlay, setIsPreviewOverlay] = useState(() =>
    typeof window !== "undefined" ? window.innerWidth < 1280 : false,
  );
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [previewPanelContent, setPreviewPanelContent] =
    useState<PreviewPanelContentState>(FILES_PANEL_CONTENT);

  // Initialize responsive state
  useEffect(() => {
    const handleResize = () => {
      const mobile = window.innerWidth < 1024;
      const previewOverlay = window.innerWidth < 1280;
      setIsMobile(mobile);
      setIsPreviewOverlay(previewOverlay);
    };

    // Set initial
    const initialMobile = window.innerWidth < 1024;
    setIsMobile(initialMobile);
    setIsPreviewOverlay(window.innerWidth < 1280);
    setIsSidebarOpen(!initialMobile);
    setIsPreviewOpen(false); // Default to closed

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const [modelConfig, setModelConfig] = useState<ModelConfig>(() => ({
    provider: "openai",
    modelProvider: undefined,
    baseUrl: "",
    modelId: "",
    name: "Select Agent",
    mcpServers: [],
    enabledConnections: [],
    enabledModels: [],
    systemPrompt: "You are a helpful AI assistant focused on technical tasks.",
    voiceDelay: 0.5,
  }));

  // Update "New Task" title when language changes for empty sessions
  useEffect(() => {
    setSessions((prev) => {
      const updated = { ...prev };
      Object.keys(updated).forEach((key) => {
        if (updated[key].messages.length === 0) {
          updated[key].title = t("sidebar.newTask");
        }
      });
      return updated;
    });
  }, [t]);

  // Ref for checking streaming status in useEffects without dependency
  const isStreamingRef = useRef(isStreaming);
  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  /** Set when user clicks New Task — blocks refreshSessions from reopening the latest chat. */
  const preferBlankChatRef = useRef(false);

  // Sync URL to state; skip ids rejected by GET /session (stale bookmarks / deleted sessions).
  useEffect(() => {
    const match = location.pathname.match(/\/chat\/([^/]+)/);
    if (match) {
      const id = decodeURIComponent(match[1]);
      if (rejectedSessionIdsRef.current.has(id)) {
        if (activeChatIdRef.current === id) {
          setActiveChatIdSynced("");
        }
        navigate("/chat", { replace: true });
        return;
      }
      if (id !== activeChatIdRef.current) {
        setActiveChatIdSynced(id);
        setLoadingChatId(id);
      }
      return;
    }
    // Bare /chat: do not force-clear activeChatId (sidebar/refresh may select without URL yet).
  }, [location.pathname, navigate, setActiveChatIdSynced]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    void (async () => {
      try {
        const [settingsResult, registry] = await Promise.all([
          fetchSettings().catch(() => null),
          listWorkspaces(),
        ]);
        if (cancelled) return;

        const defaultWs =
          settingsResult &&
          typeof settingsResult.default_workspace === "string"
            ? settingsResult.default_workspace.trim()
            : "";

        setComposerWorkspace((prev) => {
          const validatedPrev = prev.trim()
            ? findWorkspaceInRegistry(registry.workspaces, prev)?.path
            : "";
          if (validatedPrev) return validatedPrev;

          const preferred = defaultWs || prev.trim();
          const { path } = resolveAllowedComposerWorkspace(preferred, registry);
          return path;
        });

        if (
          defaultWs &&
          !findWorkspaceInRegistry(registry.workspaces, defaultWs)
        ) {
          console.warn(
            "Default workspace is not in the allowed registry; using fallback:",
            defaultWs,
          );
        }
      } catch {
        /* non-fatal boot hydration */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (composerHydratedForChatRef.current !== activeChatId) {
      composerHydratedForChatRef.current = "";
      setActiveSessionWorkspace("");
    }
  }, [activeChatId]);

  const activeSessionConfirmed = confirmedSessionIds.has(activeChatId);

  /** Bind composer workspace to the active session when server session.workspace lags the composer. */
  useEffect(() => {
    const ws = composerWorkspace.trim();
    const sid = activeChatId;
    if (!sid || !ws) return;
    if (rejectedSessionIdsRef.current.has(sid)) return;
    if (!activeSessionConfirmed) return;

    let cancelled = false;
    void (async () => {
      try {
        const { session } = await getSession(sid);
        if (cancelled) return;
        const serverWs =
          typeof session.workspace === "string" ? session.workspace : "";
        if (!composerNeedsServerWorkspaceBind(ws, serverWs)) {
          if (serverWs.trim()) {
            setActiveSessionWorkspace(serverWs.trim());
          }
          return;
        }
        const result = await switchComposerWorkspace({
          path: ws,
          sessionId: sid,
          modelConfig,
        });
        if (cancelled) return;
        setComposerWorkspace(result.path);
        setActiveSessionWorkspace(result.path);
      } catch (err) {
        if (isSessionNotFoundError(err)) {
          rejectStaleSessionId(sid);
          return;
        }
        console.warn("Failed to bind workspace to session:", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeChatId, activeSessionConfirmed, composerWorkspace, modelConfig, rejectStaleSessionId]);

  const bindComposerWorkspaceToSession = useCallback(
    async (sessionId: string): Promise<string | null> => {
      const ws = composerWorkspaceRef.current.trim();
      if (!ws || !sessionId) return null;
      if (!serverSessionIdsRef.current.has(sessionId)) return ws;
      try {
        const { session } = await getSession(sessionId);
        const serverWs =
          typeof session.workspace === "string" ? session.workspace.trim() : "";
        if (!composerNeedsServerWorkspaceBind(ws, serverWs)) {
          return ws;
        }
        const result = await switchComposerWorkspace({
          path: ws,
          sessionId,
          modelConfig,
        });
        return result.path;
      } catch (err) {
        if (isSessionNotFoundError(err)) {
          throw err;
        }
        console.warn("Failed to bind composer workspace to session:", err);
        return ws;
      }
    },
    [modelConfig],
  );

  const handleComposerWorkspaceChange = useCallback(
    async (path: string, name: string) => {
      const trimmed = path.trim();
      if (!trimmed) return;

      let registry = await listWorkspaces();
      const existing = findWorkspaceInRegistry(registry.workspaces, trimmed);
      const resolvedPath = existing?.path ?? trimmed;

      setComposerWorkspace(resolvedPath);
      setActiveSessionWorkspace(resolvedPath);

      const sid = activeChatIdRef.current;
      if (sid && !rejectedSessionIdsRef.current.has(sid)) {
        composerHydratedForChatRef.current = sid;
        if (serverSessionIdsRef.current.has(sid)) {
          const result = await switchComposerWorkspace({
            path: resolvedPath,
            name,
            sessionId: sid,
            modelConfig,
          });
          setComposerWorkspace(result.path);
          setActiveSessionWorkspace(result.path);
        }
        // Unconfirmed sessions: auto-bind effect updates server workspace once confirmed.
      } else {
        composerHydratedForChatRef.current = sid || "";
      }
    },
    [modelConfig],
  );

  const ensureComposerSession = useCallback(async (options?: {
    navigate?: boolean;
    activate?: boolean;
  }): Promise<string> => {
    const shouldNavigate = options?.navigate !== false;
    const shouldActivate = options?.activate !== false;
    const sessionModelProvider = modelProviderForHermes(modelConfig);
    const createOptions = {
      model: modelConfig.modelId || undefined,
      workspace: composerWorkspace || undefined,
      profile: activeProfile || "default",
      ...(sessionModelProvider ? { modelProvider: sessionModelProvider } : {}),
    };

    let id = activeChatIdRef.current;
    const previousId = id;
    if (!id || !serverSessionIdsRef.current.has(id)) {
      const draftId = composerDraftSessionIdRef.current;
      if (draftId && serverSessionIdsRef.current.has(draftId)) {
        id = draftId;
      } else {
        id = await ensureServerSessionId(
          id || draftId || undefined,
          serverSessionIdsRef.current,
          createOptions,
        );
      }
      confirmSessionId(id);
    }

    if (!shouldActivate) {
      composerDraftSessionIdRef.current = id;
      return id;
    }

    composerDraftSessionIdRef.current = null;

    const ws = composerWorkspace.trim();
    if (ws) {
      try {
        const { session } = await getSession(id);
        const serverWs =
          typeof session.workspace === "string" ? session.workspace.trim() : "";
        if (composerNeedsServerWorkspaceBind(ws, serverWs)) {
          const result = await switchComposerWorkspace({
            path: ws,
            sessionId: id,
            modelConfig,
          });
          setComposerWorkspace(result.path);
          setActiveSessionWorkspace(result.path);
        } else if (serverWs) {
          setActiveSessionWorkspace(serverWs);
        }
      } catch (err) {
        if (isSessionNotFoundError(err)) {
          rejectStaleSessionId(id);
          throw err;
        }
        console.warn("Failed to bind workspace for composer session:", err);
      }
    }

    setSessions((prev) => {
      if (prev[id]) return prev;
      return {
        ...prev,
        [id]: {
          id,
          title: t("sidebar.newTask"),
          messages: [],
          updatedAt: Date.now(),
          ...(modelConfig.modelId
            ? { flowId: modelConfig.modelId, flowName: modelConfig.name }
            : {}),
        },
      };
    });

    if (activeChatIdRef.current !== id) {
      setActiveChatIdSynced(id);
      if (shouldNavigate) {
        navigate(`/chat/${id}`);
      }
    } else if (previousId !== id) {
      setActiveChatIdSynced(id);
      if (shouldNavigate) {
        navigate(`/chat/${id}`);
      }
    }

    return id;
  }, [
    activeProfile,
    composerWorkspace,
    confirmSessionId,
    modelConfig,
    navigate,
    rejectStaleSessionId,
    setActiveChatIdSynced,
    t,
  ]);

  // Fetch Hermes sessions on mount / auth / SSE refresh (M17 / M33)
  const refreshSessions = useCallback(async () => {
    if (!isAuthenticated) return;

    const rejected = rejectedSessionIdsRef.current;
    const { sessions: summaries } = await listSessions();
    const fetchedSessions = mapSessionSummariesToChatSessions(summaries).filter(
      (s) => !rejected.has(s.id),
    );
    const serverIds = new Set(fetchedSessions.map((s) => s.id));
    const activeBeforeSync = activeChatIdRef.current;
    const preserveActiveOnListLag =
      Boolean(activeBeforeSync) &&
      !rejected.has(activeBeforeSync) &&
      serverSessionIdsRef.current.has(activeBeforeSync);
    syncConfirmedSessionIds(serverIds);
    if (preserveActiveOnListLag && activeBeforeSync && !serverIds.has(activeBeforeSync)) {
      confirmSessionId(activeBeforeSync);
    }

    if (fetchedSessions.length > 0) {
      setSessions((prev) => {
        const newSessionsMap: Record<string, ChatSession> = {};
        fetchedSessions.forEach((s) => {
          const existing = prev[s.id];
          if (existing && existing.messages.length > 0) {
            newSessionsMap[s.id] = {
              ...s,
              messages: existing.messages,
              flowName: existing.flowName ?? s.flowName,
              pinned: s.pinned ?? existing.pinned,
              projectId: s.projectId ?? existing.projectId,
              contextUsage: existing.contextUsage ?? s.contextUsage,
              compressionAnchor: existing.compressionAnchor ?? s.compressionAnchor,
              ...reconcileSessionStreamMetadata(existing, s),
            };
          } else {
            newSessionsMap[s.id] = s;
          }
        });

        const currentActiveId = activeChatIdRef.current;

        if (isStreamingRef.current && currentActiveId && prev[currentActiveId]) {
          const live = prev[currentActiveId];
          newSessionsMap[currentActiveId] = {
            ...newSessionsMap[currentActiveId],
            ...live,
            messages: live.messages,
            activeStreamId:
              live.activeStreamId ?? newSessionsMap[currentActiveId]?.activeStreamId,
            isStreaming: true,
          };
        }

        return newSessionsMap;
      });

      const currentActiveId = activeChatIdRef.current;
      const firstUsableId = pickFirstUsableSessionId(fetchedSessions, rejected);
      const currentRejected =
        Boolean(currentActiveId) && rejected.has(currentActiveId);
      const currentMissing =
        Boolean(currentActiveId) && !serverIds.has(currentActiveId);
      const onBareChatRoute = !location.pathname.match(/\/chat\/([^/]+)/);
      const wantsBlankNewChat =
        preferBlankChatRef.current ||
        (onBareChatRoute &&
          !currentActiveId &&
          !currentRejected &&
          !currentMissing);
      const activePendingListSync =
        Boolean(currentActiveId) &&
        currentMissing &&
        serverSessionIdsRef.current.has(currentActiveId);

      if (
        firstUsableId &&
        (!currentActiveId || currentRejected || currentMissing) &&
        !isStreamingRef.current &&
        !wantsBlankNewChat &&
        !activePendingListSync
      ) {
        setActiveChatIdSynced(firstUsableId);
        navigate(`/chat/${firstUsableId}`, { replace: true });
      } else if (currentRejected && !firstUsableId) {
        setActiveChatIdSynced("");
        navigate("/chat", { replace: true });
      }
    } else {
      syncConfirmedSessionIds(new Set());
      setSessions((prev) => {
        if (Object.keys(prev).length === 0) {
          return {};
        }
        if (isStreamingRef.current) {
          return prev;
        }
        return {};
      });
      if (!isStreamingRef.current && activeChatIdRef.current) {
        setActiveChatIdSynced("");
        if (location.pathname.match(/\/chat\/([^/]+)/)) {
          navigate("/chat", { replace: true });
        }
      }
    }
  }, [
    isAuthenticated,
    navigate,
    location.pathname,
    setActiveChatIdSynced,
    syncConfirmedSessionIds,
    confirmSessionId,
  ]);

  const { agentModels, pinnedAgentId, handlePinAgent, reloadModels } = useAgentModels({
    modelConfig,
    onModelConfigChange: setModelConfig,
    enabled: isAuthenticated,
  });

  const applyEffectiveModelFromChatStart = useCallback(
    (start: HermesChatStartResult) => {
      if (start.effective_model) {
        const matched = agentModels.find((m) => m.id === start.effective_model);
        setModelConfig((prev) => ({
          ...prev,
          modelId: start.effective_model!,
          name: matched?.name || prev.name,
          modelProvider:
            (typeof start.effective_model_provider === "string"
              ? start.effective_model_provider
              : start.effective_model_provider === null
                ? undefined
                : prev.modelProvider) ??
            matched?.hermesProvider ??
            prev.modelProvider,
        }));
        try {
          localStorage.setItem("hermes-webui-model", start.effective_model);
        } catch {}
      } else if (start.effective_model_provider) {
        setModelConfig((prev) => ({
          ...prev,
          modelProvider:
            typeof start.effective_model_provider === "string"
              ? start.effective_model_provider
              : prev.modelProvider,
        }));
      }
    },
    [agentModels],
  );

  const handleProfileSwitched = useCallback(
    (result: HermesProfileSwitchResponse) => {
      preferBlankChatRef.current = true;
      clearRejectedSessionIds();
      setActiveChatIdSynced("");
      setActiveSessionWorkspace("");
      composerHydratedForChatRef.current = "";
      navigate("/chat");
      void (async () => {
        try {
          const registry = await listWorkspaces();
          const preferred =
            typeof result.default_workspace === "string"
              ? result.default_workspace.trim()
              : "";
          const { path, matched } = resolveAllowedComposerWorkspace(
            preferred,
            registry,
          );
          if (path) {
            setComposerWorkspace(path);
          }
          if (preferred && !matched) {
            console.warn(
              "Profile default workspace is not allowed; using fallback:",
              preferred,
            );
            setErrorModalConfig({
              title: t("chat.workspacePicker") || "Workspace",
              message: t("chat.workspaceNotAllowed"),
              type: "warning",
            });
            setShowErrorModal(true);
          }
        } catch {
          if (result.default_workspace) {
            setComposerWorkspace(result.default_workspace);
          }
        }
      })();
      if (result.default_model) {
        const defaultModelId = result.default_model;
        const matched = agentModels.find((m) => m.id === defaultModelId);
        setModelConfig((prev) => ({
          ...prev,
          modelId: defaultModelId,
          name: matched?.name || prev.name,
          modelProvider:
            (typeof result.default_model_provider === "string"
              ? result.default_model_provider
              : undefined) ||
            matched?.hermesProvider ||
            undefined,
        }));
      }
      void reloadModels({ modelsOnly: true });
      void refreshSessions();
    },
    [agentModels, navigate, reloadModels, refreshSessions, setActiveChatIdSynced, t],
  );

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions, modelConfig.modelId]);

  useSessionEvents({
    enabled: isAuthenticated,
    onSessionListChanged: () => {
      void refreshSessions();
    },
  });

  const clearSessionStreamFlags = useCallback((sessionId: string) => {
    setSessions((prev) => {
      const session = prev[sessionId];
      if (!session) return prev;
      return {
        ...prev,
        [sessionId]: {
          ...session,
          activeStreamId: undefined,
          isStreaming: false,
        },
      };
    });
  }, []);

  const applySessionContextUsage = useCallback(
    (sessionId: string, patch: SessionContextUsage) => {
      setSessions((prev) => {
        const session = prev[sessionId];
        if (!session) return prev;
        return {
          ...prev,
          [sessionId]: {
            ...session,
            contextUsage: mergeContextUsage(session.contextUsage, patch),
          },
        };
      });
    },
    [],
  );

  const syncSessionMessagesAfterStream = useCallback(
    async (sessionId: string) => {
      try {
        const { session: serverSession } = await getSession(sessionId);
        confirmSessionId(sessionId);
        const serverWs =
          typeof serverSession.workspace === "string"
            ? serverSession.workspace.trim()
            : "";
        if (serverWs) {
          const composer = composerWorkspaceRef.current.trim();
          if (!composer) {
            setComposerWorkspace(serverWs);
            setActiveSessionWorkspace(serverWs);
          } else if (!composerNeedsServerWorkspaceBind(composer, serverWs)) {
            setComposerWorkspace(serverWs);
            setActiveSessionWorkspace(serverWs);
          } else {
            setActiveSessionWorkspace(composer);
          }
        }
        const serverTitle =
          typeof serverSession.title === "string" ? serverSession.title.trim() : "";
        const serverMessages = mapHermesMessagesToMessages(
          serverSession.messages,
          serverSession.tool_calls,
        );
        if (serverMessages.length === 0) return;

        const mappedSession = mapSessionDetailToChatSession(serverSession);
        setSessions((prev) => {
          const localSession = prev[sessionId];
          if (!localSession) return prev;

          const mergedMessages = dedupeTranscriptMessages(
            mergeLocalAndServerTranscript(localSession.messages, serverMessages),
          );

          return {
            ...prev,
            [sessionId]: {
              ...localSession,
              messages: mergedMessages,
              ...(serverTitle ? { title: serverTitle } : {}),
              ...(mappedSession.contextUsage
                ? {
                    contextUsage: mergeContextUsage(
                      localSession.contextUsage,
                      mappedSession.contextUsage,
                    ),
                  }
                : {}),
              compressionAnchor: mappedSession.compressionAnchor,
              ...reconcileSessionStreamMetadata(localSession, mappedSession),
            },
          };
        });
      } catch (syncError) {
        console.warn("Post-stream sync failed:", syncError);
      }
    },
    [confirmSessionId],
  );

  const resumeHermesSessionStream = useCallback(
    async (sessionId: string, streamId: string, historyMessages: Message[]) => {
      if (isStreamingRef.current) return;
      if (activeChatIdRef.current !== sessionId) return;
      const reattachKey = `${sessionId}:${streamId}`;
      if (activeReattachKeysRef.current.has(reattachKey)) return;
      activeReattachKeysRef.current.add(reattachKey);

      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      isStreamingRef.current = true;
      setIsStreaming(true);
      setIsLoading(true);

      const resolved = resolveAssistantForReattach(historyMessages);
      let assistantMsgId = resolved.assistantMsgId;
      const { accumulatedContent, appendAssistant } = resolved;
      if (appendAssistant) {
        // Deterministic id avoids duplicate placeholder bubbles across rapid
        // reattach attempts for the same stream.
        assistantMsgId = `reattach-${streamId}`;
      }

      if (appendAssistant) {
        const placeholder: Message = {
          id: assistantMsgId,
          role: "assistant",
          content: accumulatedContent,
          timestamp: Date.now(),
          blocks: [],
          versions: [
            {
              content: accumulatedContent,
              blocks: [],
              timestamp: Date.now(),
            },
          ],
          currentVersionIndex: 0,
          needsSuggestions: true,
        };
        setSessions((prev) => {
          const existing = prev[sessionId];
          const baseMessages = existing?.messages?.length
            ? existing.messages
            : historyMessages;
          const normalizedMessages = baseMessages.filter((m) => {
            if (!m.id.startsWith("reattach-")) return true;
            if (m.id === assistantMsgId) return true;
            const noText = !(m.content || "").trim();
            const noSteps = !m.steps || m.steps.length === 0;
            return !(m.role === "assistant" && noText && noSteps);
          });
          if (normalizedMessages.some((m) => m.id === assistantMsgId)) {
            return prev;
          }
          return {
            ...prev,
            [sessionId]: {
              ...existing,
              id: sessionId,
              title: existing?.title || "Untitled",
              messages: [...normalizedMessages, placeholder],
              messageCount: (existing?.messageCount ?? normalizedMessages.length) + 1,
              updatedAt: existing?.updatedAt || Date.now(),
            },
          };
        });
      }

      try {
        await consumeHermesStream({
          activeSessionId: sessionId,
          assistantMsgId,
          // Reattach should always patch the existing/placeholder assistant bubble,
          // never create a second assistant message on first incoming chunk.
          targetMessageId: assistantMsgId,
          initialAccumulatedContent: accumulatedContent,
          stream: reattachHermesChatStream({
            streamId,
            sessionId,
            signal: abortController.signal,
            onSessionTitle: (sid, title) => {
              setSessions((prev) => {
                const chat = prev[sid];
                if (!chat) return prev;
                return {
                  ...prev,
                  [sid]: { ...chat, title },
                };
              });
            },
            onContextUsage: (usage) => applySessionContextUsage(sessionId, usage),
          }),
          setSessions,
          setIsLoading,
          isStreamingRef,
          setIsStreaming,
          abortControllerRef,
          autoExpandSidebarOnTool,
          isPreviewOpen,
          isSettingsOpen,
          setIsPreviewOpen,
          setPreviewPanelContent,
          clearSessionStreamFlags,
        });
        await syncSessionMessagesAfterStream(sessionId);
      } catch (error) {
        const isAbortError =
          error instanceof DOMException && error.name === "AbortError";
        if (isAbortError) return;
        console.warn("Failed to reattach Hermes chat stream:", error);
      } finally {
        activeReattachKeysRef.current.delete(reattachKey);
        setIsLoading(false);
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
        }
        isStreamingRef.current = false;
        setIsStreaming(false);
        clearSessionStreamFlags(sessionId);
      }
    },
    [
      autoExpandSidebarOnTool,
      applySessionContextUsage,
      clearSessionStreamFlags,
      isPreviewOpen,
      isSettingsOpen,
      syncSessionMessagesAfterStream,
    ],
  );

  useEffect(() => {
    if (!activeChatId || !isAuthenticated) return;
    if (rejectedSessionIdsRef.current.has(activeChatId)) {
      rejectStaleSessionId(activeChatId);
      return;
    }

    const loadHistory = async () => {
      if (isStreamingRef.current) return;

      try {
        const { session } = await getSession(activeChatId);
        rejectedSessionIdsRef.current.delete(activeChatId);
        confirmSessionId(activeChatId);
        const serverWorkspace =
          typeof session.workspace === "string" ? session.workspace.trim() : "";
        const hydrateComposer =
          composerHydratedForChatRef.current !== activeChatId;
        if (hydrateComposer) {
          composerHydratedForChatRef.current = activeChatId;
          if (serverWorkspace) {
            try {
              const registry = await listWorkspaces();
              const composerNow = composerWorkspaceRef.current.trim();
              const composerInRegistry = composerNow
                ? findWorkspaceInRegistry(registry.workspaces, composerNow)?.path ?? ""
                : "";
              if (
                composerInRegistry &&
                composerNeedsServerWorkspaceBind(composerInRegistry, serverWorkspace)
              ) {
                setComposerWorkspace(composerInRegistry);
                setActiveSessionWorkspace(composerInRegistry);
              } else {
                const { path, matched } = resolveAllowedComposerWorkspace(
                  serverWorkspace,
                  registry,
                );
                if (path) {
                  setComposerWorkspace(path);
                  setActiveSessionWorkspace(path);
                }
                if (!matched) {
                  console.warn(
                    "Session workspace is not allowed; using fallback:",
                    serverWorkspace,
                  );
                }
              }
            } catch {
              if (
                composerWorkspaceRef.current.trim() &&
                composerNeedsServerWorkspaceBind(
                  composerWorkspaceRef.current,
                  serverWorkspace,
                )
              ) {
                setComposerWorkspace(composerWorkspaceRef.current.trim());
                setActiveSessionWorkspace(composerWorkspaceRef.current.trim());
              } else {
                setComposerWorkspace(serverWorkspace);
                setActiveSessionWorkspace(serverWorkspace);
              }
            }
          } else if (!composerWorkspaceRef.current.trim()) {
            setActiveSessionWorkspace("");
          }
        } else if (serverWorkspace) {
          setActiveSessionWorkspace(serverWorkspace);
        }
        const serverMessages = mapHermesMessagesToMessages(
          session.messages,
          session.tool_calls,
        );
        const pendingUserMessage = mergePendingUserMessage(session, serverMessages);
        const messagesWithPending = pendingUserMessage
          ? [...serverMessages, pendingUserMessage]
          : serverMessages;
        const activeStreamId = readActiveStreamId(session);

        let messagesForReattach = messagesWithPending;
        const loadedContextUsage = contextUsageFromHermesSession(session);
        const loadedCompressionAnchor =
          mapSessionDetailToChatSession(session).compressionAnchor;

        setSessions(prev => {
          const existing = prev[activeChatId];
          if (!existing && messagesWithPending.length === 0) return prev;

          const localMessages = existing?.messages || [];
          const finalMessages = dedupeTranscriptMessages(
            mergeLocalAndServerTranscript(localMessages, messagesWithPending),
          );
          messagesForReattach = finalMessages;
          const messageCount =
            typeof session.message_count === "number"
              ? session.message_count
              : finalMessages.length;

          return {
            ...prev,
            [activeChatId]: {
              ...existing,
              id: activeChatId,
              title: session.title || existing?.title || "Untitled",
              messages: finalMessages,
              messageCount,
              updatedAt: existing?.updatedAt || Date.now(),
              ...(session.model ? { flowId: session.model, flowName: session.model } : {}),
              ...(loadedContextUsage
                ? {
                    contextUsage: mergeContextUsage(
                      existing?.contextUsage,
                      loadedContextUsage,
                    ),
                  }
                : {}),
              compressionAnchor: loadedCompressionAnchor,
            }
          };
        });

        if (activeStreamId) {
          void resumeHermesSessionStream(
            activeChatId,
            activeStreamId,
            messagesForReattach,
          );
        }
      } catch (error) {
        console.warn("Failed to load Hermes session history:", error);
        if (isSessionNotFoundError(error)) {
          rejectStaleSessionId(activeChatId);
        }
      }
    };

    loadHistory();
  }, [
    activeChatId,
    isAuthenticated,
    rejectStaleSessionId,
    confirmSessionId,
    resumeHermesSessionStream,
  ]);

  useEffect(() => {
    if (loadingChatId) {
      const timer = setTimeout(() => {
        setLoadingChatId(null);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [loadingChatId]);

  // When switching chats, load that session's model into the picker; do not override user picks mid-chat.
  useEffect(() => {
    if (!activeChatId) {
      modelSyncedForChatRef.current = null;
      return;
    }

    const session = sessions[activeChatId];
    const flowId = session?.flowId;
    const agent = flowId ? agentModels.find((a) => a.id === flowId) : undefined;
    const name = agent?.name ?? session?.flowName ?? session?.title ?? "";
    const hermesProvider = agent?.hermesProvider;
    const chatSwitched = modelSyncedForChatRef.current !== activeChatId;

    if (chatSwitched) {
      modelSyncedForChatRef.current = activeChatId;
      if (!flowId) return;
      setModelConfig((prev) => ({
        ...prev,
        modelId: flowId,
        name: name || prev.name,
        modelProvider: hermesProvider,
      }));
      return;
    }

    if (!flowId || !name) return;
    setModelConfig((prev) => {
      if (prev.modelId !== flowId) return prev;
      if (prev.name && prev.name !== "Select Agent" && prev.name !== "เลือก Agent") {
        return prev;
      }
      return {
        ...prev,
        name,
        modelProvider: hermesProvider ?? prev.modelProvider,
      };
    });
  }, [activeChatId, sessions, agentModels]);

  // Enrich sessions with flowName from agentModels so sidebar shows name immediately (no id-then-name flash)
  useEffect(() => {
    if (agentModels.length === 0) return;
    setSessions((prev) => {
      let changed = false;
      const next = { ...prev };
      Object.keys(next).forEach((id) => {
        const s = next[id];
        if (s?.flowId && !s.flowName) {
          const name = agentModels.find((a) => a.id === s.flowId)?.name;
          if (name) {
            next[id] = { ...s, flowName: name };
            changed = true;
          }
        }
      });
      return changed ? next : prev;
    });
  }, [agentModels]);

  const history = useMemo(() => {
    return (Object.values(sessions) as ChatSession[]).sort((a, b) => {
      const pinDelta = (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0);
      if (pinDelta !== 0) return pinDelta;
      return b.updatedAt - a.updatedAt;
    });
  }, [sessions]);

  const handlePinSession = useCallback((sessionId: string, pinned: boolean) => {
    setSessions((prev) => {
      const existing = prev[sessionId];
      if (!existing) return prev;
      return {
        ...prev,
        [sessionId]: { ...existing, pinned },
      };
    });
  }, []);

  const resolvedAgentName = useMemo(() => {
    if (!activeChatId || !sessions[activeChatId]?.flowId) return undefined;
    const session = sessions[activeChatId];
    return session.flowName ?? agentModels.find((a) => a.id === session.flowId)?.name;
  }, [activeChatId, sessions, agentModels]);

  const cachedAgentName = useMemo(() => {
    if (!activeChatId) return undefined;
    try {
      return sessionStorage.getItem(`agent_name_${activeChatId}`) || undefined;
    } catch {
      return undefined;
    }
  }, [activeChatId]);

  const displayAgentName = resolvedAgentName ?? cachedAgentName;

  useEffect(() => {
    if (activeChatId && resolvedAgentName) {
      try {
        sessionStorage.setItem(`agent_name_${activeChatId}`, resolvedAgentName);
      } catch {}
    }
  }, [activeChatId, resolvedAgentName]);

  const currentMessages = useMemo(() => {
    return sessions[activeChatId]?.messages || [];
  }, [sessions, activeChatId]);

  const currentContextUsage = useMemo(() => {
    return sessions[activeChatId]?.contextUsage;
  }, [sessions, activeChatId]);

  const currentCompressionAnchor = useMemo(() => {
    return sessions[activeChatId]?.compressionAnchor;
  }, [sessions, activeChatId]);

  const handleProviderChange = (newProvider: AIProvider) => {
    const models = getPresetModels(t);
    const defaultModel = models[newProvider][0];
    setModelConfig((prev) => ({
      ...prev,
      provider: newProvider,
      modelId: defaultModel.id,
      name: defaultModel.name,
      baseUrl: newProvider === "openai" ? "https://api.openai.com/v1" : "",
    }));
  };

  const handlePreviewRequest = (_html: string) => {
    if (!isPreviewOpen && !isSettingsOpen) {
      setIsPreviewOpen(true);
    }
  };

  const handleBackToPreviewFiles = useCallback(() => {
    setPreviewPanelContent(FILES_PANEL_CONTENT);
  }, []);

  const handleOpenToolInPreview = useCallback((step: ProcessStep) => {
    setIsPreviewOpen(true);
    setPreviewPanelContent(resolvePreviewPanelContentForStep(step));
  }, []);

  useEffect(() => {
    setPreviewPanelContent(FILES_PANEL_CONTENT);
  }, [activeChatId]);

  const executeChatRequest = async (
    prompt: string,
    historyToUse: Message[],
    targetMessageId?: string,
    attachments?: Attachment[],
    chatId?: string,
  ) => {
    // Create abort controller for this request
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    // Use provided chatId or fall back to activeChatId
    let activeSessionId = chatId || activeChatId;

    if (!targetMessageId) {
      setIsLoading(true);
    }

    isStreamingRef.current = true;
    setIsStreaming(true);

    let assistantMsgId = targetMessageId || generateUUID();
    let messageInitialized = !!targetMessageId;
    let accumulatedContent = "";

    if (targetMessageId) {
      const existingMsg = historyToUse.find((m) => m.id === targetMessageId);
      if (existingMsg) {
        accumulatedContent = existingMsg.content;
      }
    }

    const sessionModelProvider = modelProviderForHermes(modelConfig);
    const chatProfile = activeProfile || "default";
    const sessionCreateOptions = {
      model: modelConfig.modelId,
      workspace: composerWorkspace || undefined,
      profile: chatProfile,
      ...(sessionModelProvider ? { modelProvider: sessionModelProvider } : {}),
    };

    const migrateSessionId = (fromId: string, toId: string) => {
      if (fromId === toId) return;
      setActiveChatIdSynced(toId);
      navigate(`/chat/${toId}`);
      setSessions((prev) => {
        const existing = prev[fromId];
        if (!existing) return prev;
        const next = { ...prev };
        delete next[fromId];
        next[toId] = { ...existing, id: toId };
        return next;
      });
    };

    const consumeStream = async () => {
      await consumeHermesStream({
        activeSessionId,
        assistantMsgId,
        targetMessageId,
        initialAccumulatedContent: accumulatedContent,
        stream: streamHermesChat({
          sessionId: activeSessionId,
          message: prompt,
          modelConfig,
          workspace: composerWorkspace || undefined,
          profile: chatProfile,
          attachments,
          signal: abortController.signal,
          onChatStart: (start) => {
            applyEffectiveModelFromChatStart(start);
            const streamId =
              typeof start.stream_id === "string" ? start.stream_id.trim() : "";
            if (!streamId) return;
            setSessions((prev) => {
              const session = prev[activeSessionId];
              if (!session) return prev;
              return {
                ...prev,
                [activeSessionId]: {
                  ...session,
                  activeStreamId: streamId,
                  isStreaming: true,
                },
              };
            });
          },
          onSessionTitle: (sessionId, title) => {
            setSessions((prev) => {
              const session = prev[sessionId];
              if (!session) return prev;
              return {
                ...prev,
                [sessionId]: { ...session, title },
              };
            });
          },
          onContextUsage: (usage) =>
            applySessionContextUsage(activeSessionId, usage),
        }),
        setSessions,
        setIsLoading,
        isStreamingRef,
        setIsStreaming,
        abortControllerRef,
        autoExpandSidebarOnTool,
        isPreviewOpen,
        isSettingsOpen,
        setIsPreviewOpen,
        setPreviewPanelContent,
        clearSessionStreamFlags,
      });
      await syncSessionMessagesAfterStream(activeSessionId);
    };

    try {
      if (!modelConfig.modelId) {
        throw new Error(
          "No model selected. Please select a model before sending a message.",
        );
      }

      const boundWs = await bindComposerWorkspaceToSession(activeSessionId);
      if (boundWs) {
        setComposerWorkspace(boundWs);
        setActiveSessionWorkspace(boundWs);
        composerHydratedForChatRef.current = activeSessionId;
      }

      try {
        await consumeStream();
      } catch (firstError) {
        if (!isSessionNotFoundError(firstError)) {
          throw firstError;
        }
        void refreshSessions();
        const previousId = activeSessionId;
        activeSessionId = await ensureServerSessionId(
          undefined,
          serverSessionIdsRef.current,
          sessionCreateOptions,
        );
        migrateSessionId(previousId, activeSessionId);
        messageInitialized = !!targetMessageId;
        assistantMsgId = targetMessageId || generateUUID();
        accumulatedContent = targetMessageId
          ? (historyToUse.find((m) => m.id === targetMessageId)?.content ?? "")
          : "";
        isStreamingRef.current = true;
        setIsStreaming(true);
        if (!targetMessageId) {
          setIsLoading(true);
        }
        await consumeStream();
      }
    } catch (error: unknown) {
      console.error("Error in chat loop:", error);

      const isAbortError =
        error instanceof DOMException && error.name === "AbortError";

      if (isAbortError) {
        console.log("Streaming was aborted by user");
        return;
      }

      const errorMsg =
        error instanceof Error ? error.message : JSON.stringify(error);
      if (
        errorMsg.includes("AbortError") ||
        errorMsg.includes("The user aborted a request")
      ) {
        console.log("Streaming was aborted by user");
        return;
      }

      const presentation = formatChatError(error);
      setErrorModalConfig(presentation);
      setShowErrorModal(true);

      // Remove the assistant message if it was initialized but failed
      if (messageInitialized) {
        setSessions((prev) => {
          const session = prev[activeSessionId];
          if (!session) return prev;

          return {
            ...prev,
            [activeSessionId]: {
              ...session,
              messages: session.messages.filter(
                (msg) => msg.id !== assistantMsgId,
              ),
            },
          };
        });
      }
    } finally {
      setIsLoading(false);
      isStreamingRef.current = false;
      setIsStreaming(false);
      abortControllerRef.current = null;
      if (activeSessionId) {
        clearSessionStreamFlags(activeSessionId);
      }
    }
  };

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    const sessionId = activeChatIdRef.current;
    if (sessionId) {
      setSessions((prev) => {
        const session = prev[sessionId];
        if (!session?.messages.length) return prev;
        const messages = [...session.messages];
        for (let i = messages.length - 1; i >= 0; i -= 1) {
          if (messages[i].role !== "assistant") continue;
          messages[i] = finalizeRunningStepsInMessage(messages[i]);
          break;
        }
        return { ...prev, [sessionId]: { ...session, messages } };
      });
    }
    setIsLoading(false);
    isStreamingRef.current = false;
    setIsStreaming(false);
    if (sessionId) {
      clearSessionStreamFlags(sessionId);
    }
  }, [clearSessionStreamFlags]);

  const handleCancelSession = useCallback(
    async (sessionId: string) => {
      const isActivePane =
        activeChatIdRef.current === sessionId &&
        (isStreamingRef.current || isLoading);
      if (isActivePane && abortControllerRef.current) {
        handleStop();
        clearSessionStreamFlags(sessionId);
        void refreshSessions();
        return;
      }

      const streamId =
        sessions[sessionId]?.activeStreamId?.trim() ||
        "";
      if (!streamId) return;

      try {
        await cancelChatStream(streamId);
      } catch {
        /* best-effort; server may already have finished */
      }
      clearSessionStreamFlags(sessionId);
      void refreshSessions();
    },
    [clearSessionStreamFlags, handleStop, refreshSessions, sessions],
  );

  const handleClarifyAnswered = useCallback(
    (payload: { question: string; answer: string; displayContent: string }) => {
      const sid = activeChatId;
      const content = payload.displayContent.trim();
      if (!sid || !content) return;
      setSessions((prev) => {
        const session = prev[sid];
        if (!session) return prev;
        return {
          ...prev,
          [sid]: reduceClarifyEchoToSession(session, content),
        };
      });
    },
    [activeChatId],
  );

  const handleSend = async (
    message: string,
    attachments: Attachment[] = [],
    preferredSessionId?: string,
  ) => {
    if ((isLoading || isStreaming) && !abortControllerRef.current) {
      isStreamingRef.current = false;
      setIsStreaming(false);
      setIsLoading(false);
    }

    if (
      (!message.trim() && attachments.length === 0) ||
      isLoading ||
      isStreaming
    )
      return;

    console.log('>>> handleSend: called with message:', message);

    if (preferredSessionId) {
      setActiveChatIdSynced(preferredSessionId);
    }

    // Check if model is selected before sending
    if (!modelConfig.modelId) {
      setErrorModalConfig({
        title: "กรุณาเลือก Model",
        message: "คุณยังไม่ได้เลือก model กรุณาเลือก model ก่อนส่งข้อความ",
        type: "warning",
      });
      setShowErrorModal(true);
      return;
    }

    const currentPrompt = message;
    const isAtChatRoot = location.pathname === "/chat" || location.pathname === "/";

    // Use Ref to get the LATEST active chat ID
    const currentActiveId = preferredSessionId || activeChatIdRef.current;

    // Check if we really need a new chat
    // 1. If we are at root (/chat)
    // 2. If NO active ID exists
    // 3. If the active session doesn't exist in our state
    // 4. If the active session exists but has NO messages (empty new chat)
    const isNewChat = isAtChatRoot || !currentActiveId || !sessions[currentActiveId] || (sessions[currentActiveId]?.messages.length === 0);

    // Create new chat ID if this is a new chat
    let chatId = currentActiveId;
    const sessionModelProvider = modelProviderForHermes(modelConfig);
    const chatProfile = activeProfile || "default";
    const sessionCreateOptions = {
      model: modelConfig.modelId,
      workspace: composerWorkspace || undefined,
      profile: chatProfile,
      ...(sessionModelProvider ? { modelProvider: sessionModelProvider } : {}),
    };

    if (isNewChat) {
      try {
        const previousId = chatId;
        chatId = await ensureServerSessionId(
          chatId,
          serverSessionIdsRef.current,
          sessionCreateOptions,
        );
        confirmSessionId(chatId);
        const boundWs = await bindComposerWorkspaceToSession(chatId);
        if (boundWs) {
          setComposerWorkspace(boundWs);
          setActiveSessionWorkspace(boundWs);
        }
        composerHydratedForChatRef.current = chatId;
        if (previousId && previousId !== chatId) {
          setSessions((prev) => {
            const placeholder = prev[previousId];
            if (!placeholder) return prev;
            const next = { ...prev };
            delete next[previousId];
            next[chatId] = { ...placeholder, id: chatId };
            return next;
          });
        }
        setActiveChatIdSynced(chatId);
      } catch (err) {
        console.error("Failed to create Hermes session:", err);
        setErrorModalConfig({
          title: "การสร้างแชทล้มเหลว",
          message: err instanceof Error ? err.message : "ไม่สามารถสร้าง session ได้",
          type: "error",
        });
        setShowErrorModal(true);
        return;
      }

      const userMsg: Message = {
        id: generateUUID(),
        role: "user",
        content: currentPrompt,
        attachments: attachments.map((att) => ({ ...att })),
        timestamp: Date.now(),
        versions: [
          {
            content: currentPrompt,
            attachments: attachments.map((att) => ({ ...att })),
            timestamp: Date.now(),
          },
        ],
        currentVersionIndex: 0,
      };

      // Create new session AND add message atomically
      setSessions((prev) => ({
        ...prev,
        [chatId]: {
          id: chatId,
          title: currentPrompt.substring(0, 30),
          messages: [userMsg],
          updatedAt: Date.now(),
          ...(modelConfig.modelId ? { flowId: modelConfig.modelId, flowName: modelConfig.name } : {}),
        },
      }));

      // Navigate to new chat URL with ID
      console.log('>>> handleSend: Navigating to new chat:', chatId);
      // DEBUG: Alert before navigation


      setActiveChatIdSynced(chatId);
      preferBlankChatRef.current = false;
      navigate(`/chat/${chatId}`);

      // Fallback: Force navigation again after a short delay if URL hasn't changed
      setTimeout(() => {
        if (!window.location.pathname.includes(chatId)) {
          console.warn('>>> handleSend: Navigation fallback triggered for:', chatId);
          navigate(`/chat/${chatId}`);
        }
      }, 100);

      setInputValue("");
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          chatInputRef.current?.focus();
        });
      });

      const localTitle = currentPrompt.trim().substring(0, 30) || "Untitled";
      setSessions((prev) => {
        if (!prev[chatId]) return prev;
        return {
          ...prev,
          [chatId]: { ...prev[chatId], title: localTitle },
        };
      });
      void renameSessionOnFirstMessage(chatId, currentPrompt)
        .then((res) => {
          const serverTitle = res.session?.title;
          if (!serverTitle) return;
          setSessions((prev) => {
            if (!prev[chatId]) return prev;
            return {
              ...prev,
              [chatId]: { ...prev[chatId], title: serverTitle },
            };
          });
        })
        .catch(() => undefined);

      // Execute Request (history is empty for new chat)
      try {
        // Execute Request (history is empty for new chat)
        await executeChatRequest(
          currentPrompt,
          [],
          undefined,
          attachments,
          chatId,
        );
      } catch (e: any) {
        console.error("Chat execution failed:", e);
        let errorMessage = `เกิดข้อผิดพลาด: ${e.message}`;
        if (e.message && e.message.includes("Failed to fetch")) {
          errorMessage = "ไม่สามารถเชื่อมต่อกับ Server ได้ (CORS หรือ Network Error) กรุณาตรวจสอบการเชื่อมต่อหรือตั้งค่า Proxy";
        }
        setErrorModalConfig({
          title: "การส่งข้อความล้มเหลว",
          message: errorMessage,
          type: "error",
        });
        setShowErrorModal(true);
      }

      return; // Exit here for new chat flow
    }

    // Existing Chat Flow
    const userMsg: Message = {
      id: generateUUID(),
      role: "user",
      content: currentPrompt,
      attachments: attachments.map((att) => ({ ...att })),
      timestamp: Date.now(),
      versions: [
        {
          content: currentPrompt,
          attachments: attachments.map((att) => ({ ...att })),
          timestamp: Date.now(),
        },
      ],
      currentVersionIndex: 0,
    };

    setInputValue("");
    // Focus back to textarea after clearing input
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        chatInputRef.current?.focus();
      });
    });
    const historyBeforeNewMessage = [...currentMessages];

    setSessions((prev) => {
      const currentSession = prev[chatId];
      if (!currentSession) {
        console.error("Session not found in setSessions:", chatId);
        return prev;
      }

      return {
        ...prev,
        [chatId]: {
          ...currentSession,
          messages: [...currentSession.messages, userMsg],
          updatedAt: Date.now(),
        },
      };
    });

    if (currentMessages.length === 0) {
      const localTitle = currentPrompt.trim().substring(0, 30) || "Untitled";
      setSessions((prev) => {
        if (!prev[chatId]) return prev;
        return {
          ...prev,
          [chatId]: { ...prev[chatId], title: localTitle },
        };
      });
      void renameSessionOnFirstMessage(chatId, currentPrompt)
        .then((res) => {
          const serverTitle = res.session?.title;
          if (!serverTitle) return;
          setSessions((prev) => {
            if (!prev[chatId]) return prev;
            return {
              ...prev,
              [chatId]: { ...prev[chatId], title: serverTitle },
            };
          });
        })
        .catch(() => undefined);
    }

    try {
      await executeChatRequest(
        currentPrompt,
        historyBeforeNewMessage,
        undefined,
        attachments,
        chatId,
      );
    } catch (e: any) {
      console.error("Chat execution failed:", e);
      let errorMessage = `เกิดข้อผิดพลาด: ${e.message}`;
      if (e.message && e.message.includes("Failed to fetch")) {
        errorMessage = "ไม่สามารถเชื่อมต่อกับ Server ได้ (CORS หรือ Network Error) กรุณาตรวจสอบการเชื่อมต่อหรือตั้งค่า Proxy";
      }
      setErrorModalConfig({
        title: "การส่งข้อความล้มเหลว",
        message: errorMessage,
        type: "error",
      });
      setShowErrorModal(true);
    }
  };

  const handleEditUserMessage = async (
    messageId: string,
    newContent: string,
  ) => {
    if (isLoading || isStreaming) return;

    // Snapshot state for calculation
    const currentSession = sessions[activeChatId];
    if (!currentSession) return;
    const currentMessagesRaw = currentSession.messages;
    const msgIndex = currentMessagesRaw.findIndex((m) => m.id === messageId);
    if (msgIndex === -1) return;

    const originalMsg = currentMessagesRaw[msgIndex];
    const finalAttachments = originalMsg.attachments;

    // Robustly find the next assistant message and its index
    const assistantIndex = currentMessagesRaw.slice(msgIndex + 1).findIndex(m => m.role === "assistant");
    const assistantMsg = assistantIndex !== -1 ? currentMessagesRaw[msgIndex + 1 + assistantIndex] : null;
    const actualAssistantIndex = assistantIndex !== -1 ? msgIndex + 1 + assistantIndex : -1;

    const targetAssistantId = assistantMsg?.id;
    const historyToUse = currentMessagesRaw.slice(0, msgIndex);

    console.log('>>> handleEditUserMessage calculated:', { msgIndex, actualAssistantIndex, targetAssistantId });

    setSessions((prev) => {
      const session = prev[activeChatId];
      if (!session) return prev;

      const updatedMessages = session.messages.map((msg) => {
        // Handle User Message update
        if (msg.id === messageId) {
          const currentVersions = [...(msg.versions || [
            {
              content: msg.content,
              attachments: msg.attachments,
              timestamp: msg.timestamp,
            },
          ])];

          const tailStartIndex = assistantMsg ? actualAssistantIndex + 1 : msgIndex + 1;
          const currentTail = session.messages.slice(tailStartIndex);

          const currentIndex = msg.currentVersionIndex ?? 0;
          if (currentVersions[currentIndex]) {
            currentVersions[currentIndex] = {
              ...currentVersions[currentIndex],
              tail: currentTail
            };
          }

          const newVersion: MessageVersion = {
            content: newContent,
            attachments: msg.attachments,
            timestamp: Date.now(),
          };

          return {
            ...msg,
            content: newContent,
            versions: [...currentVersions, newVersion],
            currentVersionIndex: currentVersions.length,
          };
        }

        // Handle Assistant Message update (linked version)
        if (assistantMsg && msg.id === assistantMsg.id) {
          const currentVersions = [...(msg.versions || [
            {
              content: msg.content,
              steps: msg.steps,
              timestamp: msg.timestamp,
            },
          ])];

          const currentTail = session.messages.slice(actualAssistantIndex + 1);
          const currentIndex = msg.currentVersionIndex ?? 0;
          if (currentVersions[currentIndex]) {
            currentVersions[currentIndex] = {
              ...currentVersions[currentIndex],
              tail: currentTail
            };
          }

          const newVersion: MessageVersion = {
            content: "",
            timestamp: Date.now(),
          };

          return {
            ...msg,
            content: "",
            steps: undefined,
            versions: [...currentVersions, newVersion],
            currentVersionIndex: currentVersions.length,
          };
        }

        return msg;
      });

      const truncatedSize = assistantMsg ? actualAssistantIndex + 1 : msgIndex + 1;
      const finalMessages = updatedMessages.slice(0, truncatedSize);

      return {
        ...prev,
        [activeChatId]: {
          ...session,
          messages: finalMessages,
        },
      };
    });

    await executeChatRequest(
      newContent,
      historyToUse,
      targetAssistantId,
      finalAttachments,
    );
  };

  const handleRegenerate = async (messageId: string) => {
    if (isLoading || isStreaming) return;

    const currentSession = sessions[activeChatId];
    if (!currentSession) return;
    const currentMessagesRaw = currentSession.messages;
    const msgIndex = currentMessagesRaw.findIndex((m) => m.id === messageId);
    if (msgIndex === -1) return;

    const historyToUse = currentMessagesRaw.slice(0, msgIndex);
    const lastUserMsg = [...historyToUse]
      .reverse()
      .find((m) => m.role === "user");

    if (!lastUserMsg) return;

    const targetPrompt = lastUserMsg.content;
    const targetAttachments = lastUserMsg.attachments;

    setSessions((prev) => {
      const session = prev[activeChatId];
      if (!session) return prev;

      const updatedMessages = session.messages.map((msg) => {
        if (msg.id === messageId) {
          const currentVersionIndex = msg.currentVersionIndex || 0;
          const currentVersions = msg.versions || [];

          // Get current message version
          const currentMessageVersion = currentVersions[currentVersionIndex] || {
            content: msg.content,
            steps: msg.steps,
            attachments: msg.attachments,
            suggestions: msg.suggestions,
            timestamp: msg.timestamp,
          };

          const currentAIIndex = currentMessageVersion.currentAIIndex || 0;
          const currentAIVersions = currentMessageVersion.aiVersions || [];

          // If no aiVersions exist, create the first one with current content
          if (currentAIVersions.length === 0) {
            const firstRegenVersion = {
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
              suggestions: msg.suggestions,
              timestamp: msg.timestamp,
            };

            // Create new empty regen version for streaming
            const newRegenVersion = {
              content: "",
              timestamp: Date.now(),
            };

            const firstAIVersion = {
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
              suggestions: msg.suggestions,
              timestamp: msg.timestamp,
              regenVersions: [firstRegenVersion, newRegenVersion],
              currentRegenIndex: 1, // Point to the new empty version
            };

            const updatedMessageVersion = {
              ...currentMessageVersion,
              aiVersions: [firstAIVersion],
              currentAIIndex: 0,
            };

            const updatedVersions = [...currentVersions];
            if (updatedVersions[currentVersionIndex]) {
              updatedVersions[currentVersionIndex] = updatedMessageVersion;
            } else {
              updatedVersions.push(updatedMessageVersion);
            }

            return {
              ...msg,
              content: "",
              steps: undefined,
              versions: updatedVersions,
              needsSuggestions: true,
            };
          }

          // Save current content to current AI version
          const updatedAIVersions = [...currentAIVersions];
          if (updatedAIVersions[currentAIIndex]) {
            updatedAIVersions[currentAIIndex] = {
              ...updatedAIVersions[currentAIIndex],
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
              suggestions: msg.suggestions,
            };
          }

          // Add new regen version to current AI version
          const currentAIVersion = updatedAIVersions[currentAIIndex];
          const currentRegenVersions = currentAIVersion.regenVersions || [];
          const currentRegenIndex = currentAIVersion.currentRegenIndex || 0;

          // Save current content to current regen version before creating new one
          const updatedRegenVersions = [...currentRegenVersions];

          // If regenVersions is empty, save current content as first regen version
          if (updatedRegenVersions.length === 0) {
            const firstRegenVersion = {
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
              suggestions: msg.suggestions,
              timestamp: msg.timestamp,
            };
            updatedRegenVersions.push(firstRegenVersion);
          } else if (updatedRegenVersions[currentRegenIndex]) {
            updatedRegenVersions[currentRegenIndex] = {
              ...updatedRegenVersions[currentRegenIndex],
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
              suggestions: msg.suggestions,
            };
          }

          // Create new regen version
          const newRegenVersion = {
            content: "",
            timestamp: Date.now(),
          };

          updatedAIVersions[currentAIIndex] = {
            ...currentAIVersion,
            regenVersions: [...updatedRegenVersions, newRegenVersion],
            currentRegenIndex: updatedRegenVersions.length,
          };

          const updatedMessageVersion = {
            ...currentMessageVersion,
            aiVersions: updatedAIVersions,
          };

          const updatedVersions = [...currentVersions];
          updatedVersions[currentVersionIndex] = updatedMessageVersion;

          return {
            ...msg,
            content: "",
            steps: undefined,
            versions: updatedVersions,
            needsSuggestions: true,
          };
        }
        return msg;
      });

      const finalMessages = updatedMessages.slice(0, msgIndex + 1);

      return {
        ...prev,
        [activeChatId]: {
          ...session,
          messages: finalMessages,
        },
      };
    });

    await executeChatRequest(
      targetPrompt,
      historyToUse,
      messageId,
      targetAttachments,
    );
  };

  const handleVersionChange = (messageId: string, newIndex: number) => {
    setSessions((prev) => {
      const session = prev[activeChatId];
      if (!session) return prev;

      const currentMessages = session.messages;
      const msgIndex = currentMessages.findIndex((m) => m.id === messageId);
      if (msgIndex === -1) return prev;

      const targetMsg = currentMessages[msgIndex];
      if (!targetMsg.versions || !targetMsg.versions[newIndex]) return prev;

      const updates = new Map<string, number>();
      updates.set(messageId, newIndex);

      let linkedMsg: Message | undefined;
      let linkedIndex = -1;

      if (targetMsg.role === "user") {
        const foundAssistantIndex = currentMessages.slice(msgIndex + 1).findIndex(m => m.role === "assistant");
        if (foundAssistantIndex !== -1) {
          linkedIndex = msgIndex + 1 + foundAssistantIndex;
          linkedMsg = currentMessages[linkedIndex];
          updates.set(linkedMsg.id, newIndex);
        }
      } else if (targetMsg.role === "assistant") {
        const foundUserIndex = [...currentMessages.slice(0, msgIndex)].reverse().findIndex(m => m.role === "user");
        if (foundUserIndex !== -1) {
          linkedIndex = msgIndex - 1 - foundUserIndex;
          linkedMsg = currentMessages[linkedIndex];
          updates.set(linkedMsg.id, newIndex);
        }
      }

      // Identify point of divergence
      const calculatedTailStartIndex = (targetMsg.role === "user" && linkedMsg) ? linkedIndex + 1 : msgIndex + 1;
      const currentTail = currentMessages.slice(calculatedTailStartIndex);

      // 1. Calculate new tail from TARGET or LINKED version
      let newTail: Message[] = [];
      const linkedVersion = (linkedMsg && linkedMsg.versions) ? linkedMsg.versions[newIndex] : null;
      const targetVersion = targetMsg.versions[newIndex];

      if (linkedVersion?.tail) {
        newTail = linkedVersion.tail;
      } else if (targetVersion?.tail) {
        newTail = targetVersion.tail;
      }

      // 2. Construct new message list with IMMUTABLE updates
      const baseMessages = currentMessages.slice(0, calculatedTailStartIndex).map((msg) => {
        // Clone message if it's the target or linked one
        if (updates.has(msg.id)) {
          const idxToUse = updates.get(msg.id)!;
          const currentIdx = msg.currentVersionIndex ?? 0;
          const updatedVersions = msg.versions ? [...msg.versions] : [];

          // Save CURRENT tail to CURRENT version slot before switching
          if (updatedVersions[currentIdx]) {
            updatedVersions[currentIdx] = {
              ...updatedVersions[currentIdx],
              tail: currentTail
            };
          }

          const targetV = updatedVersions[idxToUse];
          return {
            ...msg,
            content: targetV.content,
            steps: targetV.steps,
            attachments: targetV.attachments || msg.attachments,
            currentVersionIndex: idxToUse,
            versions: updatedVersions,
          };
        }
        return msg;
      });

      return {
        ...prev,
        [activeChatId]: {
          ...session,
          messages: [...baseMessages, ...newTail],
          updatedAt: Date.now(),
        },
      };
    });
  };

  // Handle AI version change (for assistant messages)
  const handleAIVersionChange = (messageId: string, newIndex: number) => {
    setSessions((prev) => {
      const session = prev[activeChatId];
      if (!session) return prev;

      const currentMessages = session.messages;
      const msgIndex = currentMessages.findIndex((m) => m.id === messageId);
      if (msgIndex === -1) return prev;

      const targetMsg = currentMessages[msgIndex];
      const currentVersionIndex = targetMsg.currentVersionIndex || 0;
      const currentMessageVersion = targetMsg.versions?.[currentVersionIndex];

      if (!currentMessageVersion?.aiVersions || !currentMessageVersion.aiVersions[newIndex]) return prev;

      const updatedMessages = currentMessages.map((msg) => {
        if (msg.id === messageId) {
          const currentAIIndex = currentMessageVersion.currentAIIndex || 0;
          const updatedAIVersions = [...(currentMessageVersion.aiVersions || [])];

          // Save current content to current AI version before switching
          if (updatedAIVersions[currentAIIndex]) {
            updatedAIVersions[currentAIIndex] = {
              ...updatedAIVersions[currentAIIndex],
              content: msg.content,
              steps: msg.steps,
              attachments: msg.attachments,
            };
          }

          const targetAIVersion = updatedAIVersions[newIndex];
          const updatedMessageVersion = {
            ...currentMessageVersion,
            aiVersions: updatedAIVersions,
            currentAIIndex: newIndex,
          };

          const updatedVersions = [...(msg.versions || [])];
          updatedVersions[currentVersionIndex] = updatedMessageVersion;

          return {
            ...msg,
            content: targetAIVersion.content,
            steps: targetAIVersion.steps,
            attachments: targetAIVersion.attachments || msg.attachments,
            suggestions: targetAIVersion.suggestions,
            versions: updatedVersions,
          };
        }
        return msg;
      });

      return {
        ...prev,
        [activeChatId]: {
          ...session,
          messages: updatedMessages,
          updatedAt: Date.now(),
        },
      };
    });
  };

  // Handle regen version change (for AI versions)
  const handleRegenVersionChange = (messageId: string, aiIndex: number, regenIndex: number) => {
    setSessions((prev) => {
      const session = prev[activeChatId];
      if (!session) return prev;

      const currentMessages = session.messages;
      const msgIndex = currentMessages.findIndex((m) => m.id === messageId);
      if (msgIndex === -1) return prev;

      const targetMsg = currentMessages[msgIndex];
      const currentVersionIndex = targetMsg.currentVersionIndex || 0;
      const currentMessageVersion = targetMsg.versions?.[currentVersionIndex];

      if (!currentMessageVersion?.aiVersions || !currentMessageVersion.aiVersions[aiIndex]) return prev;

      const targetAIVersion = currentMessageVersion.aiVersions[aiIndex];
      if (!targetAIVersion.regenVersions || !targetAIVersion.regenVersions[regenIndex]) return prev;

      const updatedMessages = currentMessages.map((msg) => {
        if (msg.id === messageId) {
          const currentAIIndex = currentMessageVersion.currentAIIndex || 0;
          const currentAIVersion = currentMessageVersion.aiVersions?.[currentAIIndex];
          const currentRegenIndex = currentAIVersion?.currentRegenIndex || 0;

          const updatedAIVersions = [...(currentMessageVersion.aiVersions || [])];

          // Save current content to current regen version before switching
          if (updatedAIVersions[aiIndex] && updatedAIVersions[aiIndex].regenVersions) {
            const updatedRegenVersions = [...updatedAIVersions[aiIndex].regenVersions!];
            if (updatedRegenVersions[currentRegenIndex]) {
              updatedRegenVersions[currentRegenIndex] = {
                ...updatedRegenVersions[currentRegenIndex],
                content: msg.content,
                steps: msg.steps,
                attachments: msg.attachments,
              };
            }
            updatedAIVersions[aiIndex] = {
              ...updatedAIVersions[aiIndex],
              regenVersions: updatedRegenVersions,
            };
          }

          const targetRegenVersion = updatedAIVersions[aiIndex].regenVersions![regenIndex];

          // Update currentRegenIndex in the target AI version
          updatedAIVersions[aiIndex] = {
            ...updatedAIVersions[aiIndex],
            currentRegenIndex: regenIndex,
          };

          const updatedMessageVersion = {
            ...currentMessageVersion,
            aiVersions: updatedAIVersions,
            currentAIIndex: aiIndex, // Update currentAIIndex to the AI version being switched to
          };

          const updatedVersions = [...(msg.versions || [])];
          updatedVersions[currentVersionIndex] = updatedMessageVersion;

          return {
            ...msg,
            content: targetRegenVersion.content,
            steps: targetRegenVersion.steps,
            attachments: targetRegenVersion.attachments || msg.attachments,
            suggestions: targetRegenVersion.suggestions,
            versions: updatedVersions,
          };
        }
        return msg;
      });

      return {
        ...prev,
        [activeChatId]: {
          ...session,
          messages: updatedMessages,
          updatedAt: Date.now(),
        },
      };
    });
  };

  const handleNewChat = () => {
    preferBlankChatRef.current = true;
    setActiveChatIdSynced("");
    navigate("/chat");

    setIsSettingsOpen(false);
    if (isMobile) {
      setIsSidebarOpen(false);
    }
  };

  const confirmDeleteChat = async () => {

    if (!chatToDelete) return;
    const id = chatToDelete;

    setChatToDelete(null);

    try {
      await deleteSession(id);
    } catch (err) {
      toast.error(toastMessage(err));
      return;
    }

    setSessions((prev) => {
      const newSessions = { ...prev };
      delete newSessions[id];

      return newSessions;
    });

    // If deleted the active chat, navigate to /chat or another chat
    if (activeChatId === id) {
      const remainingSessions = Object.values(sessions).filter(
        (s) => s.id !== id && !s.id.startsWith("suggestion-"),
      ) as ChatSession[];

      if (remainingSessions.length === 0) {
        // No chats left, go to /chat
        navigate("/chat");
      } else {
        // Navigate to the most recent chat
        const latest = remainingSessions.sort(
          (a, b) => b.updatedAt - a.updatedAt,
        )[0];
        if (latest) {
          navigate(`/chat/${latest.id}`);
        } else {
          navigate("/chat");
        }
      }
    }
  };

  const onRequestDeleteChat = (id: string) => {
    setChatToDelete(id);
  };

  const handleClearAllChats = async (): Promise<boolean> => {
    try {
      const { deleted, failed } = await deleteAllSessions();
      if (failed > 0) {
        toast.error(t("settings.clearHistoryFailed"));
        await refreshSessions();
        return false;
      }

      resetSessions();
      syncConfirmedSessionIds(new Set());
      setActiveChatIdSynced("");
      navigate("/chat");

      if (deleted > 0) {
        toast.success(t("settings.clearHistorySuccess"));
      }
      return true;
    } catch (err) {
      toast.error(toastMessage(err));
      return false;
    }
  };

  const handleSelectChat = (id: string) => {
    preferBlankChatRef.current = false;
    navigate(`/chat/${id}`);
    setIsSettingsOpen(false);
    setLoadingChatId(id);
    if (isMobile) {
      setIsSidebarOpen(false);
    }
  };

  // If not authenticated, show Auth Page
  // Sync route params to settings state
  useEffect(() => {
    if (location.pathname.startsWith("/settings/")) {
      const tab = location.pathname.split("/")[2] as SettingsTab;
      const allowed: SettingsTab[] = [
        "general",
        "account",
        "users",
        "roles",
        "departments",
        "profiles",
        "workspaces",
        "providers",
        "plugins",
        "mcp",
      ];
      if (allowed.includes(tab)) {
        setSettingsTab(tab);
        setIsSettingsOpen(true);
      } else {
        navigate("/settings/general", { replace: true });
      }
    } else {
      setIsSettingsOpen(false);
    }
  }, [location.pathname, navigate]);

  if (!authBootReady) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 dark:bg-black">
        <div
          className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-600 dark:border-zinc-600 dark:border-t-zinc-300"
          role="status"
          aria-label="Loading"
        />
      </div>
    );
  }

  /** Let users re-select the current workspace to push composer → server session bind. */
  const workspaceNeedsBind = Boolean(activeChatId && composerWorkspace.trim());

  const workspaceBindPending = Boolean(
    activeChatId &&
      activeSessionConfirmed &&
      composerWorkspace.trim() &&
      (!activeSessionWorkspace.trim() ||
        composerNeedsServerWorkspaceBind(
          composerWorkspace,
          activeSessionWorkspace,
        )),
  );

  const renderAuthenticatedShell = (panel: ShellPanelId) =>
    isAuthenticated ? (
      <AppLayout
        shellPanel={panel === "chat" ? undefined : panel}
        showSettings={panel === "settings"}
        isMobile={isMobile}
        isPreviewOverlay={isPreviewOverlay}
        isSidebarOpen={isSidebarOpen}
        setIsSidebarOpen={setIsSidebarOpen}
        history={history}
        activeChatId={activeChatId}
        handleNewChat={handleNewChat}
        handleSelectChat={handleSelectChat}
        onRequestDeleteChat={onRequestDeleteChat}
        onPinSession={handlePinSession}
        modelConfig={modelConfig}
        handleProviderChange={handleProviderChange}
        navigate={navigate}
        onAuthRefresh={() => void refreshAuth()}
        settingsTab={settingsTab}
        setModelConfig={setModelConfig}
        chatHistory={history}
        handleClearAllChats={handleClearAllChats}
        currentMessages={panel === "chat" ? currentMessages : []}
        contextUsage={panel === "chat" ? currentContextUsage : undefined}
        compressionAnchor={panel === "chat" ? currentCompressionAnchor : undefined}
        inputValue={inputValue}
        setInputValue={setInputValue}
        handleSend={handleSend}
        handleStop={handleStop}
        handleRegenerate={handleRegenerate}
        handleEditUserMessage={handleEditUserMessage}
        isLoading={isLoading}
        isStreaming={isStreaming}
        loadingChatId={loadingChatId}
        onCancelSession={handleCancelSession}
        handleVersionChange={handleVersionChange}
        handleAIVersionChange={handleAIVersionChange}
        handleRegenVersionChange={handleRegenVersionChange}
        isPreviewOpen={isPreviewOpen}
        handlePreviewRequest={handlePreviewRequest}
        setIsPreviewOpen={setIsPreviewOpen}
        previewPanelContent={previewPanelContent}
        onBackToPreviewFiles={handleBackToPreviewFiles}
        onOpenToolInPreview={handleOpenToolInPreview}
        chatToDelete={chatToDelete}
        setChatToDelete={setChatToDelete}
        t={t}
        confirmDeleteChat={confirmDeleteChat}
        chatInputRef={chatInputRef}
        agentModels={agentModels}
        pinnedAgentId={pinnedAgentId}
        onPinAgent={handlePinAgent}
        resolvedAgentName={displayAgentName}
        authStatus={authStatus}
        composerWorkspace={composerWorkspace}
        onComposerWorkspaceChange={handleComposerWorkspaceChange}
        onProfileSwitched={handleProfileSwitched}
        ensureComposerSession={ensureComposerSession}
        sessionReady={
          !activeChatId || confirmedSessionIds.has(activeChatId)
        }
        sessionWorkspace={activeSessionWorkspace}
        workspaceNeedsBind={workspaceNeedsBind}
        workspaceBindPending={workspaceBindPending}
        onClarifyAnswered={handleClarifyAnswered}
      />
    ) : (
      <Navigate to="/login" />
    );

  return (
    <>
      <OfflineBanner enabled={authBootReady} streamingActive={isStreaming} />
      <ShellRouter>
      <Routes>
        <Route
          path="/login"
          element={
            !isAuthenticated ? (
              <AuthPage onLogin={(login) => establishSession(login)} />
            ) : (
              <PostLoginRedirect />
            )
          }
        />
        <Route
          path="/register"
          element={
            !isAuthenticated ? (
              <AuthPage onLogin={(login) => establishSession(login)} />
            ) : (
              <PostLoginRedirect />
            )
          }
        />
        <Route path="/settings/:tab" element={renderAuthenticatedShell("settings")} />
        {ShellPanelRoutes({
          isAuthenticated,
          authStatus,
          activeSessionId: activeChatId,
          renderAppLayout: (panel) => renderAuthenticatedShell(panel),
        })}
        <Route
          path="/chat/:chatId"
          element={
            isAuthenticated ? (
              <AppLayout
                showSettings={false}
                isMobile={isMobile}
                isPreviewOverlay={isPreviewOverlay}
                isSidebarOpen={isSidebarOpen}
                setIsSidebarOpen={setIsSidebarOpen}
                history={history}
                activeChatId={activeChatId}
                handleNewChat={handleNewChat}
                handleSelectChat={handleSelectChat}
                onRequestDeleteChat={onRequestDeleteChat}
                onPinSession={handlePinSession}
                modelConfig={modelConfig}
                handleProviderChange={handleProviderChange}
                navigate={navigate}
                onAuthRefresh={() => void refreshAuth()}
                settingsTab={settingsTab}
                setModelConfig={setModelConfig}
                chatHistory={history}
                handleClearAllChats={handleClearAllChats}
                currentMessages={currentMessages}
                contextUsage={currentContextUsage}
                compressionAnchor={currentCompressionAnchor}
                inputValue={inputValue}
                setInputValue={setInputValue}
                handleSend={handleSend}
                handleStop={handleStop}
                handleRegenerate={handleRegenerate}
                handleEditUserMessage={handleEditUserMessage}
                isLoading={isLoading}
                isStreaming={isStreaming}
                loadingChatId={loadingChatId}
                onCancelSession={handleCancelSession}
                handleVersionChange={handleVersionChange}
                handleAIVersionChange={handleAIVersionChange}
                handleRegenVersionChange={handleRegenVersionChange}
                isPreviewOpen={isPreviewOpen}
                handlePreviewRequest={handlePreviewRequest}
                setIsPreviewOpen={setIsPreviewOpen}
                previewPanelContent={previewPanelContent}
                onBackToPreviewFiles={handleBackToPreviewFiles}
                onOpenToolInPreview={handleOpenToolInPreview}
                chatToDelete={chatToDelete}
                setChatToDelete={setChatToDelete}
                t={t}
                confirmDeleteChat={confirmDeleteChat}
                chatInputRef={chatInputRef}
                agentModels={agentModels}
                pinnedAgentId={pinnedAgentId}
                onPinAgent={handlePinAgent}
                resolvedAgentName={displayAgentName}
                composerWorkspace={composerWorkspace}
                onComposerWorkspaceChange={handleComposerWorkspaceChange}
                onProfileSwitched={handleProfileSwitched}
                ensureComposerSession={ensureComposerSession}
                authStatus={authStatus}
                sessionReady={
                  !activeChatId || confirmedSessionIds.has(activeChatId)
                }
                sessionWorkspace={activeSessionWorkspace}
                workspaceNeedsBind={workspaceNeedsBind}
                workspaceBindPending={workspaceBindPending}
              />
            ) : (
              <Navigate to="/login" />
            )
          }
        />
        <Route
          path="/chat"
          element={
            isAuthenticated ? (
              <AppLayout
                showSettings={false}
                isMobile={isMobile}
                isPreviewOverlay={isPreviewOverlay}
                isSidebarOpen={isSidebarOpen}
                setIsSidebarOpen={setIsSidebarOpen}
                history={history}
                activeChatId={activeChatId}
                handleNewChat={handleNewChat}
                handleSelectChat={handleSelectChat}
                onRequestDeleteChat={onRequestDeleteChat}
                onPinSession={handlePinSession}
                modelConfig={modelConfig}
                handleProviderChange={handleProviderChange}
                navigate={navigate}
                onAuthRefresh={() => void refreshAuth()}
                settingsTab={settingsTab}
                setModelConfig={setModelConfig}
                chatHistory={history}
                handleClearAllChats={handleClearAllChats}
                currentMessages={activeChatId ? sessions[activeChatId]?.messages ?? [] : []}
                contextUsage={
                  activeChatId ? sessions[activeChatId]?.contextUsage : undefined
                }
                compressionAnchor={
                  activeChatId ? sessions[activeChatId]?.compressionAnchor : undefined
                }
                inputValue={inputValue}
                setInputValue={setInputValue}
                handleSend={handleSend}
                handleStop={handleStop}
                handleRegenerate={handleRegenerate}
                handleEditUserMessage={handleEditUserMessage}
                isLoading={isLoading}
                isStreaming={isStreaming}
                loadingChatId={loadingChatId}
                onCancelSession={handleCancelSession}
                handleVersionChange={handleVersionChange}
                handleAIVersionChange={handleAIVersionChange}
                handleRegenVersionChange={handleRegenVersionChange}
                isPreviewOpen={isPreviewOpen}
                handlePreviewRequest={handlePreviewRequest}
                setIsPreviewOpen={setIsPreviewOpen}
                previewPanelContent={previewPanelContent}
                onBackToPreviewFiles={handleBackToPreviewFiles}
                onOpenToolInPreview={handleOpenToolInPreview}
                chatToDelete={chatToDelete}
                setChatToDelete={setChatToDelete}
                t={t}
                confirmDeleteChat={confirmDeleteChat}
                chatInputRef={chatInputRef}
                agentModels={agentModels}
                pinnedAgentId={pinnedAgentId}
                onPinAgent={handlePinAgent}
                resolvedAgentName={displayAgentName}
                composerWorkspace={composerWorkspace}
                onComposerWorkspaceChange={handleComposerWorkspaceChange}
                onProfileSwitched={handleProfileSwitched}
                ensureComposerSession={ensureComposerSession}
                authStatus={authStatus}
                sessionReady={false}
                sessionWorkspace={activeSessionWorkspace}
                workspaceNeedsBind={workspaceNeedsBind}
                workspaceBindPending={workspaceBindPending}
              />
            ) : (
              <Navigate to="/login" />
            )
          }
        />
        <Route
          path="/"
          element={
            isAuthenticated ? (
              <Navigate to="/chat" replace />
            ) : (
              <Navigate to="/login" />
            )
          }
        />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
      </ShellRouter>

      {showOnboarding && (
        <OnboardingOverlay onComplete={dismissOnboarding} />
      )}

      {/* Error Modal - Outside Routes */}
      <ErrorModal
        isOpen={showErrorModal}
        onClose={() => setShowErrorModal(false)}
        title={errorModalConfig.title}
        message={errorModalConfig.message}
        type={errorModalConfig.type}
      />
    </>
  );
}
