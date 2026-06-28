/**
 * Whether the composer workspace must be pushed to the active Hermes session.
 * GET /list uses server-side session.workspace; client-only state is not enough.
 */
export function composerNeedsServerWorkspaceBind(
  composerWorkspace: string,
  serverWorkspace: string,
): boolean {
  const composer = composerWorkspace.trim();
  if (!composer) return false;
  return serverWorkspace.trim() !== composer;
}
