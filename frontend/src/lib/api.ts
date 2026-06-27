/**
 * Hermes WebUI HTTP client — same-origin `/api/v1/*`, CSRF, credentials.
 * Mirrors conventions from `static/index.html` fetch wrapper.
 */

export type HermesConfig = {
  maxUploadBytes?: number;
  csrfToken?: string;
  accessToken?: string;
};

declare global {
  interface Window {
    __HERMES_CONFIG__?: HermesConfig;
  }
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Paths that must not receive CSRF (login sets cookie; CSP sink). */
const CSRF_EXEMPT = /^\/api\/v1\/(auth\/login|csp-report)(?:\/|$)/;

export class HermesApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown = undefined) {
    super(message);
    this.name = "HermesApiError";
    this.status = status;
    this.body = body;
  }
}

export function getHermesConfig(): HermesConfig {
  if (typeof window !== "undefined" && window.__HERMES_CONFIG__) {
    return window.__HERMES_CONFIG__;
  }
  return {};
}

export function setCsrfToken(token: string): void {
  if (typeof window === "undefined") return;
  window.__HERMES_CONFIG__ = { ...getHermesConfig(), csrfToken: token };
}

export function getCsrfToken(): string {
  return getHermesConfig().csrfToken?.trim() ?? "";
}

/** Survives full page reload when HttpOnly cookies are blocked (Bearer fallback). */
const ACCESS_TOKEN_STORAGE_KEY = "hermes_webui_access_token";

function readStoredAccessToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY)?.trim() ?? "";
  } catch {
    return "";
  }
}

function writeStoredAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
    } else {
      window.sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    }
  } catch {
    /* private browsing / storage quota */
  }
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  const trimmed = token.trim();
  window.__HERMES_CONFIG__ = { ...getHermesConfig(), accessToken: trimmed };
  writeStoredAccessToken(trimmed);
}

export function getAccessToken(): string {
  const fromMemory = getHermesConfig().accessToken?.trim() ?? "";
  if (fromMemory) return fromMemory;
  const fromStorage = readStoredAccessToken();
  if (fromStorage) {
    window.__HERMES_CONFIG__ = { ...getHermesConfig(), accessToken: fromStorage };
  }
  return fromStorage;
}

if (typeof window !== "undefined") {
  const storedAccessToken = readStoredAccessToken();
  if (storedAccessToken) {
    window.__HERMES_CONFIG__ = { ...getHermesConfig(), accessToken: storedAccessToken };
  }
}

/**
 * Normalize API paths to `/api/v1/...` (idempotent).
 * Accepts `sessions`, `/sessions`, `/api/sessions`, `/api/v1/sessions`.
 */
export function normalizeApiPath(path: string): string {
  let p = path.trim();
  if (!p) return "/api/v1";
  if (!p.startsWith("/")) p = `/${p}`;
  if (p.startsWith("/api/v1/") || p === "/api/v1") return p;
  if (p.startsWith("/api/")) {
    const rest = p.slice("/api/".length);
    if (rest.startsWith("v1/")) return `/api/${rest}`;
    return `/api/v1/${rest}`;
  }
  return `/api/v1${p}`;
}

function urlBase(): string {
  if (typeof document !== "undefined" && document.baseURI) return document.baseURI;
  if (typeof window !== "undefined") return window.location.href;
  return "http://localhost/";
}

/** Auth endpoints that may return 401 during boot — never trigger redirect. */
const AUTH_NO_REDIRECT_PATHS =
  /^\/api\/v1\/auth\/(?:status|login|logout|passkey|register)(?:\/|$)/;

function currentAppPath(): string {
  if (typeof window === "undefined") return "/";
  const pathname = window.location.pathname || "/";
  if (/^\/(?:login|register)(?:\/|$)/.test(pathname)) return pathname;
  const hash = window.location.hash;
  if (hash.startsWith("#/")) {
    const hashPath = hash.slice(1).split("?")[0] ?? "/";
    return hashPath.startsWith("/") ? hashPath : `/${hashPath}`;
  }
  return pathname;
}

function isOnAuthPage(): boolean {
  return /^\/(?:login|register)(?:\/|$)/.test(currentAppPath());
}

/** Redirect only from protected app shell routes, not login or auth probes. */
function shouldRedirectOn401(apiPathname: string): boolean {
  if (AUTH_NO_REDIRECT_PATHS.test(apiPathname)) return false;
  if (isOnAuthPage()) return false;
  return true;
}

function redirectToLogin(): void {
  const next = encodeURIComponent(currentAppPath());
  // HashRouter: always use /#/login — never compound legacy /login?next= pathname URLs.
  window.location.href = `/#/login?next=${next}`;
}

/** Same-origin Hermes API URL (relative path + query). Works on any host/IP the UI is served from. */
export function buildApiUrl(
  path: string,
  query?: Record<string, string | number | boolean | undefined | null>,
): string {
  return buildUrl(path, query);
}

function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined | null>): string {
  const normalized = normalizeApiPath(path);
  const rel = normalized.startsWith("/") ? normalized.slice(1) : normalized;
  const url = new URL(rel, urlBase());
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.pathname + url.search;
}

function needsCsrf(method: string, pathname: string): boolean {
  const m = method.toUpperCase();
  if (!UNSAFE_METHODS.has(m)) return false;
  return !CSRF_EXEMPT.test(pathname);
}

export type FetchJsonOptions = Omit<RequestInit, "body"> & {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
};

function applyAuthHeaders(headers: Headers, method: string, pathname: string): void {
  const token = getCsrfToken();
  if (token && needsCsrf(method, pathname) && !headers.has("X-Hermes-CSRF-Token")) {
    headers.set("X-Hermes-CSRF-Token", token);
  }
  const accessToken = getAccessToken();
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
}

/**
 * JSON fetch against Hermes API with credentials and CSRF on mutating requests.
 */
export async function fetchJson<T = unknown>(
  path: string,
  options: FetchJsonOptions = {},
): Promise<T> {
  const { query, body, headers: initHeaders, ...rest } = options;
  const url = buildUrl(path, query);
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(initHeaders);

  if (body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const pathname = new URL(url.startsWith("/") ? url.slice(1) : url, urlBase()).pathname;
  applyAuthHeaders(headers, method, pathname);

  const response = await fetch(url, {
    ...rest,
    method,
    headers,
    credentials: rest.credentials ?? "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const parsed = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (response.status === 401) {
    const message =
      (parsed && typeof parsed === "object" && "error" in parsed && String((parsed as { error: unknown }).error)) ||
      (parsed && typeof parsed === "object" && "detail" in parsed && String((parsed as { detail: unknown }).detail)) ||
      (typeof parsed === "string" && parsed) ||
      "Unauthorized";
    if (shouldRedirectOn401(pathname)) {
      redirectToLogin();
    }
    throw new HermesApiError(message, response.status, parsed);
  }

  if (!response.ok) {
    const message =
      (parsed && typeof parsed === "object" && "error" in parsed && String((parsed as { error: unknown }).error)) ||
      (parsed && typeof parsed === "object" && "detail" in parsed && String((parsed as { detail: unknown }).detail)) ||
      (typeof parsed === "string" && parsed) ||
      `HTTP ${response.status}`;
    throw new HermesApiError(message, response.status, parsed);
  }

  return parsed as T;
}

export type FetchBlobOptions = Omit<RequestInit, "body"> & {
  query?: Record<string, string | number | boolean | undefined | null>;
};

/** Binary fetch (e.g. `GET /file/raw`) with credentials and CSRF on mutating methods. */
export async function fetchBlob(
  path: string,
  options: FetchBlobOptions = {},
): Promise<Blob> {
  const { query, headers: initHeaders, ...rest } = options;
  const url = buildUrl(path, query);
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(initHeaders);

  const pathname = new URL(url.startsWith("/") ? url.slice(1) : url, urlBase()).pathname;
  applyAuthHeaders(headers, method, pathname);

  const response = await fetch(url, {
    ...rest,
    method,
    headers,
    credentials: rest.credentials ?? "include",
  });

  if (response.status === 401) {
    if (shouldRedirectOn401(pathname)) {
      redirectToLogin();
    }
    throw new HermesApiError("Unauthorized", response.status);
  }

  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? "";
    const isJson = contentType.includes("application/json");
    const parsed = isJson
      ? await response.json().catch(() => null)
      : await response.text().catch(() => "");
    const message =
      (parsed && typeof parsed === "object" && "error" in parsed && String((parsed as { error: unknown }).error)) ||
      (parsed && typeof parsed === "object" && "detail" in parsed && String((parsed as { detail: unknown }).detail)) ||
      (typeof parsed === "string" && parsed) ||
      `HTTP ${response.status}`;
    throw new HermesApiError(message, response.status, parsed);
  }

  return response.blob();
}

/** Open an EventSource on a normalized Hermes path (SSE). */
export function openEventSource(
  path: string,
  query?: Record<string, string | number | boolean | undefined | null>,
): EventSource {
  const merged: Record<string, string | number | boolean | undefined | null> = {
    ...(query ?? {}),
  };
  const accessToken = getAccessToken();
  if (
    accessToken &&
    merged.access_token == null &&
    merged.token == null
  ) {
    merged.access_token = accessToken;
  }
  const url = buildUrl(path, merged);
  return new EventSource(url, { withCredentials: true });
}
