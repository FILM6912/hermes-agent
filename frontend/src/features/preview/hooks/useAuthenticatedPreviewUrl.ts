import { useEffect, useState } from "react";

import { fetchBlob, normalizeApiPath } from "@/lib/api";

export type AuthenticatedPreviewUrlState = "idle" | "loading" | "ready" | "error";

function parseHermesApiUrl(
  url: string,
): { path: string; query: Record<string, string> } | null {
  const trimmed = url.trim();
  if (!trimmed.startsWith("/api")) return null;

  const qIndex = trimmed.indexOf("?");
  const pathPart = qIndex >= 0 ? trimmed.slice(0, qIndex) : trimmed;
  const queryPart = qIndex >= 0 ? trimmed.slice(qIndex + 1) : "";
  const query: Record<string, string> = {};

  if (queryPart) {
    for (const [key, value] of new URLSearchParams(queryPart)) {
      query[key] = value;
    }
  }

  return { path: normalizeApiPath(pathPart), query };
}

function isDirectPreviewUrl(url: string): boolean {
  return (
    url.startsWith("blob:") ||
    url.startsWith("data:") ||
    url.startsWith("http://") ||
    url.startsWith("https://")
  );
}

/**
 * Resolve Hermes `/api/v1/file/raw` URLs to a blob URL with session cookies.
 * Non-API URLs pass through unchanged.
 */
export function useAuthenticatedPreviewUrl(
  sourceUrl: string | null | undefined,
): {
  url: string | null;
  state: AuthenticatedPreviewUrlState;
} {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<AuthenticatedPreviewUrlState>("idle");

  useEffect(() => {
    if (!sourceUrl) {
      setUrl(null);
      setState("idle");
      return;
    }

    if (sourceUrl.startsWith("blob:") || sourceUrl.startsWith("data:")) {
      setUrl(sourceUrl);
      setState("ready");
      return;
    }

    const apiRequest = parseHermesApiUrl(sourceUrl);
    if (!apiRequest) {
      setUrl(sourceUrl);
      setState("ready");
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;

    setUrl(null);
    setState("loading");

    void fetchBlob(apiRequest.path, { query: apiRequest.query })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setUrl(null);
          setState("error");
        }
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [sourceUrl]);

  return { url, state };
}

export { isDirectPreviewUrl, parseHermesApiUrl };
