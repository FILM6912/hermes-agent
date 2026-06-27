import { fetchJson } from "@/lib/api";
import type { AuthStatus } from "@/features/auth/services/authService";
import { roleHasPermission } from "@/features/admin/rolesApi";

export type MemorySection = "memory" | "user" | "soul";

export interface MemoryPayload {
  memory: string;
  user: string;
  soul?: string;
  memory_mtime?: number | null;
  user_mtime?: number | null;
  soul_mtime?: number | null;
  external_notes_enabled?: boolean;
}

export interface NotesSource {
  name: string;
  label?: string;
  active?: boolean;
  status?: string;
  tool_count?: number;
  tools?: Array<{ name?: string; description?: string }>;
  tool_source?: string;
}

export interface NotesSourcesResponse {
  enabled?: boolean;
  sources?: NotesSource[];
  automatic_recall_unchanged?: boolean;
  recent_ai_notes?: Array<{
    id?: string;
    source?: string;
    title?: string;
    label?: string;
    updated_time?: number;
  }>;
  error?: string;
}

export interface NotesSearchResult {
  id?: string;
  title?: string;
  snippet?: string;
  source?: string;
}

export interface NotesSearchResponse {
  source: string;
  query?: string;
  results: NotesSearchResult[];
  error?: string;
}

export interface NotesItemResponse {
  source: string;
  note?: {
    id?: string;
    title?: string;
    body?: string;
    source?: string;
  };
  error?: string;
}

/** Agent Soul tab when multi-user mode is on. */
export function canAccessAgentSoul(auth: AuthStatus | null): boolean {
  if (!auth?.multi_user) return true;
  return roleHasPermission(auth.permissions, "agent_soul:access");
}

/** GET /api/v1/memory */
export async function fetchMemory(): Promise<MemoryPayload> {
  return fetchJson<MemoryPayload>("/memory");
}

/** POST /api/v1/memory/write */
export async function writeMemory(
  section: MemorySection,
  content: string,
): Promise<{ ok: boolean; section: string }> {
  return fetchJson("/memory/write", {
    method: "POST",
    body: { section, content },
  });
}

/** GET /api/v1/notes/sources */
export async function fetchNotesSources(): Promise<NotesSourcesResponse> {
  return fetchJson<NotesSourcesResponse>("/notes/sources");
}

/** GET /api/v1/notes/search */
export async function searchNotes(params: {
  source: string;
  q: string;
  limit?: number;
}): Promise<NotesSearchResponse> {
  return fetchJson<NotesSearchResponse>("/notes/search", {
    query: {
      source: params.source,
      q: params.q,
      limit: params.limit ?? 20,
    },
  });
}

/** GET /api/v1/notes/item */
export async function fetchNotesItem(params: {
  source: string;
  id: string;
}): Promise<NotesItemResponse> {
  return fetchJson<NotesItemResponse>("/notes/item", {
    query: { source: params.source, id: params.id },
  });
}

export function memorySectionContent(data: MemoryPayload, section: MemorySection): string {
  if (section === "user") return data.user || "";
  if (section === "soul") return data.soul || "";
  return data.memory || "";
}

export function memorySectionMtime(data: MemoryPayload, section: MemorySection): number | null {
  if (section === "user") return data.user_mtime ?? null;
  if (section === "soul") return data.soul_mtime ?? null;
  return data.memory_mtime ?? null;
}
