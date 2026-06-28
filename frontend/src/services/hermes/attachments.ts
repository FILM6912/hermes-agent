/**
 * Chat attachment helpers — parity with static-legacy/messages.js upload handoff.
 */
import type { Attachment } from "@/types";
import { buildApiUrl } from "@/lib/api";
import { fileRawUrl } from "./workspace";

const ATTACHMENT_AT_SUFFIX_RE = /\n\n((?:@[^\s\n]+)(?:\s+@[^\s\n]+)*)\s*$/;
const LEGACY_ATTACHED_FILES_SUFFIX_RE = /\n\n\[Attached files: ([^\]]+)\]\s*$/;
const LEGACY_FILES_SUFFIX_RE = /\n\n_Files: [^_]+_\s*$/;
const INLINE_AT_PATH_RE = /(^|\s)@([^\s\n@]+)/g;
const UPLOAD_ONLY_BOILERPLATE_RE = /^I've uploaded \d+ file\(s\):\s*(.*)$/is;

function isPathLikeAtToken(path: string): boolean {
  const token = String(path || "").trim();
  if (!token) return false;
  if (token.startsWith(".") || token.startsWith("/") || token.startsWith("\\")) {
    return true;
  }
  if (token.includes("/") || token.includes("\\")) return true;
  if (/^[A-Za-z]:[\\/]/.test(token)) return true;
  return false;
}

function looksLikeUploadOnlyBoilerplate(text: string): boolean {
  const match = UPLOAD_ONLY_BOILERPLATE_RE.exec(String(text || "").trim());
  if (!match) return false;
  const rest = String(match[1] || "").trim();
  if (!rest) return true;
  const tokens = rest.split(/[\s,]+/).map((part) => part.trim()).filter(Boolean);
  if (!tokens.length) return true;
  return tokens.every((token) => {
    const bare = token.startsWith("@") ? token.slice(1) : token;
    if (token.startsWith("@") && isPathLikeAtToken(bare)) return true;
    return /^[\w.-]+$/.test(bare);
  });
}

/** @see static-legacy/sessions.js `_stripAttachedFilesMarker` */
export function stripAttachedFilesMarker(text: string): string {
  let next = String(text || "")
    .replace(ATTACHMENT_AT_SUFFIX_RE, "")
    .replace(LEGACY_ATTACHED_FILES_SUFFIX_RE, "")
    .replace(LEGACY_FILES_SUFFIX_RE, "")
    .trim();

  next = next.replace(INLINE_AT_PATH_RE, (match, lead, path) => {
    if (isPathLikeAtToken(path)) {
      return typeof lead === "string" && /\s/.test(lead) ? lead : "";
    }
    return match;
  });
  next = next.replace(/[ \t]{2,}/g, " ");
  next = next.replace(/\n{3,}/g, "\n\n").trim();
  if (looksLikeUploadOnlyBoilerplate(next)) return "";
  return next;
}

function attachmentPathsFromContentMarker(content: string): string[] {
  const raw = String(content || "");
  const atMatch = raw.match(ATTACHMENT_AT_SUFFIX_RE);
  if (atMatch) {
    return atMatch[1]
      .split(/\s+/)
      .map((token) => (token.startsWith("@") ? token.slice(1) : token))
      .filter(Boolean);
  }
  const legacyMatch = raw.match(LEGACY_ATTACHED_FILES_SUFFIX_RE);
  if (!legacyMatch) return [];
  return legacyMatch[1]
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Parse attachment paths from the agent-only suffix when session rows omit `attachments`. */
export function attachmentsFromContentMarker(content: string): Attachment[] | undefined {
  const paths = attachmentPathsFromContentMarker(content);
  if (!paths.length) return undefined;
  const attachments: Attachment[] = [];
  for (const path of paths) {
    const name = path.split(/[/\\]/).pop() || path;
    attachments.push({
      name,
      type: /\.(png|jpe?g|gif|webp|svg)$/i.test(name) ? "image" : "file",
      content: path,
      path,
    });
  }
  return attachments.length > 0 ? attachments : undefined;
}

/** Basename used for /file/raw lookup — prefer stored server path over display name. */
export function attachmentBasenameForLookup(attachment: Attachment): string {
  const raw = attachment.path?.trim() || attachment.content?.trim() || "";
  if (raw) {
    const base = raw.split(/[/\\]/).pop()?.trim();
    if (base) return base;
  }
  return attachment.name?.trim() || "";
}

/** Merge filename-only session rows with absolute paths from the agent suffix. */
export function mergeAttachmentsWithContentMarker(
  mapped: Attachment[] | undefined,
  rawContent: string,
): Attachment[] | undefined {
  const marker = attachmentsFromContentMarker(rawContent);
  if (!mapped?.length) return marker;
  if (!marker?.length) return mapped;
  return mapped.map((att, index) => {
    const base = attachmentBasenameForLookup(att).toLowerCase();
    const fromMarker =
      marker.find((m) => attachmentBasenameForLookup(m).toLowerCase() === base) ??
      marker[index];
    const markerPath = (fromMarker?.path || fromMarker?.content || "").trim();
    if (markerPath.includes("/") || markerPath.includes("\\")) {
      return {
        ...att,
        name: att.name || fromMarker?.name || attachmentBasenameForLookup(fromMarker),
        path: markerPath,
        content: markerPath,
      };
    }
    return att;
  });
}

/** Same-origin `/api/media` URL for an absolute attachment path on the server. */
export function attachmentMediaUrl(absPath: string): string {
  return buildApiUrl("/media", { path: absPath });
}

/** Image src for composer attachment chips (blob preview or API URL, never raw FS paths). */
export function composerAttachmentImageSrc(
  sessionId: string | undefined,
  attachment: Attachment,
  options?: AttachmentPreviewOptions,
): string {
  const preview = attachment.previewUrl?.trim();
  if (preview?.startsWith("blob:")) return preview;
  const content = attachment.content?.trim() || "";
  if (content.startsWith("blob:")) return content;
  return attachmentPreviewUrls(sessionId, attachment, options)[0] || "";
}

function attachmentHasServerPath(attachment: Attachment): boolean {
  const raw = attachment.path?.trim() || attachment.content?.trim() || "";
  if (!raw || raw.startsWith("blob:")) return false;
  return raw.includes("/") || raw.includes("\\");
}

type AttachmentPreviewOptions = {
  /** Composer workspace fallback when previewing without a session id. */
  workspace?: string;
};

function pushFileRawPreview(
  urls: string[],
  sessionId: string | undefined,
  path: string,
  options?: AttachmentPreviewOptions,
) {
  const workspace = options?.workspace?.trim();
  if (sessionId?.trim()) {
    urls.push(fileRawUrl(sessionId, path, { inline: true }));
    return;
  }
  if (workspace) {
    urls.push(
      fileRawUrl(undefined, path, { inline: true, workspace }),
    );
  }
}

/** Ordered preview URLs — stable API paths first, ephemeral blob previews last. */
export function attachmentPreviewUrls(
  sessionId: string | undefined,
  attachment: Attachment,
  options?: AttachmentPreviewOptions,
): string[] {
  const urls: string[] = [];
  const preview = attachment.previewUrl?.trim();
  const raw = attachment.path?.trim() || attachment.content?.trim() || "";
  const isAbsoluteServerPath = raw.startsWith("/") || /^[A-Za-z]:\\/.test(raw);

  const workspaceRel = attachment.workspace_rel?.trim();
  if (workspaceRel && !workspaceRel.startsWith("blob:")) {
    pushFileRawPreview(urls, sessionId, workspaceRel, options);
  }

  if (raw && !raw.startsWith("blob:")) {
    if (isAbsoluteServerPath) {
      pushFileRawPreview(urls, sessionId, raw, options);
      urls.push(attachmentMediaUrl(raw));
    } else if (!workspaceRel || raw !== workspaceRel) {
      const filename = attachmentBasenameForLookup(attachment);
      if (filename) {
        pushFileRawPreview(urls, sessionId, filename, options);
      }
    }
  } else if (raw && /^https?:\/\//i.test(raw)) {
    urls.push(raw);
  }

  if (preview?.startsWith("blob:")) {
    urls.push(preview);
  } else if (raw.startsWith("blob:")) {
    urls.push(raw);
  }

  return urls;
}

/** Keep local upload paths and blob previews when server rows only have filenames. */
export function mergeMessageAttachments(
  local?: Attachment[],
  server?: Attachment[],
): Attachment[] | undefined {
  if (!server?.length) return local?.length ? local : server;
  if (!local?.length) return server;

  return server.map((serverAtt, index) => {
    const localAtt =
      local.find(
        (candidate) =>
          candidate.name === serverAtt.name ||
          attachmentBasenameForLookup(candidate).toLowerCase() ===
            attachmentBasenameForLookup(serverAtt).toLowerCase(),
      ) ?? local[index];
    if (!localAtt) return serverAtt;

    const serverPath = (serverAtt.path || serverAtt.content || "").trim();
    const localPath = (localAtt.path || localAtt.content || "").trim();
    const serverHasPath = attachmentHasServerPath(serverAtt);
    const localHasPath = attachmentHasServerPath(localAtt);

    return {
      ...serverAtt,
      path: serverHasPath ? serverPath : localAtt.path || serverAtt.path,
      content: serverHasPath
        ? serverPath
        : localHasPath
          ? localPath
          : serverAtt.content || localAtt.content,
      previewUrl: localAtt.previewUrl || serverAtt.previewUrl,
      mimeType: serverAtt.mimeType || localAtt.mimeType,
      size: serverAtt.size ?? localAtt.size,
    };
  });
}

/** Primary preview URL (first candidate). */
export function resolveAttachmentDisplayUrl(
  sessionId: string | undefined,
  attachment: Attachment,
  options?: AttachmentPreviewOptions,
): string {
  return attachmentPreviewUrls(sessionId, attachment, options)[0] || "";
}
/** Agent-facing path for chat attachment context (prefer workspace `.uploads/` rel). */
export function attachmentAgentPath(att: Attachment): string {
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

export function attachmentPathsForChat(attachments?: Attachment[]): string[] {
  if (!attachments?.length) return [];
  return attachments.map((att) => attachmentAgentPath(att)).filter(Boolean);
}

/** Composer-style ``@path`` token for agent-facing attachment hints. */
export function attachmentAtToken(path: string): string {
  const token = String(path || "").trim();
  if (!token) return "";
  return token.startsWith("@") ? token : `@${token}`;
}

/**
 * Append ``@path`` tokens so uploads are visible to the agent like composer @-mentions.
 * @see static-legacy/messages.js (uploadedPaths + msgText suffix)
 */
export function formatChatMessageWithAttachments(
  message: string,
  attachments?: Attachment[],
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
