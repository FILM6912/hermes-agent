export type AIProvider = "google" | "openai";

import type { SessionContextUsage } from "@/features/chat/utils/contextUsage";

export type { SessionContextUsage };

export interface ModelConfig {
  provider: AIProvider;
  /** Hermes catalog provider_id for API (model_provider); not the legacy UI enum. */
  modelProvider?: string;
  baseUrl: string;
  modelId: string;
  name: string;
  mcpServers?: string[];
  enabledConnections?: string[];
  enabledModels?: string[];
  systemPrompt?: string;
  voiceDelay?: number;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  description: string;
  avatar?: string;
  color?: string;
}

export interface ProcessStep {
  id: string;
  type: "thinking" | "command" | "edit" | "error" | "success";
  title?: string;
  content: string;
  duration?: string;
  isExpanded?: boolean;
  status: "running" | "completed" | "pending" | "cancelled";
  /** Raw Hermes tool name (e.g. write_file) for activity timeline labels. */
  toolName?: string;
  /** Short preview line from SSE / session tool_calls. */
  preview?: string;
  /** Display-text offset when a live SSE tool event was recorded (stream interleaving). */
  afterTextLength?: number;
}

/** Ordered assistant turn segment — text and tool activity interleaved (legacy parity). */
export type MessageBlock =
  | { type: "text"; content: string }
  | { type: "thinking"; steps: ProcessStep[] }
  | { type: "tools"; steps: ProcessStep[] };

export interface Attachment {
  name: string;
  type: "file" | "image";
  /** Preview URL (images) or server path after Hermes upload. */
  content: string;
  mimeType?: string;
  /** Hermes server path from POST /upload (used when sending chat). */
  path?: string;
  /** Workspace-relative path when stored under `.uploads/` (agent-facing). */
  workspace_rel?: string;
  /** Local blob preview before/after upload (never sent to server). */
  previewUrl?: string;
  size?: number;
  /** Local-only chip before POST /upload completes. */
  pending?: boolean;
}

export interface AIRegenVersion {
  content: string;
  attachments?: Attachment[];
  steps?: ProcessStep[];
  blocks?: MessageBlock[];
  suggestions?: string[];
  timestamp: number;
}

export interface AIVersion {
  content: string;
  attachments?: Attachment[];
  steps?: ProcessStep[];
  blocks?: MessageBlock[];
  suggestions?: string[];
  timestamp: number;
  regenVersions?: AIRegenVersion[];
  currentRegenIndex?: number;
}

export interface MessageVersion {
  content: string;
  attachments?: Attachment[];
  steps?: ProcessStep[];
  blocks?: MessageBlock[];
  suggestions?: string[];
  timestamp: number;
  // For user messages: AI versions with regen versions
  aiVersions?: AIVersion[];
  currentAIIndex?: number;
  // For assistant messages: tail messages (legacy)
  tail?: Message[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  timestamp: number;
  steps?: ProcessStep[];
  /** When set, render assistant body in this order instead of steps-then-content. */
  blocks?: MessageBlock[];
  versions?: MessageVersion[];
  currentVersionIndex?: number;
  suggestions?: string[];
  needsSuggestions?: boolean;
}

export type CompressionAnchorMessageKey = {
  role: string;
  ts?: number | null;
  text?: string;
  attachments?: number;
};

/** Persisted compaction handoff shown as a secondary transcript card. */
export type SessionCompressionAnchor = {
  summary: string;
  visibleIdx?: number | null;
  messageKey?: CompressionAnchorMessageKey | null;
  /** Raw compaction marker timestamp — used to place the card when role is `system`. */
  markerTimestamp?: number | null;
  engine?: string | null;
  mode?: string | null;
};

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
  /** Live + persisted context window usage for the composer ring. */
  contextUsage?: SessionContextUsage;
  /** Compacted earlier-turn reference card anchor from GET /session. */
  compressionAnchor?: SessionCompressionAnchor;
  /** Hermes session pin state (sidebar). */
  pinned?: boolean;
  /** Snippet from GET /sessions/search content match. */
  matchPreview?: string;
  /** LangFlow flow_id used in this chat (agent lock) */
  flowId?: string;
  /** Display name of the agent when flowId was set */
  flowName?: string;
  /** Hermes project grouping (sidebar filter / move). */
  projectId?: string | null;
  /** Server-side message count from GET /sessions (messages may be unloaded). */
  messageCount?: number;
  /** In-flight stream id from GET /sessions or GET /session (row-owned cancel). */
  activeStreamId?: string;
  /** Server/runtime flag: stream worker is live for this session. */
  isStreaming?: boolean;
}

export interface FileNode {
  name: string;
  type: "file" | "folder";
  children?: FileNode[];
}
