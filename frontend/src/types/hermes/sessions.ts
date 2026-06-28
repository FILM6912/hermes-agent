/**
 * Hermes session API shapes (M08–M12).
 * @see GET /api/v1/sessions, POST /session/new|delete|rename, GET /session
 */

/** Core session row fields returned by `Session.compact()` and sidebar list. */
export type HermesSessionSummary = {
  session_id: string;
  title: string;
  workspace?: string;
  model?: string;
  model_provider?: string;
  message_count?: number;
  created_at?: number;
  updated_at?: number;
  last_message_at?: number;
  pinned?: boolean;
  archived?: boolean;
  project_id?: string | null;
  profile?: string | null;
  is_cli_session?: boolean;
  is_streaming?: boolean;
  read_only?: boolean;
  source_tag?: string;
  raw_source?: string;
  session_source?: string;
  source_label?: string;
  parent_session_id?: string;
  worktree_path?: string;
  worktree_branch?: string;
  /** Additional server fields (tokens, compression, gateway, etc.). */
  [key: string]: unknown;
};

/** Message objects vary by source (WebUI, CLI, state.db). */
export type HermesSessionMessage = Record<string, unknown>;

/** Full session payload from `GET /session` or `POST /session/new`. */
export type HermesSessionDetail = HermesSessionSummary & {
  messages?: HermesSessionMessage[];
  tool_calls?: unknown[];
  pending_user_message?: unknown;
  pending_attachments?: unknown[];
  pending_started_at?: number | null;
  context_length?: number;
  threshold_tokens?: number;
  last_prompt_tokens?: number;
  _messages_truncated?: boolean;
  _messages_offset?: number;
  runtime_journal?: unknown;
};

/** GET /api/v1/sessions — sidebar session list with profile scope metadata. */
export type HermesSessionsListResponse = {
  sessions: HermesSessionSummary[];
  cli_count?: number;
  all_profiles?: boolean;
  active_profile?: string;
  other_profile_count?: number;
  server_time?: number;
  server_tz?: string;
};

/** GET /api/v1/session — session detail envelope. */
export type HermesSessionDetailResponse = {
  session: HermesSessionDetail;
};

/** POST /api/v1/session/new — created session envelope (includes messages). */
export type HermesSessionCreateResponse = HermesSessionDetailResponse;

/** POST /api/v1/session/rename — updated compact session. */
export type HermesSessionRenameResponse = {
  session: HermesSessionSummary;
};

/** POST /api/v1/session/delete — success with optional worktree retention hints. */
export type HermesSessionDeleteResponse = {
  ok: boolean;
  worktree_retained?: boolean;
  worktree_path?: string;
  [key: string]: unknown;
};

export type ListSessionsOptions = {
  /** When true, include sessions from all profiles (maps to `all_profiles=1`). */
  allProfiles?: boolean;
};

export type GetSessionOptions = {
  /** Load message history (default true). Set false for metadata-only. */
  loadMessages?: boolean;
  /** Resolve effective model/provider for display (defaults to loadMessages). */
  resolveModel?: boolean;
  /** Max messages to return (pagination window). */
  msgLimit?: number;
  /** Message index upper bound for pagination. */
  msgBefore?: number;
};

export type CreateSessionOptions = {
  workspace?: string;
  model?: string;
  modelProvider?: string;
  profile?: string;
  projectId?: string;
  prevSessionId?: string;
  worktree?: boolean | string;
};

/** POST /session/delete request body. */
export type HermesSessionDeleteBody = {
  session_id: string;
};

/** POST /session/rename request body. */
export type HermesSessionRenameBody = {
  session_id: string;
  title: string;
};

/** POST /session/update request body. */
export type HermesSessionUpdateBody = {
  session_id: string;
  workspace?: string;
  model?: string;
  model_provider?: string | null;
};

/** POST /session/pin request body. */
export type HermesSessionPinBody = {
  session_id: string;
  pinned: boolean;
};

/** POST /session/pin response envelope. */
export type HermesSessionPinResponse = {
  ok: boolean;
  session: HermesSessionSummary;
};

export type SearchSessionsOptions = {
  q?: string;
  /** When true (default), search message content as well as titles. */
  content?: boolean;
  depth?: number;
};

/** Row from GET /sessions/search (title or content match). */
export type HermesSessionSearchResult = HermesSessionSummary & {
  match_type?: "title" | "content";
  match_preview?: string;
};

/** GET /sessions/search response. */
export type HermesSessionsSearchResponse = {
  sessions: HermesSessionSearchResult[];
  query?: string;
  count?: number;
};
