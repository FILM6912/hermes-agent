/** Strip agent ``MEDIA:`` tokens from user-visible assistant markdown. */

const MEDIA_TOKEN_RE = /MEDIA:([^\s\)\]]+)/g;
const MEDIA_ONLY_LINE_RE = /^\s*MEDIA:[^\s\)\]]+\s*$/gm;

function mediaBasename(ref: string): string {
  const trimmed = ref.trim();
  if (!trimmed) return "file";
  const parts = trimmed.split(/[/\\]/);
  return parts[parts.length - 1] || trimmed;
}

/**
 * Remove standalone ``MEDIA:`` lines and rewrite inline tokens to a plain
 * filename mention (no ``MEDIA:`` prefix, no virtual path leak).
 */
export function stripMediaTokens(text: string): string {
  let next = text.replace(MEDIA_ONLY_LINE_RE, "");
  next = next.replace(MEDIA_TOKEN_RE, (_match, ref: string) => {
    const name = mediaBasename(ref);
    return name ? `📎 ${name}` : "";
  });
  return next.replace(/\n{3,}/g, "\n\n").trim();
}
