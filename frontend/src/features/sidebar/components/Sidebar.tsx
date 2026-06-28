import React, { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Plus,
  Search,
  LayoutGrid,
  History,
  Trash2,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  Languages,
  SquarePen,
  Sun,
  Moon,
  Laptop,
  LogOut,
  Loader2,
  Check,
  ChevronDown,
  Pin,
  Square,
  CalendarClock,
  Sparkles,
  Terminal,
  Brain,
  BarChart3,
  ScrollText,
} from "lucide-react";
import { AIProvider, ChatSession, ModelConfig } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";
import { canAccessInsights, canAccessLogs } from "@/features/insights";
import { logout as hermesLogout } from "@/features/auth/services/authService";
import {
  ProjectsBar,
  useProjects,
} from "@/features/projects";
import { pinSession, searchSessions } from "@/services/hermes/sessions";
import {
  mapSessionSummariesToChatSessions,
  shouldShowChatSessionInSidebar,
} from "@/services/hermes/mappers";
import {
  isSidebarSessionRunning,
  normalizeSessionStreamFlags,
  reconcileSessionStreamMetadata,
} from "@/features/sidebar/utils/sessionRuntime";

interface SidebarProps {
  history: ChatSession[];
  activeChatId: string | null;
  loadingChatId: string | null;
  /** True when the open chat pane has an active stream (composer stop). */
  isActivePaneStreaming?: boolean;
  onCancelSession?: (sessionId: string) => void;
  onNewChat: () => void;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onPinSession?: (id: string, pinned: boolean) => void;
  activeProvider: AIProvider;
  onProviderChange: (provider: AIProvider) => void;
  onOpenSettings: () => void;
  isOpen?: boolean;
  toggleSidebar?: () => void;
  isMobile?: boolean;
  onLogout?: () => void;
  modelConfig?: ModelConfig;
  onModelConfigChange?: (config: ModelConfig) => void;
  mcpServers?: string[];
  /** Resolve flowId to agent name for "which agent" per chat */
  agentModels?: { id: string; name: string; desc: string }[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  history,
  activeChatId,
  loadingChatId: _loadingChatId,
  isActivePaneStreaming = false,
  onCancelSession,
  onNewChat,
  onSelectChat,
  onDeleteChat,
  onPinSession,
  activeProvider: _activeProvider,
  onProviderChange: _onProviderChange,
  onOpenSettings,
  isOpen = true,
  toggleSidebar,
  isMobile = false,
  onLogout,
  modelConfig: _modelConfig,
  onModelConfigChange: _onModelConfigChange,
  mcpServers: _mcpServers = [],
  agentModels = [],
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { status: authStatus } = useAuthRole();
  const { t, language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  const {
    projects,
    loading: projectsLoading,
    activeFilter: projectFilter,
    setActiveFilter: setProjectFilter,
    actionPending: projectActionPending,
    createNewProject,
    renameExistingProject,
    updateProjectColor,
    removeProject,
    matchesProjectFilter,
  } = useProjects();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ChatSession[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [pinningId, setPinningId] = useState<string | null>(null);
  const [isLogoHovered, setIsLogoHovered] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showLanguageDropdown, setShowLanguageDropdown] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const languageDropdownRef = useRef<HTMLDivElement>(null);
  const activeChatRef = useRef<HTMLButtonElement>(null);
  const historyContainerRef = useRef<HTMLDivElement>(null);
  const scrollPositionRef = useRef<number>(0);
  const isSelectingChatRef = useRef<boolean>(false);

  type ShellNavItem = {
    path: string;
    icon: React.ComponentType<{ className?: string }>;
    labelKey: string;
    adminOnly?: boolean;
  };

  const shellNavItems = useMemo((): ShellNavItem[] => {
    const items: ShellNavItem[] = [
      { path: "/tasks", icon: CalendarClock, labelKey: "sidebar.scheduledJobs" },
      { path: "/kanban", icon: LayoutGrid, labelKey: "sidebar.kanban" },
      { path: "/skills", icon: Sparkles, labelKey: "sidebar.skills" },
      { path: "/terminal", icon: Terminal, labelKey: "sidebar.terminal" },
      { path: "/memory", icon: Brain, labelKey: "sidebar.memory" },
    ];
    if (canAccessInsights(authStatus)) {
      items.push({ path: "/insights", icon: BarChart3, labelKey: "sidebar.insights", adminOnly: true });
    }
    if (canAccessLogs(authStatus)) {
      items.push({ path: "/logs", icon: ScrollText, labelKey: "sidebar.logs", adminOnly: true });
    }
    return items;
  }, [authStatus]);

  const handleShellNav = (path: string) => {
    navigate(path);
    if (isMobile) {
      toggleSidebar?.();
    }
  };

  // Save scroll position before re-render
  useEffect(() => {
    const container = historyContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      scrollPositionRef.current = container.scrollTop;
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  // Restore scroll position after history changes (prevents jump to top)
  useEffect(() => {
    if (isSelectingChatRef.current && historyContainerRef.current) {
      historyContainerRef.current.scrollTop = scrollPositionRef.current;
      isSelectingChatRef.current = false;
    }
  }, [history]);

  // Auto-scroll to active chat only when it changes externally (not from user click)
  useEffect(() => {
    if (activeChatId && activeChatRef.current && historyContainerRef.current && !isSelectingChatRef.current) {
      const container = historyContainerRef.current;
      const element = activeChatRef.current;
      
      const containerRect = container.getBoundingClientRect();
      const elementRect = element.getBoundingClientRect();
      
      if (elementRect.top < containerRect.top || elementRect.bottom > containerRect.bottom) {
        element.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }
  }, [activeChatId]);

  // Close menu when sidebar is collapsed so dropdown isn't clipped by narrow width
  useEffect(() => {
    if (!isOpen) {
      setShowUserMenu(false);
      setShowLanguageDropdown(false);
    }
  }, [isOpen]);

  // Click outside handler for user menu
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (showUserMenu && userMenuRef.current && !userMenuRef.current.contains(target)) {
        setShowUserMenu(false);
        setShowLanguageDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showUserMenu]);

  // Sidebar expanded state relies purely on isOpen prop now
  const showExpanded = isOpen;

  const sortSessions = useCallback((sessions: ChatSession[]) => {
    return [...sessions].sort((a, b) => {
      const pinDelta = (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0);
      if (pinDelta !== 0) return pinDelta;
      return b.updatedAt - a.updatedAt;
    });
  }, []);

  // M33 — debounced Hermes GET /sessions/search
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults(null);
      setSearchLoading(false);
      return;
    }

    setSearchLoading(true);
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const { sessions } = await searchSessions({ q, content: true, depth: 5 });
          setSearchResults(mapSessionSummariesToChatSessions(sessions));
        } catch {
          setSearchResults([]);
        } finally {
          setSearchLoading(false);
        }
      })();
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const displayedHistory = useMemo(() => {
    const mergeWithHistory = (rows: ChatSession[]) =>
      rows.map((row) => {
        const existing = history.find((h) => h.id === row.id);
        if (!existing) return row;
        return {
          ...row,
          messages:
            (existing.messages?.length ?? 0) > 0
              ? existing.messages!
              : row.messages ?? [],
          flowName: existing.flowName ?? row.flowName,
          pinned: row.pinned ?? existing.pinned,
          ...reconcileSessionStreamMetadata(existing, row),
        };
      });

    if (!searchQuery.trim()) {
      const local = history
        .filter(
          (session) =>
            session &&
            session.id &&
            !session.id.startsWith("suggestion") &&
            shouldShowChatSessionInSidebar(session, activeChatId) &&
            matchesProjectFilter(session.projectId),
        )
        .map((session) => ({
          ...session,
          ...normalizeSessionStreamFlags(session),
        }));
      return sortSessions(local);
    }

    if (searchResults === null) {
      return [];
    }

    return sortSessions(mergeWithHistory(searchResults)).filter((session) =>
      matchesProjectFilter(session.projectId),
    );
  }, [history, searchQuery, searchResults, sortSessions, matchesProjectFilter, activeChatId]);

  const handlePinToggle = async (
    session: ChatSession,
    event: React.MouseEvent,
  ) => {
    event.stopPropagation();
    if (pinningId) return;

    const nextPinned = !session.pinned;
    setPinningId(session.id);
    try {
      await pinSession(session.id, nextPinned);
      onPinSession?.(session.id, nextPinned);
    } catch {
      /* parent may refresh on failure */
    } finally {
      setPinningId(null);
    }
  };

  const handleConfirmLogout = async () => {
    setShowLogoutConfirm(false);
    setLogoutPending(true);
    try {
      await hermesLogout();
    } catch {
      /* clear local shell even if network logout fails */
    } finally {
      setLogoutPending(false);
      onLogout?.();
    }
  };

  const mobileClasses = `fixed inset-y-0 left-0 z-50 w-72 bg-white dark:bg-black border-r border-zinc-200 dark:border-zinc-900 flex flex-col transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${isOpen ? "translate-x-0" : "-translate-x-full"}`;

  // Content of the sidebar (overflow-visible so user menu dropdown can extend outside)
  const SidebarContent = (
    <div className="flex flex-col h-full w-full overflow-visible bg-zinc-50 dark:bg-black">
      {/* Logout Confirmation Modal */}
      {showLogoutConfirm && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm animate-modal-backdrop">
          <div className="bg-white dark:bg-[#18181b] rounded-2xl shadow-2xl p-6 max-w-sm mx-4 animate-modal-content border border-zinc-200 dark:border-zinc-800">
            <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100 mb-2">
              {t("sidebar.logout")}
            </h3>
            <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-6">
              {language === "th"
                ? "คุณแน่ใจหรือไม่ว่าต้องการออกจากระบบ?"
                : "Are you sure you want to log out?"}
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setShowLogoutConfirm(false)}
                className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
              >
                {language === "th" ? "ยกเลิก" : "Cancel"}
              </button>
              <button
                onClick={() => void handleConfirmLogout()}
                disabled={logoutPending}
                className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {logoutPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : null}
                {t("sidebar.logout")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Logo Area */}
      <div
        className={`flex items-center text-zinc-800 dark:text-zinc-100 font-bold tracking-tight w-full flex-shrink-0 h-16 ${showExpanded ? "px-4 gap-2 justify-between" : "justify-center"}`}
      >
        <div
          className="flex items-center gap-2 cursor-pointer p-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          onClick={toggleSidebar}
          onMouseEnter={() => setIsLogoHovered(true)}
          onMouseLeave={() => setIsLogoHovered(false)}
          title={!isOpen ? "Expand Sidebar" : undefined}
        >
          {!isOpen && isLogoHovered ? (
            // Show PanelLeftOpen icon when collapsed and hovered
            <PanelLeftOpen className="w-6 h-6 text-zinc-600 dark:text-zinc-400" />
          ) : (
            // Show Default Logo
            <svg
              className="w-7 h-7 text-zinc-900 dark:text-white flex-shrink-0"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5zm0 9l2-1-10-5-2 1 10 5zm0 2.5l-8-4-2 1 10 5 10-5-2-1-8 4z" />
            </svg>
          )}

          {showExpanded && (
            <span className="text-lg whitespace-nowrap animate-in fade-in duration-200">
              Agent
            </span>
          )}
        </div>

        {showExpanded && toggleSidebar && (
          <button
            onClick={toggleSidebar}
            className="p-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-lg text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 transition-colors"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Main Nav */}
      <div
        className={`flex flex-col w-full ${showExpanded ? "px-3 space-y-1" : "items-center space-y-4 mt-2"}`}
      >
        {/* New Chat Button */}
        <button
          onClick={onNewChat}
          className={
            showExpanded
              ? "w-full flex items-center gap-3 px-3 py-2 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-200 rounded-lg transition-colors font-medium mb-3 whitespace-nowrap border border-zinc-200 dark:border-zinc-700"
              : "w-9 h-9 flex items-center justify-center text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-xl transition-colors"
          }
          title={!showExpanded ? t("sidebar.newTask") : undefined}
        >
          {showExpanded ? (
            <>
              <Plus className="w-4 h-4 flex-shrink-0" />
              <span>{t("sidebar.newTask")}</span>
            </>
          ) : (
            <SquarePen className="w-5 h-5" />
          )}
        </button>

        {/* Search */}
        {showExpanded ? (
          <div className="relative mb-2 animate-in fade-in duration-200">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-black/70 dark:text-white/70 pointer-events-none" />
            <input
              type="text"
              placeholder={t("sidebar.search")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-zinc-200/50 dark:bg-zinc-900/50 text-black dark:text-white placeholder-black/50 dark:placeholder-white/50 pl-10 pr-3 py-2 rounded-lg outline-none hover:bg-zinc-200 dark:hover:bg-zinc-900 focus:bg-zinc-200 dark:focus:bg-zinc-900 border border-transparent focus:border-zinc-300 dark:focus:border-zinc-800 transition-all text-sm"
            />
            {searchLoading && (
              <Loader2 className="w-3.5 h-3.5 absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-zinc-400" />
            )}
          </div>
        ) : (
          <button
            onClick={toggleSidebar}
            className="w-9 h-9 flex items-center justify-center text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-800 rounded-xl transition-colors"
            title={t("sidebar.search")}
          >
            <Search className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Workspace icon rail (left) + task history (right) when expanded */}
      <div
        className={`flex min-h-0 w-full flex-1 ${
          showExpanded ? "mt-2 flex-row" : "flex-col items-center"
        }`}
      >
        <div
          className={
            showExpanded
              ? "flex w-11 shrink-0 flex-col items-center gap-1 py-1 pl-2"
              : "mt-2 flex flex-col items-center space-y-2"
          }
        >
          {shellNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            const label = t(item.labelKey);
            return (
              <button
                key={item.path}
                type="button"
                onClick={() => handleShellNav(item.path)}
                className={`flex h-9 w-9 items-center justify-center rounded-xl transition-colors ${
                  isActive
                    ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                    : "text-zinc-500 dark:text-zinc-400 hover:bg-zinc-200 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                }`}
                title={label}
                aria-label={label}
              >
                <Icon className="h-5 w-5 shrink-0" />
              </button>
            );
          })}
        </div>

        {showExpanded && (
          <div
            ref={historyContainerRef}
            className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto overflow-x-hidden border-l border-zinc-200 px-2 scrollbar-hide dark:border-zinc-800"
          >
            <div className="mb-2 flex items-center justify-between px-2 pt-1 text-xs font-semibold uppercase tracking-wider text-black/80 dark:text-white/80">
              <span>{t("sidebar.history")}</span>
              <History className="h-3 w-3" />
            </div>
            {!searchQuery.trim() && (
              <ProjectsBar
                projects={projects}
                activeFilter={projectFilter}
                onFilterChange={setProjectFilter}
                loading={projectsLoading}
                actionPending={projectActionPending}
                onCreateProject={createNewProject}
                onRenameProject={renameExistingProject}
                onUpdateColor={updateProjectColor}
                onDeleteProject={removeProject}
              />
            )}
            <div className="space-y-0.5">
              {displayedHistory.length === 0 ? (
                <div className="px-2 py-4 text-center text-[10px] italic text-black/60 dark:text-white/60">
                  {searchLoading
                    ? t("sidebar.searching")
                    : searchQuery
                      ? t("sidebar.noMatching")
                      : t("sidebar.noTasks")}
                </div>
              ) : (
                displayedHistory.map((session) => {
                  const sessionRunning = isSidebarSessionRunning(session, {
                    activeChatId,
                    isActivePaneStreaming,
                  });
                  return (
                  <div
                    key={session.id}
                    className="sidebar-item group relative flex items-center"
                  >
                    <button
                      ref={activeChatId === session.id ? activeChatRef : null}
                      onClick={() => {
                        isSelectingChatRef.current = true;
                        scrollPositionRef.current = historyContainerRef.current?.scrollTop || 0;
                        onSelectChat(session.id);
                      }}
                      className={`sidebar-chat-btn flex min-w-0 flex-1 flex-col gap-0.5 overflow-hidden rounded-xl px-2 py-2 text-left text-xs ${
                        sessionRunning ? "pr-20" : "pr-14"
                      } ${activeChatId === session.id ? "is-active" : ""}`}
                    >
                      <div className="flex min-w-0 w-full items-center gap-2">
                        {session.pinned ? (
                          <Pin className="h-3 w-3 shrink-0 text-amber-500" />
                        ) : sessionRunning ? (
                          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-[#1447E6]" />
                        ) : (
                          <div
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${activeChatId === session.id ? "bg-[#1447E6]" : "bg-transparent group-hover:bg-zinc-400 dark:group-hover:bg-zinc-700"}`}
                          />
                        )}
                        <span className="min-w-0 flex-1 truncate font-medium">
                          {session.title || "Untitled Chat"}
                        </span>
                        {(session.messageCount ?? session.messages?.length ?? 0) > 0 && (
                          <span className="shrink-0 text-[10px] tabular-nums text-zinc-500 dark:text-zinc-700">
                            {session.messageCount ?? session.messages?.length ?? 0}
                          </span>
                        )}
                      </div>
                      {session.matchPreview && (
                        <span className="truncate pl-3.5 text-[10px] italic text-zinc-500 dark:text-zinc-500">
                          {session.matchPreview}
                        </span>
                      )}
                      {session.flowId &&
                        (() => {
                          const agentName =
                            session.flowName ??
                            agentModels.find((a) => a.id === session.flowId)?.name;
                          if (!agentName) return null;
                          return (
                            <span className="truncate pl-3.5 text-[10px] text-zinc-500 dark:text-zinc-500">
                              {agentName}
                            </span>
                          );
                        })()}
                    </button>

                    {sessionRunning && onCancelSession ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onCancelSession(session.id);
                        }}
                        className="sidebar-delete absolute right-9 rounded-md p-1.5 text-red-500 transition-all duration-200 hover:bg-red-500/10 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-400/20 dark:hover:text-red-300"
                        title={t("sidebar.stopSession")}
                      >
                        <Square className="h-3.5 w-3.5 fill-current" />
                      </button>
                    ) : null}

                    <button
                      onClick={(e) => void handlePinToggle(session, e)}
                      disabled={pinningId === session.id}
                      className={`sidebar-delete absolute rounded-md p-1.5 transition-all duration-200 ${
                        sessionRunning ? "right-16" : "right-9"
                      } ${
                        session.pinned
                          ? "text-amber-500 hover:bg-amber-500/10 hover:text-amber-600"
                          : "text-zinc-400 opacity-0 hover:bg-zinc-500/10 hover:text-zinc-600 group-hover:opacity-100 dark:hover:text-zinc-300"
                      }`}
                      title={
                        session.pinned ? t("sidebar.unpinSession") : t("sidebar.pinSession")
                      }
                    >
                      {pinningId === session.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Pin className={`h-3.5 w-3.5 ${session.pinned ? "fill-current" : ""}`} />
                      )}
                    </button>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteChat(session.id);
                      }}
                      className="sidebar-delete absolute right-2 rounded-md p-1.5 text-red-500 transition-all duration-200 hover:bg-red-500/10 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-400/20 dark:hover:text-red-300"
                      title={t("sidebar.deleteChat")}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
                })
              )}
            </div>
          </div>
        )}
      </div>

      {/* Bottom Actions */}
      <div
        className={`border-t border-zinc-200 dark:border-zinc-900 relative w-full overflow-visible ${showExpanded ? "p-3" : "p-2 flex justify-center py-4"}`}
      >
        <div
          className={`flex items-center ${showExpanded ? "gap-2" : "flex-col gap-2"}`}
        >
          {showExpanded ? (
            <div ref={userMenuRef} className="relative flex-1 flex">
              {/* Settings Button - Expanded */}
              <button
                onClick={() => setShowUserMenu(!showUserMenu)}
                className="flex items-center rounded-xl gap-3 px-3 py-2.5 cursor-pointer flex-1 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors text-zinc-700 dark:text-zinc-300"
                title={t("sidebar.settings")}
              >
                <div className="w-9 h-9 rounded-xl bg-zinc-200 dark:bg-zinc-800 flex items-center justify-center shrink-0">
                  <Settings className="w-5 h-5 text-zinc-600 dark:text-zinc-400" />
                </div>
                <span className="text-sm font-medium flex-1 text-left truncate">{t("sidebar.settings")}</span>
                <ChevronDown className={`w-4 h-4 text-zinc-400 shrink-0 transition-transform ${showUserMenu ? "rotate-180" : ""}`} />
              </button>

              {/* Settings Menu Dropdown - Expanded */}
              {showUserMenu && (
                <div
                  className="absolute bottom-full left-0 right-0 mb-2 min-w-[280px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-2xl p-3 z-50 animate-in slide-in-from-top-2 fade-in duration-200"
                >
                  {/* Theme Section */}
                  <div className="mb-3 animate-agent-option" style={{ animationDelay: '0ms' }}>
                    <div className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-2 uppercase tracking-wider px-1">
                      {t("sidebar.theme")}
                    </div>
                    <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-1 border border-zinc-200 dark:border-zinc-800">
                      <button
                        onClick={() => setTheme("light")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "light"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Sun className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setTheme("dark")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "dark"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Moon className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setTheme("system")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "system"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Laptop className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50 animate-agent-option" style={{ animationDelay: '35ms' }}></div>

                  {/* Language Dropdown */}
                  <div className="px-1 py-1 animate-agent-option" style={{ animationDelay: '70ms' }} ref={languageDropdownRef}>
                    <div className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-2 uppercase tracking-wider">
                      {t("sidebar.language")}
                    </div>
                    <div className="relative">
                      <button
                        onClick={() => setShowLanguageDropdown(!showLanguageDropdown)}
                        className="w-full flex items-center justify-between bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-200 text-sm border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <Languages className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
                          <span>{language === "en" ? "English" : "ไทย"}</span>
                        </div>
                        <ChevronDown
                          className={`w-4 h-4 text-zinc-500 transition-transform ${showLanguageDropdown ? "rotate-180" : ""}`}
                        />
                      </button>

                      {showLanguageDropdown && (
                        <div className="absolute bottom-full left-0 right-0 mb-1 bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg overflow-hidden z-50 animate-in fade-in slide-in-from-bottom-1 duration-150">
                          <button
                            onClick={() => {
                              setLanguage("en");
                              setShowLanguageDropdown(false);
                            }}
                            className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                              language === "en"
                                ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                                : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                            }`}
                          >
                            <span className="flex-1 text-left">English</span>
                            {language === "en" && <Check className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={() => {
                              setLanguage("th");
                              setShowLanguageDropdown(false);
                            }}
                            className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                              language === "th"
                                ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                                : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                            }`}
                          >
                            <span className="flex-1 text-left">ไทย</span>
                            {language === "th" && <Check className="w-4 h-4" />}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50 animate-agent-option" style={{ animationDelay: '105ms' }}></div>

                  {/* Go to Settings Page */}
                  <button
                    onClick={() => {
                      setShowUserMenu(false);
                      onOpenSettings();
                    }}
                    className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 font-medium animate-agent-option"
                    style={{ animationDelay: '140ms' }}
                  >
                    <Settings className="w-4 h-4 shrink-0 text-zinc-500 dark:text-zinc-400" />
                    <span className="flex-1 text-left">{t("settings.title")}</span>
                  </button>

                  {/* Logout Button */}
                  {onLogout && (
                    <button
                      onClick={() => {
                        setShowUserMenu(false);
                        setShowLogoutConfirm(true);
                      }}
                      className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium animate-agent-option"
                      style={{ animationDelay: '175ms' }}
                    >
                      <LogOut className="w-4 h-4 shrink-0" />
                      <span className="flex-1 text-left">{t("sidebar.logout")}</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div ref={userMenuRef} className="relative">
              {/* Settings Button - Collapsed */}
              <button
                onClick={() => setShowUserMenu(!showUserMenu)}
                className="flex items-center justify-center w-10 h-10 rounded-xl cursor-pointer transition-colors hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-400"
                title={t("sidebar.settings")}
              >
                <Settings className="w-5 h-5" />
              </button>
              {/* Settings Menu Dropdown - Collapsed (open to the right, align bottom so doesn't overflow below) */}
              {showUserMenu && (
                <div
                  className="absolute left-full bottom-0 ml-2 w-[240px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-2xl p-3 z-50 animate-in slide-in-from-left-2 fade-in duration-200"
                >
                  {/* Theme Section */}
                  <div className="mb-3 animate-agent-option" style={{ animationDelay: '0ms' }}>
                    <div className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-2 uppercase tracking-wider px-1">
                      {t("sidebar.theme")}
                    </div>
                    <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-1 border border-zinc-200 dark:border-zinc-800">
                      <button
                        onClick={() => setTheme("light")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "light"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Sun className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setTheme("dark")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "dark"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Moon className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => setTheme("system")}
                        className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
                          theme === "system"
                            ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                            : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                        }`}
                      >
                        <Laptop className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50 animate-agent-option" style={{ animationDelay: '35ms' }}></div>

                  {/* Language Buttons */}
                  <div className="flex gap-2 mb-2 animate-agent-option" style={{ animationDelay: '70ms' }}>
                    <button
                      onClick={() => setLanguage("en")}
                      className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                        language === "en"
                          ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                          : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      }`}
                    >
                      <Languages className="w-4 h-4" />
                      EN
                    </button>
                    <button
                      onClick={() => setLanguage("th")}
                      className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                        language === "th"
                          ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                          : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      }`}
                    >
                      <Languages className="w-4 h-4" />
                      ไทย
                    </button>
                  </div>

                  <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50 animate-agent-option" style={{ animationDelay: '105ms' }}></div>

                  {/* Settings Button */}
                  <button
                    onClick={() => {
                      setShowUserMenu(false);
                      onOpenSettings();
                    }}
                    className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 font-medium animate-agent-option"
                    style={{ animationDelay: '140ms' }}
                  >
                    <Settings className="w-4 h-4 shrink-0 text-zinc-500 dark:text-zinc-400" />
                    <span className="flex-1 text-left">{t("settings.title")}</span>
                  </button>

                  {/* Logout Button */}
                  {onLogout && (
                    <button
                      onClick={() => {
                        setShowUserMenu(false);
                        setShowLogoutConfirm(true);
                      }}
                      className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium animate-agent-option"
                      style={{ animationDelay: '175ms' }}
                    >
                      <LogOut className="w-4 h-4 shrink-0" />
                      <span className="flex-1 text-left">{t("sidebar.logout")}</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );

  if (isMobile) {
    return <div className={mobileClasses}>{SidebarContent}</div>;
  }

  return (
    <div
      className={`h-full flex-shrink-0 bg-zinc-50 dark:bg-black border-r border-zinc-200 dark:border-zinc-900 flex flex-col transition-all duration-300 ease-in-out ${isOpen ? "w-64" : "w-[50px]"}`}
    >
      {SidebarContent}
    </div>
  );
};
