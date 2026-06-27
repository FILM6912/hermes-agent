/** Broadcast when admin RBAC or account role changes should reload auth/status. */
export const AUTH_REFRESH_EVENT = "hermes-auth-refresh";

export function notifyAuthRefresh(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(AUTH_REFRESH_EVENT));
}
