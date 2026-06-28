import { useMemo } from "react";
import { useAuthBoot } from "./useAuthBoot";
import { roleHasPermission } from "@/features/admin/rolesApi";
import type { AuthStatus } from "../services/authService";

export type AuthRoleHelpers = {
  role: string | null;
  permissions: Record<string, boolean>;
  isAdmin: boolean;
  multiUser: boolean;
  canManageUsers: boolean;
  canManageRoles: boolean;
  canManageProfiles: boolean;
  canManageWorkspaces: boolean;
  canSwitchAllProfiles: boolean;
  canAccessSettingsSystem: boolean;
  canUploadFile: boolean;
  canRagIngest: boolean;
  canRagSearch: boolean;
  canRagApprove: boolean;
  canRagManage: boolean;
  canTranscriptReportRead: boolean;
  canTranscriptReportCreate: boolean;
  canTranscriptReportEdit: boolean;
  canTranscriptReportDelete: boolean;
  /** Switch among assigned profiles (multi-user regular users). */
  canSwitchAssignedProfiles: boolean;
};

export function deriveAuthRole(status: AuthStatus | null): AuthRoleHelpers {
  const role = status?.role ?? null;
  const permissions = status?.permissions ?? {};
  const multiUser = status?.multi_user ?? false;
  const isAdmin = roleHasPermission(permissions, "*");
  const assignedCount = status?.profile_names?.length ?? (status?.profile_name ? 1 : 0);
  const canManageProfiles =
    !multiUser || roleHasPermission(permissions, "profiles:manage") || isAdmin;
  return {
    role,
    permissions,
    isAdmin,
    multiUser,
    canManageUsers: !multiUser || roleHasPermission(permissions, "users:manage"),
    canManageRoles: !multiUser || roleHasPermission(permissions, "roles:manage"),
    canManageProfiles,
    canManageWorkspaces:
      !multiUser ||
      roleHasPermission(permissions, "workspaces:manage") ||
      roleHasPermission(permissions, "users:manage"),
    canSwitchAllProfiles:
      !multiUser ||
      canManageProfiles ||
      roleHasPermission(permissions, "profiles:switch_all"),
    canAccessSettingsSystem:
      !multiUser || isAdmin || roleHasPermission(permissions, "settings:system"),
    canUploadFile: !multiUser || roleHasPermission(permissions, "upload:file"),
    canRagIngest: !multiUser || roleHasPermission(permissions, "rag:ingest"),
    canRagSearch: !multiUser || roleHasPermission(permissions, "rag:search"),
    canRagApprove: !multiUser || roleHasPermission(permissions, "rag:approve"),
    canRagManage: !multiUser || roleHasPermission(permissions, "rag:manage"),
    canTranscriptReportRead:
      !multiUser || roleHasPermission(permissions, "transcript-report:read"),
    canTranscriptReportCreate:
      !multiUser || roleHasPermission(permissions, "transcript-report:create"),
    canTranscriptReportEdit:
      !multiUser || roleHasPermission(permissions, "transcript-report:edit"),
    canTranscriptReportDelete:
      !multiUser || roleHasPermission(permissions, "transcript-report:delete"),
    canSwitchAssignedProfiles:
      !multiUser || isAdmin || assignedCount > 1,
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
