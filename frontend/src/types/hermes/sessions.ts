import type { SessionCompressionAnchor } from "@/types";

export type HermesSessionMessage = {
  id?: string;
  role?: string;
  content?: unknown;
  timestamp?: number;
  _ts?: number;
  steps?: unknown[];
  [key: string]: unknown;
};

export type HermesSessionSummary = {
  session_id?: string;
  id?: string;
  title?: string | null;
  pinned?: boolean;
  updated_at?: number;
  message_count?: number;
  active_stream_id?: string | null;
  model?: string;
  project_id?: string | null;
  [key: string]: unknown;
};

export type HermesSessionDetail = HermesSessionSummary & {
  messages?: HermesSessionMessage[];
  tool_calls?: unknown[];
  workspace?: string;
  pending_user_message?: string;
  pending_attachments?: unknown[];
  pending_started_at?: number;
  compression_anchor?: SessionCompressionAnchor;
  input_tokens?: number;
  output_tokens?: number;
  last_prompt_tokens?: number;
  context_length?: number;
  threshold_tokens?: number;
  estimated_cost?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cache_hit_percent?: number | null;
};
