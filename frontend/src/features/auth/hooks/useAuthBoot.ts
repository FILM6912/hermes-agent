import { useCallback, useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { AUTH_REFRESH_EVENT } from "../authRefresh";
import {
  getAuthStatus,
  isShellAuthenticated,
  type AuthLoginResponse,
  type AuthStatus,
} from "../services/authService";

export interface UseAuthBootResult {
  /** True after the first status probe finishes (success or failure). */
  ready: boolean;
  status: AuthStatus | null;
  /** `true` when auth is off or the session cookie is valid. */
  isAuthenticated: boolean;
  error: Error | null;
  /** Re-run `GET /api/v1/auth/status` (e.g. after login/logout). */
  refresh: () => Promise<AuthStatus | null>;
  /** After password/passkey login — probe session via cookie or bearer token. */
  establishSession: (login?: AuthLoginResponse) => Promise<AuthStatus | null>;
}

/**
 * Hermes auth boot probe for App shell integration (M01 / M33).
 * Does not navigate — callers decide redirect vs login route.
 */
export function useAuthBoot(): UseAuthBootResult {
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const applyStatus = useCallback((next: AuthStatus | null) => {
    flushSync(() => {
      setStatus(next);
      if (next) setError(null);
      setReady(true);
    });
    return next;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await getAuthStatus();
      return applyStatus(next);
    } catch (err) {
      flushSync(() => {
        setStatus(null);
        setError(err instanceof Error ? err : new Error(String(err)));
        setReady(true);
      });
      return null;
    }
  }, [applyStatus]);

  const establishSession = useCallback(
    async (_login?: AuthLoginResponse) => refresh(),
    [refresh],
  );

  useEffect(() => {
    const onRefresh = () => {
      void refresh();
    };
    window.addEventListener(AUTH_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(AUTH_REFRESH_EVENT, onRefresh);
  }, [refresh]);

  useEffect(() => {
    let cancelled = false;
    getAuthStatus()
      .then((next) => {
        if (!cancelled) {
          setStatus(next);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setStatus(null);
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    ready,
    status,
    isAuthenticated: status ? isShellAuthenticated(status) : false,
    error,
    refresh,
    establishSession,
  };
}
