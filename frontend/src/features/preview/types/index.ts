export interface ProcessStep {
  id: string;
  type: "thinking" | "command" | "edit" | "error" | "success";
  title?: string;
  content: string;
  duration?: string;
  isExpanded?: boolean;
  status: "running" | "completed" | "pending";
}

export interface PreviewWindowProps {
  isOpen: boolean;
  onToggle: () => void;
  isMobile: boolean;
  isSidebarOpen: boolean;
  isLoading: boolean;
}

export interface ProcessStepProps {
  step: ProcessStep;
}
