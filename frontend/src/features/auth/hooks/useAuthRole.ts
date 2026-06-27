import { useMemo } from "react";
import { useAuthBoot } from "./useAuthBoot";
import type { AuthStatus } from "../services/authService";

export type AuthRoleHelpers = {
  role: string | null;
  isAdmin: boolean;
  multiUser: boolean;
  /** Switch among assigned profiles (multi-user regular users). */
  canSwitchAssignedProfiles: boolean;
};

export function deriveAuthRole(status: AuthStatus | null): AuthRoleHelpers {
  const role = status?.role ?? null;
  const multiUser = status?.multi_user ?? false;
  const assignedCount = status?.profile_names?.length ?? (status?.profile_name ? 1 : 0);
  return {
    role,
    isAdmin: role === "admin",
    multiUser,
    canSwitchAssignedProfiles: !multiUser || role === "admin" || assignedCount > 1,
  };
}

/** Auth boot + role helpers for admin-gated UI (M30 / M30b / M39). */
export function useAuthRole() {
  const boot = useAuthBoot();
  const roleHelpers = useMemo(() => deriveAuthRole(boot.status), [boot.status]);

  return {
    ...boot,
    ...roleHelpers,
  };
}
