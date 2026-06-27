import { useCallback, useEffect, useRef, useState } from "react";
import type { NavigateFunction } from "react-router-dom";
import type { ChatSession } from "@/types";
import {
  addConfirmedSessionId,
  removeConfirmedSessionId,
  removeSessionFromMap,
  updateSessionInMap,
  upsertSessionInMap,
  type SessionMap,
} from "@/stores/sessionState";

export type UseSessionStoreOptions = {
  /** Router navigate — used when rejecting the active session from a stale URL. */
  navigate?: NavigateFunction;
  /** Current `location.pathname` — keeps reject/navigation in sync with the URL. */
  pathname?: string;
};

export type SessionStore = {
  sessions: SessionMap;
  setSessions: React.Dispatch<React.SetStateAction<SessionMap>>;
  activeChatId: string;
  activeChatIdRef: React.MutableRefObject<string>;
  /** Updates React state and `activeChatIdRef` together (stream/effect safe reads). */
  setActiveChat: (id: string) => void;
  confirmedSessionIds: Set<string>;
  serverSessionIdsRef: React.MutableRefObject<Set<string>>;
  rejectedSessionIdsRef: React.MutableRefObject<Set<string>>;
  getSession: (id: string) => ChatSession | undefined;
  upsertSession: (id: string, session: ChatSession) => void;
  updateSession: (
    id: string,
    updater: (session: ChatSession) => ChatSession,
  ) => void;
  removeSession: (id: string) => void;
  resetSessions: () => void;
  confirmSessionId: (id: string) => void;
  unconfirmSessionId: (id: string) => void;
  syncConfirmedSessionIds: (ids: Set<string>) => void;
  clearRejectedSessionIds: () => void;
  rejectStaleSessionId: (missingId: string) => void;
};

/**
 * Session map + active chat id + server/rejected id guards (c5 PR1).
 * Streaming/send orchestration stays in App until PR2.
 */
export function useSessionStore(options: UseSessionStoreOptions = {}): SessionStore {
  const { navigate, pathname = "" } = options;

  const [sessions, setSessions] = useState<SessionMap>({});
  const [activeChatId, setActiveChatId] = useState("");
  const activeChatIdRef = useRef(activeChatId);

  useEffect(() => {
    activeChatIdRef.current = activeChatId;
  }, [activeChatId]);

  const setActiveChat = useCallback((id: string) => {
    activeChatIdRef.current = id;
    setActiveChatId(id);
  }, []);

  const rejectedSessionIdsRef = useRef<Set<string>>(new Set());
  const serverSessionIdsRef = useRef<Set<string>>(new Set());
  const [confirmedSessionIds, setConfirmedSessionIds] = useState<Set<string>>(
    () => new Set(),
  );

  const getSession = useCallback(
    (id: string) => sessions[id],
    [sessions],
  );

  const upsertSession = useCallback((id: string, session: ChatSession) => {
    setSessions((prev) => upsertSessionInMap(prev, id, session));
  }, []);

  const updateSession = useCallback(
    (id: string, updater: (session: ChatSession) => ChatSession) => {
      setSessions((prev) => updateSessionInMap(prev, id, updater));
    },
    [],
  );

  const removeSession = useCallback((id: string) => {
    setSessions((prev) => removeSessionFromMap(prev, id));
  }, []);

  const resetSessions = useCallback(() => {
    setSessions({});
  }, []);

  const syncConfirmedSessionIds = useCallback((ids: Set<string>) => {
    serverSessionIdsRef.current = ids;
    setConfirmedSessionIds(new Set(ids));
  }, []);

  const confirmSessionId = useCallback((id: string) => {
    serverSessionIdsRef.current.add(id);
    setConfirmedSessionIds((prev) => addConfirmedSessionId(prev, id));
  }, []);

  const unconfirmSessionId = useCallback((id: string) => {
    serverSessionIdsRef.current.delete(id);
    setConfirmedSessionIds((prev) => removeConfirmedSessionId(prev, id));
  }, []);

  const clearRejectedSessionIds = useCallback(() => {
    rejectedSessionIdsRef.current.clear();
  }, []);

  const rejectStaleSessionId = useCallback(
    (missingId: string) => {
      if (!missingId) return;
      rejectedSessionIdsRef.current.add(missingId);
      unconfirmSessionId(missingId);
      removeSession(missingId);
      if (activeChatIdRef.current === missingId) {
        setActiveChat("");
        if (pathname.match(/\/chat\/([^/]+)/)) {
          navigate?.("/chat", { replace: true });
        }
      }
    },
    [navigate, pathname, removeSession, setActiveChat, unconfirmSessionId],
  );

  return {
    sessions,
    setSessions,
    activeChatId,
    activeChatIdRef,
    setActiveChat,
    confirmedSessionIds,
    serverSessionIdsRef,
    rejectedSessionIdsRef,
    getSession,
    upsertSession,
    updateSession,
    removeSession,
    resetSessions,
    confirmSessionId,
    unconfirmSessionId,
    syncConfirmedSessionIds,
    clearRejectedSessionIds,
    rejectStaleSessionId,
  };
}
