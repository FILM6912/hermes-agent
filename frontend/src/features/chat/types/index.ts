import { ProcessStep } from "@/types";

export interface Attachment {
  name: string;
  type: "file" | "image";
  content: string;
  mimeType?: string;
}

export interface MessageVersion {
  content: string;
  attachments?: Attachment[];
  steps?: ProcessStep[];
  timestamp: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  timestamp: number;
  steps?: ProcessStep[];
  versions?: MessageVersion[];
  currentVersionIndex?: number;
}

export interface ChatInterfaceProps {
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  onSend: (message: string, attachments: Attachment[]) => void;
  onRegenerate: (messageId: string) => void;
  onEdit?: (messageId: string, newContent: string) => void;
  isLoading: boolean;
  isStreaming?: boolean;
  modelConfig: any; // Import from global types
  onModelConfigChange: (config: any) => void;
  onProviderChange?: (provider: any) => void;
  onVersionChange?: (messageId: string, newIndex: number) => void;
  isPreviewOpen?: boolean;
  onPreviewRequest?: (content: string) => void;
  onOpenSettings?: () => void;
  onLogout?: () => void;
}
