import type { HermesMcpServer } from "@/services/hermes/mcp";

export type McpServerConfig = Record<string, unknown>;

export const MCP_JSON_EXAMPLE = `{
  "opensandbox": {
    "command": "opensandbox-mcp",
    "args": ["--domain", "localhost:8080", "--protocol", "http"]
  }
}`;

export type McpJsonMessages = {
  required: string;
  invalid: string;
  objectRequired: string;
  noServers: string;
  entryInvalid: string;
  entryMissingTransport: string;
  editSingle: string;
};

const DEFAULT_MESSAGES: McpJsonMessages = {
  required: "JSON is required.",
  invalid: "Invalid JSON.",
  objectRequired: "JSON must be an object.",
  noServers: "No MCP server entries found in JSON.",
  entryInvalid: "Invalid config for server",
  entryMissingTransport: "Each server needs url or command",
  editSingle: "Edit JSON must contain only the current server name.",
};

export function serverToMcpConfig(
  server: Partial<
    HermesMcpServer & { args?: string[]; env?: Record<string, string>; connect_timeout?: number }
  >,
): McpServerConfig {
  const cfg: McpServerConfig = {};
  if (!server || typeof server !== "object") return cfg;
  if (server.url) cfg.url = server.url;
  if (server.command) cfg.command = server.command;
  if (Array.isArray(server.args) && server.args.length) cfg.args = server.args.slice();
  if (server.headers && typeof server.headers === "object") cfg.headers = { ...server.headers };
  if (server.env && typeof server.env === "object") cfg.env = { ...server.env };
  if (server.timeout != null) cfg.timeout = server.timeout;
  if (server.connect_timeout != null) cfg.connect_timeout = server.connect_timeout;
  if (server.enabled === false) cfg.enabled = false;
  if (server.transport) cfg.transport = server.transport;
  if (server.auth) cfg.auth = server.auth;
  return cfg;
}

export function mcpJsonDraftText(options: {
  jsonText?: string;
  name?: string;
  server?: Partial<HermesMcpServer & { args?: string[]; env?: Record<string, string> }>;
}): string {
  if (options.jsonText?.trim()) return options.jsonText;
  const name = options.name?.trim() || options.server?.name?.trim() || "";
  const cfg = serverToMcpConfig(options.server ?? {});
  if (name) return JSON.stringify({ [name]: cfg }, null, 2);
  return MCP_JSON_EXAMPLE;
}

export function parseMcpJsonInput(
  raw: string,
  messages: Partial<McpJsonMessages> = {},
): Record<string, McpServerConfig> {
  const msg = { ...DEFAULT_MESSAGES, ...messages };
  let text = String(raw || "").trim();
  if (!text) throw new Error(msg.required);
  if (!text.startsWith("{")) {
    text = `{${text.replace(/,\s*$/, "")}}`;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    const detail = err instanceof Error ? err.message : "";
    throw new Error(detail ? `${msg.invalid} ${detail}` : msg.invalid);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(msg.objectRequired);
  }
  const servers: Record<string, McpServerConfig> = {};
  for (const [name, cfg] of Object.entries(parsed as Record<string, unknown>)) {
    const key = String(name || "").trim();
    if (!key) continue;
    if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) {
      throw new Error(`${msg.entryInvalid} "${key}"`);
    }
    const entry = cfg as McpServerConfig;
    if (!entry.url && !entry.command) {
      throw new Error(`${msg.entryMissingTransport}: "${key}"`);
    }
    servers[key] = entry;
  }
  if (!Object.keys(servers).length) throw new Error(msg.noServers);
  return servers;
}

export function validateMcpJsonEdit(
  servers: Record<string, McpServerConfig>,
  expectedName: string,
  messages: Partial<McpJsonMessages> = {},
): void {
  const msg = { ...DEFAULT_MESSAGES, ...messages };
  const names = Object.keys(servers);
  if (names.length !== 1 || names[0] !== expectedName) {
    throw new Error(msg.editSingle);
  }
}

export type McpFormJsonSource = {
  name: string;
  transport: "stdio" | "http";
  command: string;
  args: string;
  url: string;
  timeout: string;
  enabled: boolean;
  headers?: Record<string, string>;
  auth?: string;
};

export function formToMcpConfig(form: McpFormJsonSource): McpServerConfig {
  const cfg: McpServerConfig = {
    timeout: Number(form.timeout) || 120,
  };
  if (!form.enabled) cfg.enabled = false;
  if (form.transport === "http") {
    cfg.url = form.url.trim();
    if (form.headers && Object.keys(form.headers).length) cfg.headers = form.headers;
    if (form.auth) cfg.auth = form.auth;
  } else {
    cfg.command = form.command.trim();
    const argsRaw = form.args.trim();
    if (argsRaw) {
      cfg.args = argsRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
  }
  return cfg;
}

export function formToMcpJsonText(form: McpFormJsonSource): string {
  const name = form.name.trim() || "my-server";
  return JSON.stringify({ [name]: formToMcpConfig(form) }, null, 2);
}
