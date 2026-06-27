import React, { useState, useEffect, useMemo } from "react";
import {
  Settings,
  User,
  ArrowLeft,
  PanelLeftClose,
  PanelLeftOpen,
  Users,
  Layers,
  KeyRound,
  Puzzle,
  Plug,
  FolderOpen,
  Shield,
  Building2,
} from "lucide-react";
import { ModelConfig, ChatSession } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";
import {
  AdminWorkspacesPanel,
  DepartmentsPanel,
  RolesPanel,
  UsersPanel,
  ProfilesPanel,
} from "@/features/admin";
import { GeneralTab } from "./tabs/GeneralTab";
import { AccountTab } from "./tabs/AccountTab";
import { ProvidersTab } from "./tabs/ProvidersTab";
import { PluginsTab } from "./tabs/PluginsTab";
import { McpTab } from "./tabs/McpTab";

export type SettingsTab =
  | "general"
  | "account"
  | "users"
  | "roles"
  | "departments"
  | "profiles"
  | "workspaces"
  | "providers"
  | "plugins"
  | "mcp";

interface SettingsViewProps {
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
  onBack: () => void;
  chatHistory: ChatSession[];
  onDeleteChat: (id: string) => void;
  onClearAllChats: () => Promise<boolean>;
  initialTab?: SettingsTab;
  onTabChange?: (tab: SettingsTab) => void;
}

type TabDef = {
  id: SettingsTab;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  adminOnly?: boolean;
  requiresProfileAdmin?: boolean;
};

const TAB_LABELS: Record<SettingsTab, string> = {
  general: "General",
  account: "Account",
  users: "Users",
  roles: "Roles",
  departments: "Departments",
  profiles: "Profiles",
  workspaces: "Workspaces",
  providers: "Providers",
  plugins: "Plugins",
  mcp: "MCP",
};

export const SettingsView: React.FC<SettingsViewProps> = ({
  modelConfig: _modelConfig,
  onModelConfigChange: _onModelConfigChange,
  onBack,
  chatHistory,
  onDeleteChat: _onDeleteChat,
  onClearAllChats,
  initialTab = "general",
  onTabChange,
}) => {
  const { t } = useLanguage();
  const { canManageUsers, canManageRoles, canManageProfiles, canManageWorkspaces } = useAuthRole();
  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const navItems = useMemo((): TabDef[] => {
    const items: TabDef[] = [
      { id: "general", icon: Settings, label: t("settings.general") },
      { id: "account", icon: User, label: t("settings.account") },
      { id: "providers", icon: KeyRound, label: "Providers" },
      { id: "plugins", icon: Puzzle, label: "Plugins" },
      { id: "mcp", icon: Plug, label: t("settings.mcpNav") || "MCP" },
    ];
    if (canManageProfiles) {
      items.push({ id: "profiles", icon: Layers, label: "Profiles", requiresProfileAdmin: true });
    }
    if (canManageUsers) {
      items.push({ id: "users", icon: Users, label: "Users", adminOnly: true });
      items.push({ id: "roles", icon: Shield, label: "Roles", adminOnly: true });
      items.push({ id: "departments", icon: Building2, label: "Departments", adminOnly: true });
    } else if (canManageRoles) {
      items.push({ id: "roles", icon: Shield, label: "Roles", adminOnly: true });
    }
    if (canManageWorkspaces) {
      items.push({
        id: "workspaces",
        icon: FolderOpen,
        label: "Workspaces",
        adminOnly: true,
      });
    }
    return items;
  }, [canManageProfiles, canManageRoles, canManageUsers, canManageWorkspaces, t]);

  const visibleTabIds = useMemo(() => new Set(navItems.map((item) => item.id)), [navItems]);

  useEffect(() => {
    const rawTab = initialTab as string;
    const fallback = rawTab === "agent" ? "general" : initialTab;
    if (visibleTabIds.has(fallback)) {
      setActiveTab(fallback);
      return;
    }
    setActiveTab("general");
    if (fallback !== "general") {
      onTabChange?.("general");
    }
  }, [initialTab, visibleTabIds, onTabChange]);

  const handleTabChange = (tab: SettingsTab) => {
    setActiveTab(tab);
    onTabChange?.(tab);
  };

  const activeLabel =
    navItems.find((item) => item.id === activeTab)?.label ?? TAB_LABELS[activeTab] ?? activeTab;

  const ActiveIcon = navItems.find((item) => item.id === activeTab)?.icon ?? Settings;

  return (
    <div className="flex h-full w-full bg-zinc-50 dark:bg-[#09090b] text-zinc-900 dark:text-zinc-200 overflow-hidden transition-colors duration-200">
      <div
        className={`border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-[#09090b] flex flex-col transition-all duration-300 ${isSidebarOpen ? "w-64" : "w-16"}`}
      >
        <div className="h-16 flex items-center justify-between px-4 border-b border-zinc-200 dark:border-zinc-800/50">
          {isSidebarOpen && (
            <h1 className="text-xl font-bold text-zinc-900 dark:text-zinc-100 tracking-tight">
              {t("settings.title")}
            </h1>
          )}
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors ml-auto"
            title={isSidebarOpen ? "ปิด Sidebar" : "เปิด Sidebar"}
          >
            {isSidebarOpen ? (
              <PanelLeftClose className="w-4 h-4" />
            ) : (
              <PanelLeftOpen className="w-4 h-4" />
            )}
          </button>
        </div>

        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => handleTabChange(item.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 outline-none focus:outline-none focus-visible:outline-none active:outline-none ${
                activeTab === item.id
                  ? "bg-white dark:bg-[#27272a] text-zinc-900 dark:text-white font-medium shadow-sm"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
              }`}
              title={!isSidebarOpen ? item.label : undefined}
            >
              <item.icon className="w-4 h-4 flex-shrink-0" />
              {isSidebarOpen && item.label}
            </button>
          ))}
        </nav>

        <div className="p-4 border-t border-zinc-200 dark:border-zinc-800">
          <button
            onClick={onBack}
            className={`flex items-center gap-2 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white transition-colors text-sm font-medium ${!isSidebarOpen ? "justify-center w-full" : ""}`}
            title={!isSidebarOpen ? t("settings.back") : undefined}
          >
            <ArrowLeft className="w-4 h-4" />
            {isSidebarOpen && t("settings.back")}
          </button>
        </div>
      </div>

      <div className="flex-1 bg-zinc-50 dark:bg-black flex flex-col overflow-hidden transition-colors duration-200">
        <div className="h-16 flex items-center justify-between px-8 border-b border-zinc-200 dark:border-zinc-800/50 flex-shrink-0 bg-white/50 dark:bg-black/50 backdrop-blur-sm">
          <div className="flex items-center gap-3">
            <ActiveIcon className="w-5 h-5 text-blue-500" />
            <h2 className="text-lg font-bold text-zinc-900 dark:text-white tracking-wide">
              {activeLabel}
            </h2>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {activeTab === "general" && (
            <GeneralTab chatHistory={chatHistory} onClearAllChats={onClearAllChats} />
          )}
          {activeTab === "account" && <AccountTab />}
          {activeTab === "users" && canManageUsers && <UsersPanel />}
          {activeTab === "roles" && (canManageUsers || canManageRoles) && <RolesPanel />}
          {activeTab === "departments" && canManageUsers && <DepartmentsPanel />}
          {activeTab === "profiles" && canManageProfiles && <ProfilesPanel />}
          {activeTab === "workspaces" && canManageWorkspaces && <AdminWorkspacesPanel />}
          {activeTab === "providers" && <ProvidersTab />}
          {activeTab === "plugins" && <PluginsTab />}
          {activeTab === "mcp" && <McpTab />}
        </div>
      </div>
    </div>
  );
};
