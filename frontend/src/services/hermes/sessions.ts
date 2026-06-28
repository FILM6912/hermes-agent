/**
 * Hermes session API client (M08–M11, M33 pin/search).
 * List, create, rename, delete, pin, and search sessions via `/api/v1/*`.
 */
import { fetchJson } from "@/lib/api";
import type {
  CreateSessionOptions,
  GetSessionOptions,
  HermesSessionCreateResponse,
  HermesSessionDeleteBody,
  HermesSessionDeleteResponse,
  HermesSessionDetailResponse,
  HermesSessionMessage,
  HermesSessionPinBody,
  HermesSessionPinResponse,
  HermesSessionRenameBody,
  HermesSessionRenameResponse,
  HermesSessionUpdateBody,
  HermesSessionSearchResult,
  HermesSessionSummary,
  HermesSessionsListResponse,
  HermesSessionsSearchResponse,
  ListSessionsOptions,
  SearchSessionsOptions,
} from "@/types/hermes/sessions";

export type {
  CreateSessionOptions,
  GetSessionOptions,
  HermesSessionCreateResponse,
  HermesSessionDeleteBody,
  HermesSessionDeleteResponse,
  HermesSessionDetail,
  HermesSessionDetailResponse,
  HermesSessionMessage,
  HermesSessionPinBody,
  HermesSessionPinResponse,
  HermesSessionRenameBody,
  HermesSessionRenameResponse,
  HermesSessionUpdateBody,
  HermesSessionSearchResult,
  HermesSessionSummary,
  HermesSessionsListResponse,
  HermesSessionsSearchResponse,
  ListSessionsOptions,
  SearchSessionsOptions,
} from "@/types/hermes/sessions";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/**
 * Query params for M08 `GET /sessions`.
 * @param options — `allProfiles` maps to `all_profiles=1`.
 */
export function buildListSessionsQuery(
  options: ListSessionsOptions = {},
): Record<string, string> | undefined {
  if (!options.allProfiles) return undefined;
  return { all_profiles: "1" };
}

/**
 * Request body for M09 `POST /session/new`.
 */
export function buildCreateSessionBody(
  options: CreateSessionOptions = {},
): Record<string, unknown> {
  return {
    workspace: options.workspace,
    model: options.model,
    model_provider: options.modelProvider,
    profile: options.profile,
    project_id: options.projectId,
    prev_session_id: options.prevSessionId,
    worktree: options.worktree,
  };
}

/** Request body for M10 `POST /session/delete`. */
export function buildSessionDeleteBody(sessionId: string): HermesSessionDeleteBody {
  return { session_id: sessionId };
}

/** Request body for M11 `POST /session/rename`. */
export function buildSessionRenameBody(
  sessionId: string,
  title: string,
): HermesSessionRenameBody {
  return { session_id: sessionId, title };
}

/** Request body for `POST /session/update`. */
export function buildSessionUpdateBody(
  sessionId: string,
  options: {
    workspace?: string;
    model?: string;
    modelProvider?: string | null;
  } = {},
): HermesSessionUpdateBody {
  const body: HermesSessionUpdateBody = { session_id: sessionId };
  if (options.workspace !== undefined) body.workspace = options.workspace;
  if (options.model !== undefined) body.model = options.model;
  if (options.modelProvider !== undefined) body.model_provider = options.modelProvider;
  return body;
}

/** Request body for session pin toggle `POST /session/pin`. */
export function buildSessionPinBody(
  sessionId: string,
  pinned: boolean,
): HermesSessionPinBody {
  return { session_id: sessionId, pinned };
}

/**
 * Extract `session_id` from a detail or create envelope (M09).
 */
export function sessionIdFromDetailResponse(
  response: HermesSessionDetailResponse,
): string {
  return response.session.session_id;
}

/** Narrow an unknown session row to a summary (requires `session_id`). */
export function narrowSessionSummary(value: unknown): HermesSessionSummary | null {
  if (!isRecord(value)) return null;
  const sessionId = asString(value.session_id);
  if (!sessionId) return null;
  return {
    ...value,
    session_id: sessionId,
    title: asString(value.title, "Untitled"),
  };
}

/** Narrow M08 list response; returns empty sessions when shape is unexpected. */
export function narrowSessionsListResponse(value: unknown): HermesSessionsListResponse {
  if (!isRecord(value) || !Array.isArray(value.sessions)) {
    return { sessions: [] };
  }
  const sessions = value.sessions
    .map((row) => narrowSessionSummary(row))
    .filter((row): row is HermesSessionSummary => row !== null);
  return {
    sessions,
    cli_count: typeof value.cli_count === "number" ? value.cli_count : undefined,
    all_profiles: typeof value.all_profiles === "boolean" ? value.all_profiles : undefined,
    active_profile: typeof value.active_profile === "string" ? value.active_profile : undefined,
    other_profile_count:
      typeof value.other_profile_count === "number" ? value.other_profile_count : undefined,
    server_time: typeof value.server_time === "number" ? value.server_time : undefined,
    server_tz: typeof value.server_tz === "string" ? value.server_tz : undefined,
  };
}

/** Narrow session detail envelope from unknown JSON (GET /session, POST /session/new). */
export function narrowSessionDetailResponse(value: unknown): HermesSessionDetailResponse | null {
  if (!isRecord(value) || !isRecord(value.session)) return null;
  const summary = narrowSessionSummary(value.session);
  if (!summary) return null;
  const messages = Array.isArray(value.session.messages)
    ? (value.session.messages.filter(isRecord) as HermesSessionMessage[])
    : undefined;
  const toolCalls = Array.isArray(value.session.tool_calls)
    ? value.session.tool_calls
    : undefined;
  return {
    session: {
      ...summary,
      ...value.session,
      session_id: summary.session_id,
      title: summary.title,
      messages,
      tool_calls: toolCalls,
    },
  };
}

/** Narrow M11 rename response. */
export function narrowSessionRenameResponse(value: unknown): HermesSessionRenameResponse | null {
  if (!isRecord(value) || !isRecord(value.session)) return null;
  const session = narrowSessionSummary(value.session);
  if (!session) return null;
  return { session };
}

/** Narrow M10 delete response (requires `ok: true`). */
export function narrowSessionDeleteResponse(value: unknown): HermesSessionDeleteResponse | null {
  if (!isRecord(value) || value.ok !== true) return null;
  return value as HermesSessionDeleteResponse;
}

/** Narrow M33 pin response. */
export function narrowSessionPinResponse(value: unknown): HermesSessionPinResponse | null {
  if (!isRecord(value) || value.ok !== true || !isRecord(value.session)) return null;
  const session = narrowSessionSummary(value.session);
  if (!session) return null;
  return { ok: true, session };
}

/** Narrow GET /sessions/search response. */
export function narrowSessionsSearchResponse(value: unknown): HermesSessionsSearchResponse {
  if (!isRecord(value) || !Array.isArray(value.sessions)) {
    return { sessions: [] };
  }
  const sessions: HermesSessionSearchResult[] = value.sessions
    .map((row) => {
      const summary = narrowSessionSummary(row);
      if (!summary) return null;
      const matchType =
        isRecord(row) && (row.match_type === "title" || row.match_type === "content")
          ? row.match_type
          : undefined;
      const matchPreview =
        isRecord(row) && typeof row.match_preview === "string"
          ? row.match_preview
          : undefined;
      return {
        ...summary,
        ...(matchType ? { match_type: matchType } : {}),
        ...(matchPreview ? { match_preview: matchPreview } : {}),
      };
    })
    .filter((row): row is HermesSessionSearchResult => row !== null);
  return {
    sessions,
    query: typeof value.query === "string" ? value.query : undefined,
    count: typeof value.count === "number" ? value.count : undefined,
  };
}

/**
 * M08 — `GET /api/v1/sessions` — list sidebar sessions.
 * Query: `all_profiles=1` when `allProfiles` is true.
 */
export async function listSessions(
  options: ListSessionsOptions = {},
): Promise<HermesSessionsListResponse> {
  const raw = await fetchJson<unknown>("/sessions", {
    query: buildListSessionsQuery(options),
  });
  return narrowSessionsListResponse(raw);
}

/**
 * GET /api/v1/session — load session detail and optional message history (M12).
 * Query: `session_id`, `messages`, `resolve_model`, `msg_limit`, `msg_before`.
 */
export async function getSession(
  sessionId: string,
  options: GetSessionOptions = {},
): Promise<HermesSessionDetailResponse> {
  const loadMessages = options.loadMessages ?? true;
  const resolveModel = options.resolveModel ?? loadMessages;
  const raw = await fetchJson<unknown>("/session", {
    query: {
      session_id: sessionId,
      messages: loadMessages ? "1" : "0",
      resolve_model: resolveModel ? "1" : "0",
      msg_limit: options.msgLimit,
      msg_before: options.msgBefore,
    },
  });
  const narrowed = narrowSessionDetailResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session detail response");
  }
  return narrowed;
}

/**
 * M09 — `POST /api/v1/session/new` — create a Hermes session.
 * Returns the full session envelope; use `createSessionId` for only `session_id`.
 */
export async function createSession(
  options: CreateSessionOptions = {},
): Promise<HermesSessionCreateResponse> {
  const raw = await fetchJson<unknown>("/session/new", {
    method: "POST",
    body: buildCreateSessionBody(options),
  });
  const narrowed = narrowSessionDetailResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session create response");
  }
  return narrowed;
}

/**
 * M09 convenience — create session and return only `session_id`.
 */
export async function createSessionId(
  options: CreateSessionOptions = {},
): Promise<string> {
  const response = await createSession(options);
  return sessionIdFromDetailResponse(response);
}

/**
 * `POST /api/v1/session/update` — update session workspace and/or model.
 */
export async function updateSession(
  sessionId: string,
  options: {
    workspace?: string;
    model?: string;
    modelProvider?: string | null;
  } = {},
): Promise<HermesSessionDetailResponse> {
  const raw = await fetchJson<unknown>("/session/update", {
    method: "POST",
    body: buildSessionUpdateBody(sessionId, options),
  });
  const narrowed = narrowSessionDetailResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session update response");
  }
  return narrowed;
}

/**
 * M11 — `POST /api/v1/session/rename` — persist a session title change.
 */
export async function renameSession(
  sessionId: string,
  title: string,
): Promise<HermesSessionRenameResponse> {
  const raw = await fetchJson<unknown>("/session/rename", {
    method: "POST",
    body: buildSessionRenameBody(sessionId, title),
  });
  const narrowed = narrowSessionRenameResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session rename response");
  }
  return narrowed;
}

/**
 * M15 — Derive a title from the first user message and persist via `POST /session/rename`.
 */
export async function renameSessionOnFirstMessage(
  sessionId: string,
  firstUserText: string,
): Promise<HermesSessionRenameResponse> {
  const trimmed = firstUserText.trim();
  const title = trimmed.length > 0 ? trimmed.substring(0, 30) : "Untitled";
  return renameSession(sessionId, title);
}

/**
 * M10 — `POST /api/v1/session/delete` — delete a session by id.
 */
export async function deleteSession(sessionId: string): Promise<HermesSessionDeleteResponse> {
  const raw = await fetchJson<unknown>("/session/delete", {
    method: "POST",
    body: buildSessionDeleteBody(sessionId),
  });
  const narrowed = narrowSessionDeleteResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session delete response");
  }
  return narrowed;
}

/**
 * List sidebar sessions and delete each one (settings "clear all history").
 */
export async function deleteAllSessions(): Promise<{ deleted: number; failed: number }> {
  const { sessions } = await listSessions();
  const ids = sessions
    .map((row) => row.session_id)
    .filter((id): id is string => Boolean(id) && !id.startsWith("suggestion-"));

  if (ids.length === 0) {
    return { deleted: 0, failed: 0 };
  }

  const results = await Promise.allSettled(ids.map((id) => deleteSession(id)));
  const failed = results.filter((result) => result.status === "rejected").length;
  return { deleted: ids.length - failed, failed };
}

/**
 * M33 — `POST /api/v1/session/pin` — pin or unpin a session.
 */
export async function pinSession(
  sessionId: string,
  pinned: boolean,
): Promise<HermesSessionPinResponse> {
  const raw = await fetchJson<unknown>("/session/pin", {
    method: "POST",
    body: buildSessionPinBody(sessionId, pinned),
  });
  const narrowed = narrowSessionPinResponse(raw);
  if (!narrowed) {
    throw new Error("Invalid session pin response");
  }
  return narrowed;
}

/**
 * M33 — `GET /api/v1/sessions/search` — search sessions by title and optional content.
 */
export async function searchSessions(
  options: SearchSessionsOptions = {},
): Promise<HermesSessionsSearchResponse> {
  const raw = await fetchJson<unknown>("/sessions/search", {
    query: {
      q: options.q ?? "",
      content: options.content === false ? "0" : "1",
      depth: options.depth ?? 5,
    },
  });
  return narrowSessionsSearchResponse(raw);
}

export {
  ensureServerSessionId,
  filterRejectedSessionIds,
  isSessionNotFoundError,
  pickFirstUsableSessionId,
} from "./sessionGuard";
