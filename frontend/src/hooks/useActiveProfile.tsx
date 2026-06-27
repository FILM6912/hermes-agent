import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { deriveAuthRole } from "@/features/auth/hooks/useAuthRole";
import { useAuthBoot } from "@/features/auth/hooks/useAuthBoot";
import {
  HermesProfileSummary,
  HermesProfileSwitchResponse,
  boundProfileSummaries,
  listProfiles,
  switchProfile,
} from "@/services/hermes/profiles";

export type ActiveProfileContextValue = {
  /** Current active Hermes profile name (defaults to `"default"`). */
  activeProfile: string;
  profiles: HermesProfileSummary[];
  loading: boolean;
  switching: string | null;
  error: string | null;
  /** Switch active profile via POST /profile/switch and update shared state. */
  setActiveProfile: (name: string) => Promise<HermesProfileSwitchResponse>;
  /** Reload profile list and active name from the server. */
  refreshProfiles: () => Promise<void>;
};

const ActiveProfileContext = createContext<ActiveProfileContextValue | undefined>(
  undefined,
);

export type ActiveProfileProviderProps = {
  children: ReactNode;
};

export const ActiveProfileProvider: React.FC<ActiveProfileProviderProps> = ({
  children,
}) => {
  const { ready: authReady, status, isAuthenticated } = useAuthBoot();
  const { canManageProfiles, canSwitchAllProfiles, canSwitchAssignedProfiles, multiUser } = useMemo(
    () => deriveAuthRole(status),
    [status],
  );
  const unrestrictedProfileAccess = canManageProfiles || canSwitchAllProfiles;

  const [profiles, setProfiles] = useState<HermesProfileSummary[]>([]);
  const [activeProfile, setActiveProfileState] = useState("default");
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshProfiles = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      if (multiUser && !unrestrictedProfileAccess) {
        const listData = await listProfiles();
        const active =
          listData.active ||
          listData.profiles.find((p) => p.is_active)?.name ||
          status?.profile_name?.trim() ||
          "default";
        setProfiles(listData.profiles);
        setActiveProfileState(active);
        return;
      }
      const listData = await listProfiles();
      const active =
        listData.active ||
        listData.profiles.find((p) => p.is_active)?.name ||
        "default";
      setProfiles(listData.profiles);
      setActiveProfileState(active);
    } catch (err) {
      console.error("Failed to load Hermes profiles:", err);
      setError(err instanceof Error ? err.message : "Failed to load profiles");
      const fallback = boundProfileSummaries(status?.profile_name);
      if (fallback.length > 0) {
        setProfiles(fallback);
        setActiveProfileState(fallback[0].name);
      } else {
        setActiveProfileState("default");
      }
    } finally {
      setLoading(false);
    }
  }, [multiUser, status?.profile_name, unrestrictedProfileAccess]);

  useEffect(() => {
    if (!authReady || !isAuthenticated) return;
    void refreshProfiles();
  }, [authReady, isAuthenticated, refreshProfiles, status?.profile_name]);

  const setActiveProfile = useCallback(
    async (name: string): Promise<HermesProfileSwitchResponse> => {
      if (!unrestrictedProfileAccess && multiUser && !canSwitchAssignedProfiles) {
        throw new Error("Profile switching is not allowed for this account");
      }
      if (!unrestrictedProfileAccess && multiUser) {
        const allowed = new Set(
          (status?.profile_names?.length
            ? status.profile_names
            : status?.profile_name
              ? [status.profile_name]
              : []
          ).map((n) => n.trim()),
        );
        if (!allowed.has(name.trim())) {
          throw new Error("Profile is not assigned to this account");
        }
      }
      if (!name || name === activeProfile) {
        return { active: activeProfile };
      }
      setSwitching(name);
      setError(null);
      try {
        const result = await switchProfile(name);
        const nextActive = result.active || name;
        setActiveProfileState(nextActive);
        setProfiles((prev) =>
          prev.map((profile) => ({
            ...profile,
            is_active: profile.name === nextActive,
          })),
        );
        return result;
      } catch (err) {
        console.error("Failed to switch Hermes profile:", err);
        const message =
          err instanceof Error ? err.message : "Failed to switch profile";
        setError(message);
        throw err instanceof Error ? err : new Error(message);
      } finally {
        setSwitching(null);
      }
    },
    [activeProfile, canSwitchAssignedProfiles, multiUser, status?.profile_name, status?.profile_names, unrestrictedProfileAccess],
  );

  const value = useMemo<ActiveProfileContextValue>(
    () => ({
      activeProfile: activeProfile || "default",
      profiles,
      loading,
      switching,
      error,
      setActiveProfile,
      refreshProfiles,
    }),
    [
      activeProfile,
      profiles,
      loading,
      switching,
      error,
      setActiveProfile,
      refreshProfiles,
    ],
  );

  return (
    <ActiveProfileContext.Provider value={value}>
      {children}
    </ActiveProfileContext.Provider>
  );
};

/** Shared Hermes active profile state for shell UI and chat/session APIs. */
export function useActiveProfile(): ActiveProfileContextValue {
  const context = useContext(ActiveProfileContext);
  if (!context) {
    throw new Error("useActiveProfile must be used within an ActiveProfileProvider");
  }
  return context;
}
