import type { HermesMcpServer } from "@/services/hermes/mcp";

/** Placeholder returned by the API for masked secret values. */
export const MCP_MASKED_SECRET = "••••••";

export type McpAuthType = "none" | "bearer" | "api_key" | "oauth";

const NON_SECRET_HEADERS = new Set([
  "accept",
  "content-type",
  "user-agent",
  "mcp-protocol-version",
]);

export function isMaskedSecret(value: string | undefined): boolean {
  return value === MCP_MASKED_SECRET;
}

export function detectMcpAuthType(server: HermesMcpServer): McpAuthType {
  const explicit = server.auth_type?.toLowerCase();
  if (explicit === "oauth") return "oauth";
  if (explicit === "bearer") return "bearer";
  if (explicit === "api_key") return "api_key";
  if (explicit === "none" || explicit === "custom") return explicit === "none" ? "none" : "api_key";

  if (server.auth?.toLowerCase() === "oauth") return "oauth";

  const headers = server.headers;
  if (!headers || Object.keys(headers).length === 0) {
    return server.auth_configured ? "api_key" : "none";
  }

  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === "authorization") {
      if (
        typeof value === "string" &&
        (value.toLowerCase().startsWith("bearer ") || isMaskedSecret(value))
      ) {
        return "bearer";
      }
    }
  }

  return "api_key";
}

export function mcpAuthHeaderName(server: HermesMcpServer): string {
  if (server.auth_header_name) return server.auth_header_name;
  const headers = server.headers ?? {};
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === "authorization") continue;
    if (NON_SECRET_HEADERS.has(key.toLowerCase())) continue;
    return key;
  }
  return "X-Api-Key";
}

export type McpAuthFormState = {
  authType: McpAuthType;
  bearerToken: string;
  apiKeyHeader: string;
  apiKeyValue: string;
};

export function mcpAuthFormFromServer(server: HermesMcpServer): McpAuthFormState {
  const authType = detectMcpAuthType(server);
  return {
    authType,
    bearerToken: "",
    apiKeyHeader: authType === "api_key" ? mcpAuthHeaderName(server) : "X-Api-Key",
    apiKeyValue: "",
  };
}

export function buildMcpAuthPayload(
  auth: McpAuthFormState,
  existingHeaders?: Record<string, string>,
): { headers?: Record<string, string>; auth?: string } {
  if (auth.authType === "none") {
    return { headers: {}, auth: "" };
  }
  if (auth.authType === "oauth") {
    return { auth: "oauth", headers: {} };
  }
  if (auth.authType === "bearer") {
    const token = auth.bearerToken.trim();
    if (token) {
      return { headers: { Authorization: `Bearer ${token}` } };
    }
    const existing = existingHeaders?.Authorization ?? existingHeaders?.authorization;
    if (isMaskedSecret(existing)) {
      return { headers: { Authorization: MCP_MASKED_SECRET } };
    }
    return { headers: {} };
  }

  const headerName = auth.apiKeyHeader.trim() || "X-Api-Key";
  const value = auth.apiKeyValue.trim();
  if (value) {
    return { headers: { [headerName]: value } };
  }
  const existing = existingHeaders?.[headerName];
  if (isMaskedSecret(existing)) {
    return { headers: { [headerName]: MCP_MASKED_SECRET } };
  }
  return { headers: {} };
}

export function mcpAuthLabel(authType: McpAuthType): string {
  switch (authType) {
    case "bearer":
      return "Bearer";
    case "api_key":
      return "API key";
    case "oauth":
      return "OAuth";
    default:
      return "";
  }
}
