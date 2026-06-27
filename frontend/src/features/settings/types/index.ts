import { ModelConfig, ChatSession } from "@/types";

export type SettingsTab = "general" | "account";

export interface SettingsViewProps {
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
  onBack: () => void;
  chatHistory: ChatSession[];
  onDeleteChat: (id: string) => void;
  onClearAllChats: () => Promise<boolean>;
  initialTab?: SettingsTab;
  onTabChange?: (tab: SettingsTab) => void;
}

