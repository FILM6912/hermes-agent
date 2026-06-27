import { describe, expect, it } from "vitest";
import {
  MCP_JSON_EXAMPLE,
  formToMcpJsonText,
  mcpJsonDraftText,
  parseMcpJsonInput,
  serverToMcpConfig,
  validateMcpJsonEdit,
} from "./mcpJson";

describe("parseMcpJsonInput", () => {
  it("parses a single stdio server", () => {
    const raw = `{
      "demo": { "command": "node", "args": ["server.js"] }
    }`;
    expect(parseMcpJsonInput(raw)).toEqual({
      demo: { command: "node", args: ["server.js"] },
    });
  });

  it("rejects entries without url or command", () => {
    expect(() => parseMcpJsonInput(`{"bad": {"timeout": 10}}`)).toThrow(/url or command/i);
  });

  it("requires edit JSON to keep the same server name", () => {
    const servers = parseMcpJsonInput(`{"other": {"command": "x"}}`);
    expect(() => validateMcpJsonEdit(servers, "demo")).toThrow(/current server name/i);
  });
});

describe("mcpJsonDraftText", () => {
  it("falls back to example when no name is set", () => {
    expect(mcpJsonDraftText({})).toBe(MCP_JSON_EXAMPLE);
  });

  it("builds JSON from a server summary", () => {
    const text = mcpJsonDraftText({
      name: "hermes-webui",
      server: { command: "python3", args: ["mcp_server.py"] },
    });
    expect(JSON.parse(text)).toEqual({
      "hermes-webui": { command: "python3", args: ["mcp_server.py"] },
    });
  });
});

describe("formToMcpJsonText", () => {
  it("serializes HTTP form fields", () => {
    const text = formToMcpJsonText({
      name: "remote",
      transport: "http",
      command: "",
      args: "",
      url: "http://127.0.0.1:3000/mcp",
      timeout: "90",
      enabled: true,
    });
    expect(JSON.parse(text)).toEqual({
      remote: { url: "http://127.0.0.1:3000/mcp", timeout: 90 },
    });
  });
});

describe("serverToMcpConfig", () => {
  it("preserves masked headers for edit drafts", () => {
    expect(
      serverToMcpConfig({
        url: "http://127.0.0.1/mcp",
        headers: { Authorization: "Bearer ••••••" },
      }),
    ).toEqual({
      url: "http://127.0.0.1/mcp",
      headers: { Authorization: "Bearer ••••••" },
    });
  });
});
