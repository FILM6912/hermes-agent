import { useEffect } from "react";
import { readWorkspaceFile } from "@/services/hermes/workspace";

const FETCH_REQUEST = "hermes-workspace-fetch";
const FETCH_RESPONSE = "hermes-workspace-fetch-response";

type WorkspaceFetchRequest = {
  type: typeof FETCH_REQUEST;
  id: string;
  workspace: string;
  path: string;
};

function isWorkspaceFetchRequest(data: unknown): data is WorkspaceFetchRequest {
  if (typeof data !== "object" || data === null) return false;
  const row = data as Record<string, unknown>;
  return (
    row.type === FETCH_REQUEST &&
    typeof row.id === "string" &&
    typeof row.workspace === "string" &&
    typeof row.path === "string"
  );
}

/**
 * Lets sandboxed workspace HTML previews load sibling files via authenticated API.
 * Injected pages call hermesLoadText()/hermesLoadJson() which postMessage here.
 */
export function useWorkspaceHtmlBridge(): void {
  useEffect(() => {
    async function onMessage(ev: MessageEvent) {
      if (ev.origin !== window.location.origin) return;
      if (!isWorkspaceFetchRequest(ev.data)) return;
      const source = ev.source;
      if (!source || typeof source.postMessage !== "function") return;

      const { id, workspace, path } = ev.data;
      const rel = path.trim().replace(/^\/+/, "");
      if (!rel || rel.includes("..")) {
        source.postMessage(
          {
            type: FETCH_RESPONSE,
            id,
            ok: false,
            error: "invalid workspace path",
          },
          { targetOrigin: ev.origin },
        );
        return;
      }

      try {
        const file = await readWorkspaceFile(undefined, rel, { workspace });
        source.postMessage(
          {
            type: FETCH_RESPONSE,
            id,
            ok: true,
            body: file.content,
          },
          { targetOrigin: ev.origin },
        );
      } catch (err) {
        source.postMessage(
          {
            type: FETCH_RESPONSE,
            id,
            ok: false,
            error: err instanceof Error ? err.message : "workspace fetch failed",
          },
          { targetOrigin: ev.origin },
        );
      }
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);
}
