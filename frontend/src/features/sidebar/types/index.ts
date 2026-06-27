import { ChatSession, AIProvider } from "@/types";

export interface SidebarProps {
  history: ChatSession[];
  onNewChat: () => void;
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  activeProvider: AIProvider;
  onProviderChange: (provider: AIProvider) => void;
  onOpenSettings: () => void;
  isOpen?: boolean;
  toggleSidebar?: () => void;
  isMobile?: boolean;
  onLogout?: () => void;
}
