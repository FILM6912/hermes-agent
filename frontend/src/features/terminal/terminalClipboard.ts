import { copyTextToClipboard, readTextFromClipboard } from "@/lib/clipboard";
import type { XtermTerminal } from "./loadXterm";

export function normalizeTerminalPaste(text: string): string {
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

export function setupTerminalClipboard(
  term: XtermTerminal,
  surface: HTMLElement,
  handlers: {
    onPaste: (text: string) => void;
    onPasteBlocked: () => void;
  },
): () => void {
  const pasteFromClipboard = () => {
    void readTextFromClipboard().then((text) => {
      const value = normalizeTerminalPaste(text);
      if (value) handlers.onPaste(value);
      else handlers.onPasteBlocked();
    });
  };

  term.attachCustomKeyEventHandler?.((event: KeyboardEvent) => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) {
      if (event.shiftKey && event.key === "Insert") {
        event.preventDefault();
        pasteFromClipboard();
        return false;
      }
      return true;
    }

    const key = event.key.toLowerCase();

    if (key === "v" || (event.shiftKey && key === "v")) {
      event.preventDefault();
      pasteFromClipboard();
      return false;
    }

    if (key === "c" && term.hasSelection?.()) {
      event.preventDefault();
      const selection = term.getSelection?.() ?? "";
      if (selection) void copyTextToClipboard(selection);
      return false;
    }

    if (event.shiftKey && key === "c" && term.hasSelection?.()) {
      event.preventDefault();
      const selection = term.getSelection?.() ?? "";
      if (selection) void copyTextToClipboard(selection);
      return false;
    }

    return true;
  });

  const onContextMenu = (event: MouseEvent) => {
    event.preventDefault();
    pasteFromClipboard();
  };
  surface.addEventListener("contextmenu", onContextMenu);

  return () => {
    surface.removeEventListener("contextmenu", onContextMenu);
  };
}
