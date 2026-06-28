/** True when composer workspace differs from the server-bound session workspace. */
export function composerNeedsServerWorkspaceBind(
  composer: string,
  server: string,
): boolean {
  const c = composer.trim();
  if (!c) return false;
  return server.trim() !== c;
}
