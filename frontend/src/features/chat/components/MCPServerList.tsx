import React from "react";
import {
  Loader2,
  Pencil,
  Plug,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { ConfirmModal } from "@/components/ConfirmModal";
import { useLanguage } from "@/hooks/useLanguage";
import {
  deleteMcpServer,
  discoverMcpServers,
  isMcpServerReadOnly,
  listMcpServers,
  listMcpTools,
  toggleMcpServer,
  updateMcpServer,
  type HermesMcpServer,
  type HermesMcpTool,
} from "@/services/hermes/mcp";
import { McpAuthFields } from "@/features/mcp/McpAuthFields";
import {
  buildMcpAuthPayload,
  detectMcpAuthType,
  mcpAuthFormFromServer,
  mcpAuthLabel,
  type McpAuthFormState,
} from "@/features/mcp/mcpAuth";

interface MCPServerListProps {
  isOpen: boolean;
  onToggle: () => void;
  menuRef: React.RefObject<HTMLDivElement | null>;
}

type Transport = "stdio" | "http";

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

function statusDotClass(server: HermesMcpServer): string {
  if (!server.enabled) return "bg-zinc-400 dark:bg-zinc-600";
  if (server.active) return "bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.5)]";
  return "bg-amber-500 shadow-[0_0_5px_rgba(245,158,11,0.4)]";
}

function statusLabel(server: HermesMcpServer): string {
  if (server.status) return server.status;
  if (!server.enabled) return "disabled";
  return server.active ? "active" : "configured";
}

function formFromServer(server: HermesMcpServer): FormState {
  const transport: Transport = server.transport === "http" ? "http" : "stdio";
  return {
    name: server.name,
    transport,
    command: server.command || "",
    args: "",
    url: server.url || "",
    timeout: "120",
    enabled: server.enabled !== false,
    auth: mcpAuthFormFromServer(server),
    existingHeaders: server.headers,
    authConfigured: server.auth_configured === true,
  };
}

export const MCPServerList: React.FC<MCPServerListProps> = ({
  isOpen,
  onToggle,
  menuRef,
}) => {
  const { t } = useLanguage();
  const [servers, setServers] = React.useState<HermesMcpServer[]>([]);
  const [tools, setTools] = React.useState<HermesMcpTool[]>([]);
  const [toggleSupported, setToggleSupported] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [formMode, setFormMode] = React.useState<"list" | "create" | "edit">("list");
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = React.useState(false);
  const [pendingAction, setPendingAction] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<HermesMcpServer | null>(null);

  const activeCount = servers.filter((s) => s.enabled && s.active).length;

  const loadInventory = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [serversResp, toolsResp] = await Promise.all([
        listMcpServers(),
        listMcpTools(),
      ]);
      setServers(serversResp.servers);
      setTools(toolsResp.tools);
      setToggleSupported(serversResp.toggle_supported !== false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load MCP servers");
      setServers([]);
      setTools([]);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (isOpen) void loadInventory();
  }, [isOpen, loadInventory]);

  React.useEffect(() => {
    if (!isOpen) {
      setFormMode("list");
      setForm(EMPTY_FORM);
      setError(null);
      setDeleteTarget(null);
    }
  }, [isOpen]);

  const toolsByServer = React.useMemo(() => {
    const map = new Map<string, HermesMcpTool[]>();
    for (const tool of tools) {
      const key = tool.server || "unknown";
      const list = map.get(key) ?? [];
      list.push(tool);
      map.set(key, list);
    }
    return map;
  }, [tools]);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormMode("create");
    setError(null);
  };

  const openEdit = (server: HermesMcpServer) => {
    if (isMcpServerReadOnly(server)) return;
    setForm(formFromServer(server));
    setFormMode("edit");
    setError(null);
  };

  const cancelForm = () => {
    setForm(EMPTY_FORM);
    setFormMode("list");
    setError(null);
  };

  const handleSave = async () => {
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
        setError(
          t("settings.mcpCommandRequired") || "Command is required for stdio transport.",
        );
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
      await loadInventory();
      await discoverMcpServers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save MCP server");
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (server: HermesMcpServer) => {
    if (!toggleSupported || isMcpServerReadOnly(server) || pendingAction) return;
    setPendingAction(server.name);
    setError(null);
    try {
      await toggleMcpServer(server.name, server.enabled === false);
      await loadInventory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to toggle MCP server");
    } finally {
      setPendingAction(null);
    }
  };

  const handleDelete = (server: HermesMcpServer) => {
    if (isMcpServerReadOnly(server) || pendingAction) return;
    setDeleteTarget(server);
  };

  const submitDelete = async () => {
    if (!deleteTarget) return;
    const server = deleteTarget;
    setPendingAction(server.name);
    setError(null);
    try {
      await deleteMcpServer(server.name);
      await loadInventory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete MCP server");
    } finally {
      setPendingAction(null);
    }
  };

  const renderForm = () => {
    const isEdit = formMode === "edit";
    return (
      <div className="p-2 space-y-2 max-h-64 overflow-y-auto scrollbar-hide">
        <div className="flex items-center justify-between gap-2 px-1">
          <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">
            {isEdit
              ? t("settings.mcpEditServer") || "Edit MCP server"
              : t("settings.mcpAddServer") || "Add server"}
          </span>
          <button
            type="button"
            onClick={cancelForm}
            className="p-1 rounded-md text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            aria-label="Cancel"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        <label className="block px-1">
          <span className="text-[10px] font-medium text-zinc-500">
            {t("settings.mcpFieldName") || "Server name"}
          </span>
          <input
            type="text"
            value={form.name}
            readOnly={isEdit}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="mt-0.5 w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-xs"
            autoComplete="off"
          />
        </label>
        <label className="block px-1">
          <span className="text-[10px] font-medium text-zinc-500">
            {t("settings.mcpTransport") || "Transport"}
          </span>
          <select
            value={form.transport}
            onChange={(e) =>
              setForm((f) => ({ ...f, transport: e.target.value as Transport }))
            }
            className="mt-0.5 w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-xs"
          >
            <option value="stdio">stdio</option>
            <option value="http">HTTP</option>
          </select>
        </label>
        {form.transport === "http" ? (
          <>
            <label className="block px-1">
              <span className="text-[10px] font-medium text-zinc-500">URL</span>
              <input
                type="text"
                value={form.url}
                onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                placeholder="http://127.0.0.1:3000/mcp"
                className="mt-0.5 w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 font-mono text-xs"
              />
            </label>
            <div className="px-1">
              <McpAuthFields
                auth={form.auth}
                authConfigured={form.authConfigured}
                onChange={(auth) => setForm((f) => ({ ...f, auth }))}
              />
            </div>
          </>
        ) : (
          <>
            <label className="block px-1">
              <span className="text-[10px] font-medium text-zinc-500">
                {t("settings.mcpCommand") || "Command"}
              </span>
              <input
                type="text"
                value={form.command}
                onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                className="mt-0.5 w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 font-mono text-xs"
              />
            </label>
            <label className="block px-1">
              <span className="text-[10px] font-medium text-zinc-500">
                {t("settings.mcpArgs") || "Arguments"}
              </span>
              <input
                type="text"
                value={form.args}
                onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                className="mt-0.5 w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 font-mono text-xs"
              />
            </label>
          </>
        )}
        <label className="flex items-center gap-2 px-1 text-xs text-zinc-600 dark:text-zinc-300">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
            className="rounded border-zinc-300"
          />
          {t("settings.mcpEnabled") || "Enabled"}
        </label>
        <div className="flex gap-2 px-1 pt-1">
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="flex-1 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium py-1.5 disabled:opacity-60"
          >
            {saving ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin mx-auto" />
            ) : (
              t("settings.mcpSave") || "Save"
            )}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={cancelForm}
            className="flex-1 rounded-md border border-zinc-200 dark:border-zinc-700 text-xs py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            {t("settings.mcpCancel") || "Cancel"}
          </button>
        </div>
      </div>
    );
  };

  return (
    <>
    <div className="relative" ref={menuRef}>
      {isOpen && (
        <div className="absolute bottom-full mb-2 left-0 w-[min(20rem,calc(100vw-1.5rem))] max-h-[min(24rem,75vh)] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl z-50 flex flex-col animate-in slide-in-from-bottom-2 fade-in duration-200 overflow-hidden">
          <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-[10px] font-bold text-zinc-500 uppercase tracking-wider flex justify-between items-center">
            <span>{t("chat.mcpTitle")}</span>
            <span className="bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 px-1.5 rounded-sm">
              {loading ? "…" : servers.length}
            </span>
          </div>

          {error ? (
            <div className="mx-2 mt-2 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1.5 text-[10px] text-rose-600 dark:text-rose-300">
              {error}
            </div>
          ) : null}

          {formMode !== "list" ? (
            renderForm()
          ) : (
            <>
              <div className="p-2 max-h-56 overflow-y-auto scrollbar-hide">
                {loading && servers.length === 0 ? (
                  <div className="flex items-center justify-center gap-2 text-xs text-zinc-500 py-6">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>{t("chat.mcpLoading") || "Loading…"}</span>
                  </div>
                ) : servers.length === 0 ? (
                  <div className="text-xs text-zinc-500 text-center py-4 italic">
                    {t("chat.noServers") || "No servers connected"}
                  </div>
                ) : (
                  servers.map((server) => {
                    const readOnly = isMcpServerReadOnly(server);
                    const serverTools = toolsByServer.get(server.name) ?? [];
                    const toolCount =
                      typeof server.tool_count === "number"
                        ? server.tool_count
                        : serverTools.length;
                    const isBusy = pendingAction === server.name;

                    return (
                      <div
                        key={server.name}
                        className="flex flex-col gap-1 p-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors"
                      >
                        <div className="flex items-start gap-2 min-w-0">
                          <div
                            className={`w-1.5 h-1.5 rounded-full shrink-0 mt-1.5 ${statusDotClass(server)}`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-xs font-medium text-zinc-700 dark:text-zinc-300 truncate">
                                {server.name}
                              </span>
                              {readOnly ? (
                                <span className="text-[9px] uppercase tracking-wide rounded px-1 py-0.5 bg-zinc-200 dark:bg-zinc-800 text-zinc-500">
                                  {t("chat.mcpSyncedFromDefault") || "Synced"}
                                </span>
                              ) : null}
                            </div>
                            <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                              <span>{statusLabel(server)}</span>
                              <span className="uppercase">{server.transport}</span>
                              {server.auth_configured ? (
                                <span className="uppercase text-blue-600 dark:text-blue-400">
                                  · {mcpAuthLabel(detectMcpAuthType(server)) || "auth"}
                                </span>
                              ) : null}
                              {toolCount > 0 && (
                                <span>
                                  · {toolCount} {t("chat.mcpTools") || "tools"}
                                </span>
                              )}
                            </div>
                            {readOnly ? (
                              <p className="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                                {t("chat.mcpReadOnlyHint")}
                              </p>
                            ) : null}
                            {server.connect_error && (
                              <p className="text-[10px] text-amber-600 dark:text-amber-400 line-clamp-2 mt-0.5">
                                {server.connect_error}
                              </p>
                            )}
                          </div>
                          <div className="flex shrink-0 items-center gap-0.5">
                            {toggleSupported && (
                              <button
                                type="button"
                                disabled={readOnly || isBusy}
                                onClick={() => void handleToggle(server)}
                                className={`rounded-md px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide disabled:opacity-40 ${
                                  server.enabled !== false
                                    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                                    : "bg-zinc-500/15 text-zinc-600"
                                }`}
                                title={
                                  readOnly
                                    ? t("chat.mcpReadOnlyHint")
                                    : server.enabled !== false
                                      ? t("settings.mcpDisabled")
                                      : t("settings.mcpEnabled")
                                }
                              >
                                {isBusy ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : server.enabled !== false ? (
                                  t("settings.active") || "On"
                                ) : (
                                  t("settings.mcpDisabled") || "Off"
                                )}
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={readOnly || isBusy}
                              onClick={() => openEdit(server)}
                              className="p-1 rounded-md text-zinc-500 hover:text-indigo-600 hover:bg-white/80 dark:hover:bg-zinc-900/80 disabled:opacity-40"
                              title={t("settings.mcpEdit") || "Edit"}
                            >
                              <Pencil className="w-3 h-3" />
                            </button>
                            <button
                              type="button"
                              disabled={readOnly || isBusy}
                              onClick={() => handleDelete(server)}
                              className="p-1 rounded-md text-zinc-500 hover:text-red-600 hover:bg-white/80 dark:hover:bg-red-500/10 disabled:opacity-40"
                              title={t("settings.mcpDelete") || "Delete"}
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
              <div className="border-t border-zinc-200 dark:border-zinc-800 p-2">
                <button
                  type="button"
                  disabled={!!pendingAction || saving}
                  onClick={openCreate}
                  className="w-full flex items-center gap-2 p-2 rounded-lg text-left text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-950/20 disabled:opacity-60"
                >
                  <Plus className="w-3.5 h-3.5 shrink-0" />
                  <span>{t("chat.mcpAddServer") || t("settings.mcpAddServer")}</span>
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <button
        type="button"
        onClick={onToggle}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-full border transition-all ${
          isOpen || activeCount > 0
            ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-zinc-800 text-emerald-700 dark:text-emerald-400"
            : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400"
        }`}
        title={t("chat.mcpTitle")}
      >
        <Plug className="w-3.5 h-3.5" />
        {activeCount > 0 && (
          <span className="text-xs font-bold">{activeCount}</span>
        )}
      </button>
    </div>

    <ConfirmModal
      isOpen={deleteTarget !== null}
      onClose={() => setDeleteTarget(null)}
      onConfirm={submitDelete}
      title={t("settings.mcpDelete") || "Delete MCP server"}
      message={
        deleteTarget
          ? (t("settings.mcpDeleteConfirm") || 'Delete MCP server "{name}"?').replace(
              "{name}",
              deleteTarget.name,
            )
          : ""
      }
      confirmText={t("settings.mcpDelete") || "Delete"}
      cancelText={t("chat.workspaceCreateCancel") || "Cancel"}
      type="danger"
    />
    </>
  );
};
