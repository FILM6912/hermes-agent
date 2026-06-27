import { fetchJson } from "@/lib/api";
import type { AuthStatus } from "@/features/auth/services/authService";
import { roleHasPermission } from "@/features/admin/rolesApi";

export type InsightsQuery = {
  days?: number;
  profile?: string;
  username?: string;
};

export type DailyTokenRow = {
  date: string;
  input_tokens: number;
  output_tokens: number;
  sessions: number;
  cost: number;
};

export type ModelUsageRow = {
  model: string;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost: number;
  session_share: number;
  token_share: number;
  cost_share: number;
};

export type InsightsResponse = {
  period_days?: number;
  profile?: string | null;
  total_sessions: number;
  total_messages: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_cost: number;
  models: ModelUsageRow[];
  daily_tokens: DailyTokenRow[];
  activity_by_day?: Array<{ day: string; sessions: number }>;
  activity_by_hour?: Array<{ hour: number; sessions: number }>;
};

/** Insights panel when multi-user mode is enabled. */
export function canAccessInsights(status: AuthStatus | null): boolean {
  if (!status) return false;
  if (!status.multi_user) return true;
  if (status.role === "admin") return true;
  return (
    roleHasPermission(status.permissions, "*") ||
    roleHasPermission(status.permissions, "insights:read") ||
    roleHasPermission(status.permissions, "users:manage") ||
    roleHasPermission(status.permissions, "roles:manage")
  );
}

/** Logs panel when multi-user mode is enabled. */
export function canAccessLogs(status: AuthStatus | null): boolean {
  if (!status) return false;
  if (!status.multi_user) return true;
  if (status.role === "admin") return true;
  return (
    roleHasPermission(status.permissions, "*") ||
    roleHasPermission(status.permissions, "logs:read") ||
    roleHasPermission(status.permissions, "users:manage") ||
    roleHasPermission(status.permissions, "roles:manage")
  );
}

/** Either permission shows the insights/logs tool group in the shell. */
export function canAccessInsightsLogs(status: AuthStatus | null): boolean {
  return canAccessInsights(status) || canAccessLogs(status);
}

export type InsightsLogsScopeOption = { value: string; label: string };

/** Scope selector for non-admin viewers — own profile/username only. */
export function scopeOptionsFromAuthStatus(
  status: AuthStatus | null,
): InsightsLogsScopeOption[] {
  if (!status?.multi_user) return [];
  const email = (status.email || status.user_id || "").trim();
  const profile = (status.profile_name || status.profile_names?.[0] || "").trim();
  if (profile) {
    return [
      {
        value: `profile:${profile}`,
        label: email ? `${email} (${profile})` : profile,
      },
    ];
  }
  if (email) {
    return [{ value: `user:${email}`, label: email }];
  }
  return [];
}

export async function loadInsightsLogsScopeOptions(
  status: AuthStatus | null,
  canManageUsers: boolean,
): Promise<InsightsLogsScopeOption[]> {
  if (!status?.multi_user) return [];
  if (canManageUsers) {
    try {
      const data = await fetchJson<{
        users?: Array<{ username: string; profile_name?: string | null }>;
      }>("/admin/users");
      const users = data.users ?? [];
      return users.map((u) => ({
        value: u.profile_name ? `profile:${u.profile_name}` : `user:${u.username}`,
        label: u.profile_name ? `${u.username} (${u.profile_name})` : u.username,
      }));
    } catch {
      return scopeOptionsFromAuthStatus(status);
    }
  }
  return scopeOptionsFromAuthStatus(status);
}

/** GET /api/v1/insights */
export async function fetchInsights(query?: InsightsQuery): Promise<InsightsResponse> {
  return fetchJson<InsightsResponse>("/insights", {
    query: {
      days: query?.days,
      profile: query?.profile,
      username: query?.username,
    },
  });
}
