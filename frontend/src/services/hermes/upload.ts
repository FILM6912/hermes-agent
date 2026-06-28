/**
 * Hermes chat attachment upload API (M22).
 * POST /api/v1/upload — multipart inbox with CSRF.
 */
import { getCsrfToken, HermesApiError, normalizeApiPath } from "@/lib/api";

/** Response from POST /api/v1/upload (`app/domain/upload.py`). */
export type HermesUploadResponse = {
  filename: string;
  path: string;
  size: number;
  mime: string;
  is_image: boolean;
  /** Workspace-relative path when stored under `.uploads/` (e.g. `.uploads/file.xlsx`). */
  workspace_rel?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/** Narrow upload JSON to typed response. */
export function narrowUploadResponse(value: unknown): HermesUploadResponse | null {
  if (!isRecord(value)) return null;
  const filename = asString(value.filename);
  const path = asString(value.path);
  if (!filename || !path) return null;
  const workspaceRel = asString(value.workspace_rel);
  return {
    filename,
    path,
    size: typeof value.size === "number" ? value.size : 0,
    mime: asString(value.mime, "application/octet-stream"),
    is_image: value.is_image === true,
    ...(workspaceRel ? { workspace_rel: workspaceRel } : {}),
  };
}

export type UploadFileOptions = {
  /** Active composer workspace — stores the file under the account main `<workspace>/.uploads/`. */
  workspace?: string;
};

/** POST /api/v1/upload — attach a file to the account main workspace `.uploads/` dir. */
export async function uploadFile(
  sessionId: string,
  file: File,
  options?: UploadFileOptions,
): Promise<HermesUploadResponse> {
  const formData = new FormData();
  formData.append("session_id", sessionId);
  const workspace = options?.workspace?.trim();
  if (workspace) {
    formData.append("workspace", workspace);
  }
  formData.append("file", file);

  const url = normalizeApiPath("/upload");
  const headers = new Headers();
  const token = getCsrfToken();
  if (token) headers.set("X-Hermes-CSRF-Token", token);

  const response = await fetch(url, {
    method: "POST",
    headers,
    credentials: "include",
    body: formData,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const parsed = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (!response.ok) {
    const message =
      (isRecord(parsed) && asString(parsed.error)) ||
      (isRecord(parsed) && asString(parsed.detail)) ||
      (typeof parsed === "string" && parsed) ||
      `HTTP ${response.status}`;
    throw new HermesApiError(message, response.status, parsed);
  }

  const narrowed = narrowUploadResponse(parsed);
  if (!narrowed) {
    throw new Error("Invalid upload response");
  }
  return narrowed;
}
