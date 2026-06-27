import React, { useCallback, useEffect, useState } from "react";
import {
  Loader2,
  Plug,
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  X,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import {
  deleteMcpServer,
  discoverMcpServers,
  importMcpServers,
  isMcpServerReadOnly,
  listMcpServers,
  testMcpServer,
  toggleMcpServer,
  updateMcpServer,
  type HermesMcpServer,
  type HermesMcpTool,
} from "@/services/hermes/mcp";
import { McpAuthFields } from "@/features/mcp/McpAuthFields";
import {
  formToMcpJsonText,
  mcpJsonDraftText,
  MCP_JSON_EXAMPLE,
  parseMcpJsonInput,
  validateMcpJsonEdit,
} from "@/features/mcp/mcpJson";
import {
  buildMcpAuthPayload,
  detectMcpAuthType,
  mcpAuthFormFromServer,
  mcpAuthLabel,
  type McpAuthFormState,
} from "@/features/mcp/mcpAuth";

type Transport = "stdio" | "http";
type InputMode = "form" | "json";

type FormState = {
  name: string;
  transport: Transport;
  command: string;
  args: string;
  url: string;
  timeout: string;
  enabled: boolean;
  auth: McpAuthFormState;
  existingHeaders?: Record<string, string>;
  authConfigured: boolean;
};

const EMPTY_AUTH: McpAuthFormState = {
  authType: "none",
  bearerToken: "",
  apiKeyHeader: "X-Api-Key",
  apiKeyValue: "",
};

const EMPTY_FORM: FormState = {
  name: "",
  transport: "stdio",
  command: "",
  args: "",
  url: "",
  timeout: "120",
  enabled: true,
  auth: EMPTY_AUTH,
  authConfigured: false,
};

function statusBadgeClass(server: HermesMcpServer): string {
  const status = server.status || "configured";
  if (status === "active") return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300";
  if (status === "disabled" || !server.enabled) return "bg-zinc-500/15 text-zinc-600 dark:text-zinc-400";
  if (status === "error" || server.connect_error) return "bg-rose-500/15 text-rose-700 dark:text-rose-300";
  return "bg-amber-500/15 text-amber-700 dark:text-amber-300";
}

function serverDetail(server: HermesMcpServer): string {
  if (server.transport === "http") return server.url || "";
  return server.command || server.url || "";
}

function formFromServer(server: HermesMcpServer): FormState {
  const transport: Transport = server.transport === "http" ? "http" : "stdio";
  return {
    name: server.name,
    transport,
    command: server.command || "",
    args: Array.isArray(server.args) ? server.args.join(", ") : "",
    url: server.url || "",
    timeout: server.timeout != null ? String(server.timeout) : "120",
    enabled: server.enabled !== false,
    auth: mcpAuthFormFromServer(server),
    existingHeaders: server.headers,
    authConfigured: server.auth_configured === true,
  };
}

function formToJsonSource(form: FormState) {
  const base = {
    name: form.name,
    transport: form.transport,
    command: form.command,
    args: form.args,
    url: form.url,
    timeout: form.timeout,
    enabled: form.enabled,
  };
  if (form.transport !== "http") return base;
  const authPayload = buildMcpAuthPayload(form.auth, form.existingHeaders);
  return {
    ...base,
    headers: authPayload.headers,
    auth: authPayload.auth,
  };
}

function jsonMessages(t: (key: string) => string | undefined) {
  return {
    required: t("settings.mcpJsonRequired") || "JSON is required.",
    invalid: t("settings.mcpJsonInvalid") || "Invalid JSON.",
    objectRequired: t("settings.mcpJsonObjectRequired") || "JSON must be an object.",
    noServers: t("settings.mcpJsonNoServers") || "No MCP server entries found in JSON.",
    entryInvalid: t("settings.mcpJsonEntryInvalid") || "Invalid config for server",
    entryMissingTransport:
      t("settings.mcpJsonEntryMissingTransport") || "Each server needs url or command",
    editSingle:
      t("settings.mcpJsonEditSingle") ||
      "Edit JSON must contain only the current server name.",
  };
}

export const McpTab: React.FC = () => {
  const { t } = useLanguage();
  const [servers, setServers] = useState<HermesMcpServer[]>([]);
  const [toggleSupported, setToggleSupported] = useState(true);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<"list" | "create" | "edit">("list");
  const [inputMode, setInputMode] = useState<InputMode>("form");
  const [jsonText, setJsonText] = useState(MCP_JSON_EXAMPLE);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [pendingToggle, setPendingToggle] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingTest, setPendingTest] = useState<string | null>(null);
  const [serverTools, setServerTools] = useState<Record<string, HermesMcpTool[]>>({});

  const loadServers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listMcpServers();
      setServers(resp.servers);
      setToggleSupported(resp.toggle_supported !== false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setServers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const runDiscover = useCallback(async () => {
    setDiscovering(true);
    try {
      await discoverMcpServers();
      const resp = await listMcpServers();
      setServers(resp.servers);
      setToggleSupported(resp.toggle_supported !== false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDiscovering(false);
    }
  }, []);

  useEffect(() => {
    void loadServers();
  }, [loadServers]);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setInputMode("form");
    setJsonText(MCP_JSON_EXAMPLE);
    setFormMode("create");
  };

  const openEdit = (server: HermesMcpServer) => {
    if (isMcpServerReadOnly(server)) return;
    setForm(formFromServer(server));
    setInputMode("form");
    setJsonText(mcpJsonDraftText({ name: server.name, server }));
    setFormMode("edit");
  };

  const cancelForm = () => {
    setForm(EMPTY_FORM);
    setInputMode("form");
    setJsonText(MCP_JSON_EXAMPLE);
    setFormMode("list");
  };

  const switchInputMode = (mode: InputMode) => {
    if (mode === "json") {
      setJsonText((current) =>
        current.trim() && current !== MCP_JSON_EXAMPLE
          ? current
          : formToMcpJsonText(formToJsonSource(form)),
      );
    }
    setInputMode(mode);
  };

  const handleSaveJson = async () => {
    const messages = jsonMessages(t);
    let servers;
    try {
      servers = parseMcpJsonInput(jsonText, messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    if (formMode === "edit") {
      try {
        validateMcpJsonEdit(servers, form.name.trim(), messages);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      await importMcpServers(servers);
      setFormMode("list");
      setForm(EMPTY_FORM);
      setInputMode("form");
      setJsonText(MCP_JSON_EXAMPLE);
      await loadServers();
      await runDiscover();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    if (inputMode === "json") {
      await handleSaveJson();
      return;
    }
    const name = form.name.trim();
    if (!name) {
      setError(t("settings.mcpNameRequired") || "Server name is required.");
      return;
    }
    const payload: Parameters<typeof updateMcpServer>[1] = {
      enabled: form.enabled,
      timeout: Number(form.timeout) || 120,
    };
    if (form.transport === "http") {
      const url = form.url.trim();
      if (!url) {
        setError(t("settings.mcpUrlRequired") || "URL is required for HTTP transport.");
        return;
      }
      payload.url = url;
      const authPayload = buildMcpAuthPayload(form.auth, form.existingHeaders);
      if (authPayload.headers !== undefined) payload.headers = authPayload.headers;
      if (authPayload.auth !== undefined) payload.auth = authPayload.auth;
    } else {
      const command = form.command.trim();
      if (!command) {
        setError(t("settings.mcpCommandRequired") || "Command is required for stdio transport.");
        return;
      }
      payload.command = command;
      const argsRaw = form.args.trim();
      if (argsRaw) {
        payload.args = argsRaw.split(",").map((s) => s.trim()).filter(Boolean);
      }
    }
    setSaving(true);
    setError(null);
    try {
      await updateMcpServer(name, payload);
      setFormMode("list");
      setForm(EMPTY_FORM);
      await loadServers();
      await runDiscover();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (server: HermesMcpServer) => {
    if (!toggleSupported || isMcpServerReadOnly(server)) return;
    setPendingToggle(server.name);
    setError(null);
    try {
      await toggleMcpServer(server.name, server.enabled === false);
      await loadServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingToggle(null);
    }
  };

  const handleTest = async (server: HermesMcpServer) => {
    setPendingTest(server.name);
    setError(null);
    try {
      const result = await testMcpServer(server.name);
      setServerTools((prev) => ({ ...prev, [server.name]: result.tools }));
      setServers((prev) =>
        prev.map((entry) => (entry.name === server.name ? result.server : entry)),
      );
      if (!result.ok) {
        setError(
          result.error ||
            (t("settings.mcpTestFailed") || "MCP connection test failed for {name}").replace(
              "{name}",
              server.name,
            ),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingTest(null);
    }
  };

  const handleDelete = async (server: HermesMcpServer) => {
    if (isMcpServerReadOnly(server)) return;
    const ok = window.confirm(
      (t("settings.mcpDeleteConfirm") || 'Delete MCP server "{name}"?').replace(
        "{name}",
        server.name,
      ),
    );
    if (!ok) return;
    setPendingDelete(server.name);
    setError(null);
    try {
      await deleteMcpServer(server.name);
      await loadServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPendingDelete(null);
    }
  };

  if (formMode !== "list") {
    const isEdit = formMode === "edit";
    const jsonMode = inputMode === "json";
    return (
      <div className="max-w-2xl space-y-6">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {isEdit
              ? t("settings.mcpEditServer") || "Edit MCP server"
              : t("settings.mcpAddServer") || "Add MCP server"}
          </h3>
          <button
            type="button"
            onClick={cancelForm}
            className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div
          className="inline-flex rounded-lg border border-zinc-200 p-1 dark:border-zinc-800"
          role="tablist"
          aria-label={t("settings.mcpInputModeLabel") || "MCP input mode"}
        >
          <button
            type="button"
            role="tab"
            aria-selected={!jsonMode}
            onClick={() => switchInputMode("form")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              !jsonMode
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            {t("settings.mcpInputForm") || "Form"}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={jsonMode}
            onClick={() => switchInputMode("json")}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              jsonMode
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            JSON
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
            {error}
          </div>
        )}

        {jsonMode ? (
          <div className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]">
            <label className="block text-xs font-medium text-zinc-500">
              {t("settings.mcpJsonLabel") || "MCP server JSON"}
              <span className="mt-1 block text-[11px] font-normal leading-relaxed text-zinc-400">
                {t("settings.mcpJsonHint") ||
                  "Paste one or more servers keyed by name, as in config.yaml mcp_servers."}
              </span>
              <textarea
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
                spellCheck={false}
                autoComplete="off"
                rows={16}
                className="mt-2 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-xs leading-relaxed text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
            </label>
          </div>
        ) : (
        <div className="space-y-4 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]">
          <label className="block text-xs font-medium text-zinc-500">
            {t("settings.mcpFieldName") || "Server name"}
            <input
              type="text"
              value={form.name}
              readOnly={isEdit}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              autoComplete="off"
            />
          </label>

          <label className="block text-xs font-medium text-zinc-500">
            {t("settings.mcpTransport") || "Transport"}
            <select
              value={form.transport}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  transport: e.target.value as Transport,
                }))
              }
              className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              <option value="stdio">stdio</option>
              <option value="http">HTTP</option>
            </select>
          </label>

          {form.transport === "http" ? (
            <>
              <label className="block text-xs font-medium text-zinc-500">
                URL
                <input
                  type="text"
                  value={form.url}
                  onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                  placeholder="http://127.0.0.1:3000/mcp"
                  className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <McpAuthFields
                auth={form.auth}
                authConfigured={form.authConfigured}
                onChange={(auth) => setForm((f) => ({ ...f, auth }))}
              />
            </>
          ) : (
            <>
              <label className="block text-xs font-medium text-zinc-500">
                {t("settings.mcpCommand") || "Command"}
                <input
                  type="text"
                  value={form.command}
                  onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
              <label className="block text-xs font-medium text-zinc-500">
                {t("settings.mcpArgs") || "Arguments (comma-separated)"}
                <input
                  type="text"
                  value={form.args}
                  onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                  className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
                />
              </label>
            </>
          )}

          <label className="block text-xs font-medium text-zinc-500">
            {t("settings.mcpTimeout") || "Timeout (seconds)"}
            <input
              type="number"
              min={1}
              value={form.timeout}
              onChange={(e) => setForm((f) => ({ ...f, timeout: e.target.value }))}
              className="mt-1 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
          </label>

          <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              className="rounded border-zinc-300"
            />
            {t("settings.mcpEnabled") || "Enabled"}
          </label>
        </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancelForm}
            className="rounded-lg px-4 py-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            {t("settings.mcpCancel") || "Cancel"}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("settings.mcpSave") || "Save"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {t("settings.mcpDesc") ||
            "Configure MCP servers stored in your active Hermes profile. Changes persist to config.yaml."}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void runDiscover()}
            disabled={loading || discovering}
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            title={t("settings.mcpRefresh") || "Refresh status"}
            aria-label="Refresh MCP servers"
          >
            <RefreshCw
              className={`h-4 w-4 ${loading || discovering ? "animate-spin" : ""}`}
            />
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500"
          >
            <Plus className="h-4 w-4" />
            {t("settings.mcpAddServer") || "Add server"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}

      {loading && servers.length === 0 ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("settings.mcpLoading") || "Loading MCP servers…"}
        </div>
      ) : servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-300 py-16 text-sm text-zinc-500 dark:border-zinc-800">
          <Plug className="h-8 w-8 opacity-40" />
          {t("settings.mcpEmpty") || "No MCP servers configured."}
        </div>
      ) : (
        <div className="space-y-3">
          {servers.map((server) => {
            const readOnly = isMcpServerReadOnly(server);
            const toolCount =
              typeof server.tool_count === "number" ? server.tool_count : null;
            return (
              <div
                key={server.name}
                className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-[#121212]"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        {server.name}
                      </span>
                      {readOnly ? (
                        <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[10px] uppercase text-zinc-500 dark:bg-zinc-800">
                          {t("chat.mcpSyncedFromDefault") || "Synced from default"}
                        </span>
                      ) : null}
                      <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-500 dark:bg-zinc-800">
                        {server.transport}
                      </span>
                      {server.auth_configured ? (
                        <span className="rounded-md bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase text-blue-700 dark:text-blue-300">
                          {mcpAuthLabel(detectMcpAuthType(server)) ||
                            t("settings.mcpAuthConfigured") ||
                            "Auth"}
                        </span>
                      ) : null}
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase ${statusBadgeClass(server)}`}
                      >
                        {server.status || (server.active ? "active" : "configured")}
                      </span>
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-zinc-500">
                      {serverDetail(server)}
                    </p>
                    {server.connect_error && (
                      <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                        {server.connect_error}
                      </p>
                    )}
                    {readOnly ? (
                      <p className="mt-1 text-xs text-zinc-500">{t("chat.mcpReadOnlyHint")}</p>
                    ) : null}
                    {toolCount !== null && toolCount > 0 && (
                      <p className="mt-1 text-xs text-zinc-500">
                        {toolCount} {t("chat.mcpTools") || "tools"}
                      </p>
                    )}
                    {(serverTools[server.name]?.length ?? 0) > 0 && (
                      <p className="mt-1 text-xs text-zinc-500">
                        {(t("settings.mcpTestTools") || "Test found {count} tools").replace(
                          "{count}",
                          String(serverTools[server.name]?.length ?? 0),
                        )}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={pendingTest === server.name}
                      onClick={() => void handleTest(server)}
                      className="rounded-lg px-2 py-1 text-[10px] font-bold uppercase tracking-wide bg-blue-500/15 text-blue-700 dark:text-blue-300 disabled:opacity-50"
                      title={t("settings.mcpTestConnection") || "Test connection"}
                    >
                      {pendingTest === server.name
                        ? t("settings.mcpTesting") || "Testing…"
                        : t("settings.mcpTest") || "Test"}
                    </button>
                    {toggleSupported && (
                      <button
                        type="button"
                        disabled={readOnly || pendingToggle === server.name}
                        onClick={() => void handleToggle(server)}
                        className={`rounded-lg px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${
                          server.enabled !== false
                            ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                            : "bg-zinc-500/15 text-zinc-600"
                        }`}
                      >
                        {server.enabled !== false
                          ? t("settings.active") || "Active"
                          : t("settings.mcpDisabled") || "Disabled"}
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={readOnly}
                      onClick={() => openEdit(server)}
                      className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-40"
                      title={t("settings.mcpEdit") || "Edit"}
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      disabled={readOnly || pendingDelete === server.name}
                      onClick={() => void handleDelete(server)}
                      className="rounded-lg p-2 text-zinc-500 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                      title={t("settings.mcpDelete") || "Delete"}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-zinc-500">
        {t("settings.mcpHint") ||
          "Use Refresh to probe servers and update connection status. Use Test to verify one server and list its tools. Use Profiles settings to manage per-profile configs."}
      </p>
    </div>
  );
};
