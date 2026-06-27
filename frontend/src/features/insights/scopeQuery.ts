/** Map scope selector value to insights/logs API query params. */
export function scopeToQuery(scope: string): { profile?: string; username?: string } {
  if (!scope) return {};
  if (scope.startsWith("user:")) return { username: scope.slice(5) };
  if (scope.startsWith("profile:")) return { profile: scope.slice(8) };
  return { profile: scope };
}
