/** Load xterm + fit addon from CDN (same versions as Hermes legacy shell). */

declare global {
  interface Window {
    Terminal?: new (options?: Record<string, unknown>) => XtermTerminal;
    FitAddon?: { FitAddon: new () => XtermFitAddon };
  }
}

export interface XtermFitAddon {
  fit: () => void;
}

export interface XtermTerminal {
  cols: number;
  rows: number;
  open: (parent: HTMLElement) => void;
  write: (data: string) => void;
  writeln: (data: string) => void;
  focus: () => void;
  dispose: () => void;
  onData: (cb: (data: string) => void) => void;
  loadAddon: (addon: XtermFitAddon) => void;
  options: { theme?: Record<string, string> };
  attachCustomKeyEventHandler?: (handler: (event: KeyboardEvent) => boolean) => void;
  hasSelection?: () => boolean;
  getSelection?: () => string;
}

const XTERM_CSS =
  "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css";
const XTERM_JS =
  "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js";
const FIT_JS =
  "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js";

let loadPromise: Promise<void> | null = null;

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.getAttribute("data-loaded") === "1") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)));
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.crossOrigin = "anonymous";
    script.defer = true;
    script.addEventListener("load", () => {
      script.setAttribute("data-loaded", "1");
      resolve();
    });
    script.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)));
    document.head.appendChild(script);
  });
}

function loadStylesheet(href: string): void {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.crossOrigin = "anonymous";
  document.head.appendChild(link);
}

export async function ensureXtermLoaded(): Promise<void> {
  if (typeof window !== "undefined" && window.Terminal) return;
  if (!loadPromise) {
    loadPromise = (async () => {
      loadStylesheet(XTERM_CSS);
      await loadScript(XTERM_JS);
      await loadScript(FIT_JS);
      if (!window.Terminal) {
        throw new Error("xterm.js failed to initialize");
      }
    })();
  }
  await loadPromise;
}

export function terminalTheme(): Record<string, string> {
  const isDark = document.documentElement.classList.contains("dark");
  const read = (name: string, fallback: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const background = read("--code-bg", isDark ? "#1A1A2E" : "#F5F0E5");
  const foreground = read("--pre-text", isDark ? "#E2E8F0" : "#1A1610");
  const accent = read("--accent-text", isDark ? "#FFD700" : "#8B6508");
  return {
    background,
    foreground,
    cursor: accent,
    selectionBackground: isDark ? "rgba(255,215,0,.18)" : "rgba(184,134,11,.18)",
    black: isDark ? "#0D0D1A" : "#1A1610",
    red: read("--error", "#C62828"),
    green: read("--success", "#3D8B40"),
    yellow: read("--warning", "#E68A00"),
    blue: read("--info", "#0288A8"),
    magenta: accent,
    cyan: read("--info", "#0288A8"),
    white: foreground,
    brightBlack: read("--muted", isDark ? "#C0C0C0" : "#5C5344"),
    brightRed: read("--error", "#C62828"),
    brightGreen: read("--success", "#3D8B40"),
    brightYellow: accent,
    brightBlue: read("--info", "#0288A8"),
    brightMagenta: accent,
    brightCyan: read("--info", "#0288A8"),
    brightWhite: isDark ? "#FFFFFF" : "#0F0D08",
  };
}

export function createTerminal(surface: HTMLElement): {
  term: XtermTerminal;
  fitAddon: XtermFitAddon | null;
} {
  const Terminal = window.Terminal;
  if (!Terminal) throw new Error("xterm is not loaded");
  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: 'Menlo, Monaco, Consolas, "Liberation Mono", monospace',
    scrollback: 1000,
    convertEol: false,
    theme: terminalTheme(),
  });
  let fitAddon: XtermFitAddon | null = null;
  if (window.FitAddon?.FitAddon) {
    fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
  }
  term.open(surface);
  return { term, fitAddon };
}
