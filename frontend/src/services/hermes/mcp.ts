/**
 * Hermes MCP inventory API (M25).
 * GET /mcp/servers — configured MCP servers with runtime status.
 * GET /mcp/tools — known tools from runtime/registry.
 */
import { fetchJson } from "@/lib/api";

export type HermesMcpServer = {
  name: string;
  transport: string;
  enabled: boolean;
  active: boolean;
  status: string;
  tool_count?: number | null;
  connect_error?: string;
  url?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  timeout?: number;
  connect_timeout?: number;
  /** Masked HTTP headers (secrets redacted). */
  headers?: Record<string, string>;
  /** Hermes agent auth mode, e.g. oauth. */
  auth?: string;
  auth_configured?: boolean;
  auth_type?: "none" | "bearer" | "api_key" | "oauth" | "custom";
  auth_header_name?: string;
  /** Synced from default profile — UI must not edit/delete/disable. */
  read_only?: boolean;
  synced_from_default?: boolean;
};

export type HermesMcpTool = {
  name: string;
  server: string;
  description?: string;
  active?: boolean;
  enabled?: boolean;
  status?: string;
};

export type HermesMcpServersResponse = {
  servers: HermesMcpServer[];
  toggle_supported?: boolean;
  reload_required?: boolean;
  profile?: string;
};

export type HermesMcpToolsResponse = {
  tools: HermesMcpTool[];
  total?: number;
  source?: string;
  unavailable_servers?: string[];
};

export type HermesMcpServerTestResponse = {
  ok: boolean;
  profile?: string;
  server: HermesMcpServer;
  tools: HermesMcpTool[];
  tool_count?: number;
  error?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asBool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function narrowMcpHeaders(value: unknown): Record<string, string> | undefined {
  if (!isRecord(value)) return undefined;
  const out: Record<string, string> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw === "string") out[key] = raw;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function narrowMcpAuthType(
  value: unknown,
): HermesMcpServer["auth_type"] | undefined {
  const allowed = new Set(["none", "bearer", "api_key", "oauth", "custom"]);
  return typeof value === "string" && allowed.has(value)
    ? (value as HermesMcpServer["auth_type"])
    : undefined;
}

export function narrowMcpServer(value: unknown): HermesMcpServer | null {
  if (!isRecord(value)) return null;
  const name = asString(value.name).trim();
  if (!name) return null;
  return {
    name,
    transport: asString(value.transport, "unknown"),
    enabled: asBool(value.enabled, true),
    active: asBool(value.active),
    status: asString(value.status, "unknown"),
    tool_count:
      typeof value.tool_count === "number" || value.tool_count === null
        ? value.tool_count
        : undefined,
    connect_error: asString(value.connect_error) || undefined,
    url: asString(value.url) || undefined,
    command: asString(value.command) || undefined,
    args: Array.isArray(value.args)
      ? value.args.filter((entry): entry is string => typeof entry === "string")
      : undefined,
    env: narrowMcpHeaders(value.env),
    timeout: typeof value.timeout === "number" ? value.timeout : undefined,
    connect_timeout:
      typeof value.connect_timeout === "number" ? value.connect_timeout : undefined,
    headers: narrowMcpHeaders(value.headers),
    auth: asString(value.auth) || undefined,
    auth_configured:
      typeof value.auth_configured === "boolean" ? value.auth_configured : undefined,
    auth_type: narrowMcpAuthType(value.auth_type),
    auth_header_name: asString(value.auth_header_name) || undefined,
    read_only: typeof value.read_only === "boolean" ? value.read_only : undefined,
    synced_from_default:
      typeof value.synced_from_default === "boolean"
        ? value.synced_from_default
        : undefined,
  };
}

export function isMcpServerReadOnly(server: HermesMcpServer): boolean {
  return server.read_only === true || server.synced_from_default === true;
}

export function narrowMcpTool(value: unknown): HermesMcpTool | null {
  if (!isRecord(value)) return null;
  const name = asString(value.name).trim();
  const server = asString(value.server).trim();
  if (!name) return null;
  return {
    name,
    server,
    description: asString(value.description) || undefined,
    active: typeof value.active === "boolean" ? value.active : undefined,
    enabled: typeof value.enabled === "boolean" ? value.enabled : undefined,
    status: asString(value.status) || undefined,
  };
}

export function narrowMcpServersResponse(value: unknown): HermesMcpServersResponse {
  if (!isRecord(value) || !Array.isArray(value.servers)) {
    return { servers: [] };
  }
  return {
    servers: value.servers
      .map(narrowMcpServer)
      .filter((s): s is HermesMcpServer => s !== null),
    toggle_supported:
      typeof value.toggle_supported === "boolean" ? value.toggle_supported : undefined,
    reload_required:
      typeof value.reload_required === "boolean" ? value.reload_required : undefined,
    profile: asString(value.profile) || undefined,
  };
}

export function narrowMcpToolsResponse(value: unknown): HermesMcpToolsResponse {
  if (!isRecord(value) || !Array.isArray(value.tools)) {
    return { tools: [] };
  }
  return {
    tools: value.tools
      .map(narrowMcpTool)
      .filter((t): t is HermesMcpTool => t !== null),
    total: typeof value.total === "number" ? value.total : undefined,
    source: asString(value.source) || undefined,
    unavailable_servers: Array.isArray(value.unavailable_servers)
      ? value.unavailable_servers.filter((s): s is string => typeof s === "string")
      : undefined,
  };
}

/** GET /api/v1/mcp/servers */
export async function listMcpServers(
  profile?: string,
): Promise<HermesMcpServersResponse> {
  const raw = await fetchJson<unknown>("/mcp/servers", {
    query: profile ? { profile } : undefined,
  });
  return narrowMcpServersResponse(raw);
}

/** GET /api/v1/mcp/tools */
export async function listMcpTools(): Promise<HermesMcpToolsResponse> {
  const raw = await fetchJson<unknown>("/mcp/tools");
  return narrowMcpToolsResponse(raw);
}

export type McpServerWritePayload = {
  profile?: string;
  transport?: "stdio" | "http";
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  auth?: string;
  timeout?: number;
  enabled?: boolean;
};

function profileQuery(profile?: string) {
  return profile ? { profile } : undefined;
}

/** POST /api/v1/mcp/discover — refresh runtime connection status */
export async function discoverMcpServers(
  profile?: string,
): Promise<unknown> {
  return fetchJson<unknown>("/mcp/discover", {
    method: "POST",
    body: profile ? { profile } : {},
    query: profileQuery(profile),
  });
}

export function narrowMcpServerTestResponse(
  value: unknown,
): HermesMcpServerTestResponse | null {
  if (!isRecord(value)) return null;
  const server = narrowMcpServer(value.server);
  if (!server) return null;
  const tools = Array.isArray(value.tools)
    ? value.tools
        .map(narrowMcpTool)
        .filter((t): t is HermesMcpTool => t !== null)
    : [];
  return {
    ok: asBool(value.ok),
    profile: asString(value.profile) || undefined,
    server,
    tools,
    tool_count: typeof value.tool_count === "number" ? value.tool_count : tools.length,
    error: asString(value.error) || undefined,
  };
}

/** POST /api/v1/mcp/servers/{name}/test — probe one server and list its tools */
export async function testMcpServer(
  name: string,
  profile?: string,
): Promise<HermesMcpServerTestResponse> {
  const raw = await fetchJson<unknown>(
    `/mcp/servers/${encodeURIComponent(name)}/test`,
    {
      method: "POST",
      body: profile ? { profile } : {},
      query: profileQuery(profile),
    },
  );
  return (
    narrowMcpServerTestResponse(raw) ?? {
      ok: false,
      server: {
        name,
        transport: "unknown",
        enabled: true,
        active: false,
        status: "error",
      },
      tools: [],
      error: "Invalid MCP test response",
    }
  );
}

/** PUT /api/v1/mcp/servers/{name} — add or update a server */
export async function updateMcpServer(
  name: string,
  payload: McpServerWritePayload,
  profile?: string,
): Promise<unknown> {
  const body = { ...payload, ...(profile ? { profile } : {}) };
  return fetchJson<unknown>(`/mcp/servers/${encodeURIComponent(name)}`, {
    method: "PUT",
    body,
    query: profileQuery(profile),
  });
}

/** PATCH /api/v1/mcp/servers/{name} — enable/disable */
export async function toggleMcpServer(
  name: string,
  enabled: boolean,
  profile?: string,
): Promise<unknown> {
  const body = { enabled, ...(profile ? { profile } : {}) };
  return fetchJson<unknown>(`/mcp/servers/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body,
    query: profileQuery(profile),
  });
}

/** POST /api/v1/mcp/servers/import — bulk import from JSON object */
export async function importMcpServers(
  servers: Record<string, Record<string, unknown>>,
  profile?: string,
): Promise<unknown> {
  const body = { servers, ...(profile ? { profile } : {}) };
  return fetchJson<unknown>("/mcp/servers/import", {
    method: "POST",
    body,
    query: profileQuery(profile),
  });
}

/** DELETE /api/v1/mcp/servers/{name} */
export async function deleteMcpServer(
  name: string,
  profile?: string,
): Promise<unknown> {
  const body = profile ? { profile } : {};
  return fetchJson<unknown>(`/mcp/servers/${encodeURIComponent(name)}`, {
    method: "DELETE",
    body,
    query: profileQuery(profile),
  });
}
