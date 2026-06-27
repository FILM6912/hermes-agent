/** Copy text with Clipboard API on secure contexts, execCommand fallback elsewhere (legacy parity). */

export async function copyTextToClipboard(text: string): Promise<boolean> {
  const value = String(text ?? "");
  if (!value) return false;

  if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // Fall through to execCommand (common on http://192.168.x.x LAN access).
    }
  }

  return fallbackCopyText(value);
}

function fallbackCopyText(text: string): boolean {
  if (typeof document === "undefined") return false;
  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.cssText =
      "position:fixed;left:0;top:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent;z-index:-1";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textArea);
    return ok;
  } catch {
    return false;
  }
}

/** Read clipboard text when permitted (secure context + user gesture). */
export async function readTextFromClipboard(): Promise<string> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.readText && window.isSecureContext) {
    try {
      return await navigator.clipboard.readText();
    } catch {
      // Fall through to execCommand / manual paste UI.
    }
  }
  return fallbackReadTextFromClipboard();
}

export function isClipboardPasteBlocked(): boolean {
  return typeof window !== "undefined" && !window.isSecureContext;
}

function fallbackReadTextFromClipboard(): string {
  if (typeof document === "undefined") return "";
  try {
    const textArea = document.createElement("textarea");
    textArea.setAttribute("autocomplete", "off");
    textArea.setAttribute("autocapitalize", "off");
    textArea.setAttribute("spellcheck", "false");
    textArea.style.cssText =
      "position:fixed;left:0;top:0;width:2em;height:2em;padding:0;border:none;outline:none;opacity:0;z-index:-1";
    document.body.appendChild(textArea);
    textArea.focus();
    const ok = document.execCommand("paste");
    const value = ok ? textArea.value : "";
    document.body.removeChild(textArea);
    return value;
  } catch {
    return "";
  }
}
