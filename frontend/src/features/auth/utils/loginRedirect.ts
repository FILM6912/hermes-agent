/** HashRouter-safe post-login navigation (server may use /login?next= pathname). */

import { getAccessToken } from "@/lib/api";

/** FastAPI/OpenAPI paths are server routes, not HashRouter SPA routes. */
const FULL_PAGE_PATHS = new Set(["/docs", "/redoc", "/openapi.json"]);

const FULL_PAGE_REDIRECT_GUARD_KEY = "hermes_full_page_redirect_guard";
const FULL_PAGE_REDIRECT_GUARD_MS = 4000;

export function isFullPageRedirectPath(raw: string | null | undefined): boolean {
  const token = (raw ?? "").trim();
  if (!token.startsWith("/") || token.startsWith("//")) return false;
  const pathOnly = token.split("?")[0]?.split("#")[0] ?? "";
  return FULL_PAGE_PATHS.has(pathOnly);
}

/** Attach session token for server routes (navigation cannot send Authorization header). */
export function buildFullPageRedirectUrl(path: string): string {
  const normalized = safeAppPath(path, "/");
  if (typeof window === "undefined") return normalized;
  const token = getAccessToken();
  if (!token) return normalized;
  const url = new URL(normalized, window.location.origin);
  url.searchParams.set("access_token", token);
  return `${url.pathname}${url.search}`;
}

/** Navigate to a server-only path; returns false when a redirect loop is detected. */
export function navigateToFullPagePath(
  path: string,
  method: "assign" | "replace" = "assign",
): boolean {
  if (typeof window === "undefined") return false;
  const pathOnly = safeAppPath(path, "/");
  const now = Date.now();
  try {
    const prev = window.sessionStorage.getItem(FULL_PAGE_REDIRECT_GUARD_KEY);
    if (prev) {
      const [prevPath, prevTs] = prev.split(":");
      if (prevPath === pathOnly && now - Number(prevTs) < FULL_PAGE_REDIRECT_GUARD_MS) {
        return false;
      }
    }
    window.sessionStorage.setItem(FULL_PAGE_REDIRECT_GUARD_KEY, `${pathOnly}:${now}`);
  } catch {
    /* ignore storage failures */
  }
  const url = buildFullPageRedirectUrl(pathOnly);
  if (method === "replace") {
    window.location.replace(url);
  } else {
    window.location.assign(url);
  }
  return true;
}

export function safeAppPath(raw: string | null | undefined, fallback = "/chat"): string {
  const token = (raw ?? "").trim();
  if (!token || !token.startsWith("/") || token.startsWith("//")) return fallback;
  if (token.startsWith("/#/")) return token.slice(2) || fallback;
  if (token.startsWith("/#")) return token.slice(2) || fallback;
  const pathOnly = token.split("#")[0] ?? "";
  return pathOnly.startsWith("/") ? pathOnly : fallback;
}

/** Read ?next= from hash or legacy pathname query after login. */
export function resolvePostLoginPath(
  location: Pick<Location, "search" | "hash"> = window.location,
): string {
  const hash = location.hash ?? "";
  if (hash.includes("?")) {
    const qs = hash.slice(hash.indexOf("?") + 1);
    const fromHash = new URLSearchParams(qs).get("next");
    if (fromHash) return safeAppPath(fromHash);
  }

  const fromSearch = new URLSearchParams(location.search).get("next");
  if (fromSearch) return safeAppPath(fromSearch);

  return "/chat";
}

/** Rewrite legacy ``/login?next=`` URLs to ``/#/login?next=`` for HashRouter. */
export function normalizeLegacyLoginUrl(): void {
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (pathname !== "/login" && pathname !== "/register") return;

  const params = new URLSearchParams(search);
  const next = params.get("next");
  const loginRoute = pathname === "/register" ? "/register" : "/login";
  const query = next
    ? `?next=${encodeURIComponent(safeAppPath(next))}`
    : "";
  window.history.replaceState(null, "", `/#${loginRoute}${query}`);
}
