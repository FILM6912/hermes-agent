/**
 * Hermes chat API + SSE shapes (M12–M14).
 * @see POST /api/v1/chat/start, GET /api/v1/chat/stream, GET /api/v1/chat/cancel
 */

/** Attachment payload for `POST /api/v1/chat/start` (after POST /upload). */
export type HermesChatAttachmentPayload = {
  name: string;
  path: string;
  mime?: string;
  size?: number;
  is_image?: boolean;
  workspace_rel?: string;
};

/** Body for `POST /api/v1/chat/start`. */
export type HermesChatStartBody = {
  session_id: string;
  message: string;
  model: string;
  workspace?: string;
  model_provider?: string | null;
  profile?: string;
  attachments?: (string | HermesChatAttachmentPayload)[];
};

/** JSON response from chat start — at minimum includes `stream_id`. */
export type HermesChatStartResult = {
  stream_id: string;
  title?: string;
  effective_model?: string;
  effective_model_provider?: string | null;
  pending_started_at?: number;
};

export type HermesChatCancelResult = {
  ok: boolean;
  cancelled?: boolean;
  stream_id?: string;
};

/** GET /api/v1/chat/stream/status — live worker + journal replay hints. */
export type HermesChatStreamStatusResult = {
  active: boolean;
  stream_id: string;
  replay_available: boolean;
  journal?: Record<string, unknown>;
};

/** SSE `token` event payload. */
export type HermesChatStreamTokenPayload = {
  text?: string;
};

/** SSE `reasoning` event payload. */
export type HermesChatStreamReasoningPayload = {
  text?: string;
};

/** SSE `tool` / `tool_complete` event payload. */
export type HermesChatStreamToolPayload = {
  name?: string;
  preview?: string;
  args?: unknown;
  snippet?: string;
  tid?: string;
  done?: boolean;
  is_error?: boolean;
  duration?: number;
};

/** SSE `metering` event payload — live token usage during streaming. */
export type HermesChatStreamMeteringPayload = {
  session_id?: string;
  usage?: Record<string, unknown>;
  estimated?: boolean;
  tps?: number;
  tps_available?: boolean;
};

/** SSE `compressed` event payload — context auto-compression finished. */
export type HermesChatStreamCompressedPayload = {
  session_id?: string;
  old_session_id?: string;
  new_session_id?: string;
  continuation_session_id?: string;
  usage?: Record<string, unknown>;
  message?: string;
};

/** SSE `done` event payload. */
export type HermesChatStreamDonePayload = {
  session?: Record<string, unknown>;
  usage?: Record<string, unknown>;
};

/** SSE `stream_end` event payload. */
export type HermesChatStreamEndPayload = {
  session_id?: string;
  reason?: string;
};

/** SSE `stream_close` event payload — live channel closed after optional late events. */
export type HermesChatStreamClosePayload = {
  session_id?: string;
};

/** SSE `title` event payload — LLM-generated session title after first turn. */
export type HermesChatStreamTitlePayload = {
  session_id?: string;
  title?: string;
};

/** SSE `apperror` / `error` event payload. */
export type HermesChatStreamErrorPayload = {
  message?: string;
  type?: string;
  hint?: string;
  details?: string;
  label?: string;
};

export type HermesSubscribeChatStreamOptions = {
  /** Resume after this journal sequence (`after_seq` query param). */
  afterSeq?: number;
  /** Request journal replay when the live worker is gone (`replay=1`). */
  replay?: boolean;
};

export type HermesChatStreamHandlers = {
  /** Incremental assistant text (`token` SSE events). */
  onTextDelta?: (text: string, payload: HermesChatStreamTokenPayload) => void;
  /** Reasoning / thinking trace (`reasoning` SSE events). */
  onReasoningDelta?: (text: string, payload: HermesChatStreamReasoningPayload) => void;
  /** Tool invocation started (`tool` SSE events). */
  onTool?: (payload: HermesChatStreamToolPayload) => void;
  /** Tool invocation finished (`tool_complete` SSE events). */
  onToolComplete?: (payload: HermesChatStreamToolPayload) => void;
  /** Turn finished (`done` SSE event). Stream may stay open until `stream_end`. */
  onDone?: (payload: HermesChatStreamDonePayload) => void;
  /** Live token/context usage during streaming (`metering` SSE events). */
  onMetering?: (payload: HermesChatStreamMeteringPayload) => void;
  /** Context auto-compressed (`compressed` SSE event). */
  onCompressed?: (payload: HermesChatStreamCompressedPayload) => void;
  /** LLM session title persisted in background (`title` SSE event). */
  onTitle?: (payload: HermesChatStreamTitlePayload) => void;
  /** Assistant turn finished (`stream_end` SSE event). SSE may stay open for `title`. */
  onStreamEnd?: (payload: HermesChatStreamEndPayload) => void;
  /** Live SSE channel closed after optional post-`stream_end` events (`stream_close`). */
  onStreamClose?: (payload: HermesChatStreamClosePayload) => void;
  /** Application or transport failure (`apperror` / `error` SSE, or EventSource disconnect). */
  onError?: (payload: HermesChatStreamErrorPayload) => void;
};
