export function composerAttachmentImageSrc(_sessionId: string | undefined, file: { path?: string }, _opts?: Record<string, unknown>) {
  return file.path ?? "";
}

export function attachmentPreviewUrls(): string[] {
  return [];
}

export function resolveAttachmentDisplayUrl(_attachment: { path?: string; content?: string }) {
  return "";
}

export function stripAttachedFilesMarker(text: string): string {
  return text;
}

/** Agent-facing path for chat attachment context (prefer workspace `.uploads/` rel). */
export function attachmentAgentPath(att: {
  workspace_rel?: string;
  path?: string;
  content?: string;
  name?: string;
}): string {
  const workspaceRel = att.workspace_rel?.trim();
  if (workspaceRel) return workspaceRel;
  const raw = att.path?.trim() || att.content?.trim() || "";
  const marker = "/.uploads/";
  const idx = raw.indexOf(marker);
  if (idx >= 0) {
    return raw.slice(idx + 1);
  }
  return att.path?.trim() || att.content?.trim() || att.name?.trim() || "";
}

export function attachmentPathsForChat(
  attachments?: Array<{ workspace_rel?: string; path?: string; content?: string; name?: string }>,
): string[] {
  if (!attachments?.length) return [];
  return attachments.map((att) => attachmentAgentPath(att)).filter(Boolean);
}

export function attachmentAtToken(path: string): string {
  const token = String(path || "").trim();
  if (!token) return "";
  return token.startsWith("@") ? token : `@${token}`;
}

/** Append `@path` tokens so uploads are visible to the agent like composer @-mentions. */
export function formatChatMessageWithAttachments(
  message: string,
  attachments?: Array<{ workspace_rel?: string; path?: string; content?: string; name?: string }>,
): string {
  const paths = attachmentPathsForChat(attachments);
  if (!paths.length) return message;

  const tokens = paths.map((path) => attachmentAtToken(path));
  const trimmed = message.trim();
  if (!trimmed) {
    return `I've uploaded ${paths.length} file(s): ${tokens.join(" ")}`;
  }
  return `${trimmed}\n\n${tokens.join(" ")}`;
}
