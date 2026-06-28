import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  KeyRound,
  Loader2,
  Server,
  Sparkles,
  X,
} from "lucide-react";
import { HermesApiError } from "@/lib/api";
import { saveSettings } from "@/features/settings/services/hermesSettings";
import { addWorkspace } from "@/services/hermes/workspace";
import {
  fetchOnboardingOAuthPoll,
  fetchOnboardingStatus,
  postOnboardingComplete,
  postOnboardingOAuthCancel,
  postOnboardingOAuthStart,
  postOnboardingProbe,
  postOnboardingSetup,
  type OnboardingSetupProvider,
  type OnboardingStatus,
} from "./api";

const STEPS = ["provider", "workspace", "password", "finish"] as const;
type StepKey = (typeof STEPS)[number];

type ProbeState = {
  status: "idle" | "probing" | "ok" | "error";
  error: string | null;
  detail: string;
  models: { id: string; label: string }[] | null;
  probedKey: string;
};

const STEP_META: Record<
  StepKey,
  { title: string; description: string }
> = {
  provider: {
    title: "Connect a provider",
    description: "Choose your model provider and credentials.",
  },
  workspace: {
    title: "Workspace & model",
    description: "Pick where Hermes works and your default model.",
  },
  password: {
    title: "Protect the Web UI",
    description: "Optional password for browser access.",
  },
  finish: {
    title: "Ready to go",
    description: "Review your setup and open Hermes.",
  },
};

function probeKey(provider: string, baseUrl: string, apiKey: string): string {
  return `${provider}|${baseUrl.trim().replace(/\/+$/, "")}|${apiKey}`;
}

function getProvider(
  status: OnboardingStatus | null,
  id: string,
): OnboardingSetupProvider | undefined {
  return status?.setup.providers?.find((p) => p.id === id);
}

function modelChoices(
  status: OnboardingStatus | null,
  providerId: string,
  probe: ProbeState,
): { id: string; label: string }[] {
  const provider = getProvider(status, providerId);
  if (
    provider?.requires_base_url &&
    probe.status === "ok" &&
    probe.models &&
    probe.models.length > 0
  ) {
    return probe.models;
  }
  return provider?.models ?? [];
}

export type OnboardingOverlayProps = {
  onComplete: () => void;
};

export const OnboardingOverlay: React.FC<OnboardingOverlayProps> = ({
  onComplete,
}) => {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState(0);
  const [notice, setNotice] = useState<{ text: string; kind: "info" | "warn" | "success" } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const [provider, setProvider] = useState("openrouter");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [password, setPassword] = useState("");

  const [probe, setProbe] = useState<ProbeState>({
    status: "idle",
    error: null,
    detail: "",
    models: null,
    probedKey: "",
  });

  const [oauthFlowId, setOauthFlowId] = useState<string | null>(null);
  const [oauthUserCode, setOauthUserCode] = useState("");
  const [oauthVerificationUri, setOauthVerificationUri] = useState("");
  const [oauthBusy, setOauthBusy] = useState(false);
  const oauthPollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentStep = STEPS[step];

  const refreshStatus = useCallback(async () => {
    const next = await fetchOnboardingStatus();
    setStatus(next);
    const current = next.setup?.current ?? { provider: "openrouter", model: "", base_url: "" };
    setProvider(current.provider || "openrouter");
    setModel(next.settings.default_model || current.model || "");
    setWorkspace(
      next.workspaces.last ||
        next.settings.default_workspace ||
        next.workspaces.items[0]?.path ||
        "",
    );
    setBaseUrl(current.base_url || "");
    return next;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await refreshStatus();
      } catch {
        if (!cancelled) setNotice({ text: "Could not load setup status.", kind: "warn" });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  useEffect(() => {
    return () => {
      if (oauthPollRef.current) clearTimeout(oauthPollRef.current);
    };
  }, []);

  const selectedProvider = useMemo(
    () => (status ? getProvider(status, provider) : undefined),
    [status, provider],
  );

  const syncProviderDefaults = useCallback(
    (id: string) => {
      setProvider(id);
      const p = status ? getProvider(status, id) : undefined;
      if (!p) return;
      const choices = modelChoices(status, id, probe);
      if (!model || !choices.some((m) => m.id === model) || id === "custom") {
        setModel(p.default_model || choices[0]?.id || "");
      }
      if (p.requires_base_url) {
        setBaseUrl((prev) => prev || p.default_base_url || "");
      } else {
        setBaseUrl(p.default_base_url || "");
      }
      setProbe({ status: "idle", error: null, detail: "", models: null, probedKey: "" });
    },
    [status, model, probe],
  );

  const runProbe = useCallback(
    async (force = false): Promise<ProbeState["status"]> => {
      const p = status ? getProvider(status, provider) : undefined;
      if (!p?.requires_base_url) {
        setProbe({ status: "idle", error: null, detail: "", models: null, probedKey: "" });
        return "idle";
      }
      const trimmedBase = baseUrl.trim();
      if (!trimmedBase) {
        setProbe({ status: "idle", error: null, detail: "", models: null, probedKey: "" });
        return "idle";
      }
      const key = probeKey(provider, trimmedBase, apiKey.trim());
      if (!force && probe.probedKey === key && probe.status !== "probing") {
        return probe.status;
      }

      setProbe({ status: "probing", error: null, detail: "", models: null, probedKey: key });
      try {
        const res = await postOnboardingProbe({
          provider,
          base_url: trimmedBase,
          api_key: apiKey.trim() || undefined,
        });
        if (res.ok) {
          const models = Array.isArray(res.models) ? res.models : [];
          setProbe({ status: "ok", error: null, detail: "", models, probedKey: key });
          if (!model || !models.some((m) => m.id === model)) {
            if (models[0]?.id) setModel(models[0].id);
          }
          return "ok";
        }
        setProbe({
          status: "error",
          error: res.error || "unreachable",
          detail: res.detail || "",
          models: null,
          probedKey: key,
        });
        return "error";
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setProbe({
          status: "error",
          error: "unreachable",
          detail: message,
          models: null,
          probedKey: key,
        });
        return "error";
      }
    },
    [status, provider, baseUrl, apiKey, model, probe.probedKey, probe.status],
  );

  const probeDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleProbe = useCallback(() => {
    if (probeDebounceRef.current) clearTimeout(probeDebounceRef.current);
    probeDebounceRef.current = setTimeout(() => void runProbe(), 400);
  }, [runProbe]);

  const clearOauthPoll = useCallback(() => {
    if (oauthPollRef.current) {
      clearTimeout(oauthPollRef.current);
      oauthPollRef.current = null;
    }
  }, []);

  const pollOauth = useCallback(
    async (flowId: string) => {
      try {
        const resp = await fetchOnboardingOAuthPoll(flowId);
        if (resp.status === "pending") {
          oauthPollRef.current = setTimeout(() => void pollOauth(flowId), 3000);
          return;
        }
        clearOauthPoll();
        setOauthFlowId(null);
        setOauthBusy(false);
        if (resp.status === "success") {
          setNotice({ text: "OAuth login succeeded. Refreshing status…", kind: "success" });
          await refreshStatus();
        } else if (resp.status === "expired") {
          setNotice({ text: "OAuth code expired. Start again when ready.", kind: "warn" });
        } else if (resp.status === "cancelled") {
          setNotice({ text: "OAuth login cancelled.", kind: "info" });
        } else {
          setNotice({
            text: resp.error || "OAuth login failed.",
            kind: "warn",
          });
        }
      } catch (err) {
        clearOauthPoll();
        setOauthFlowId(null);
        setOauthBusy(false);
        setNotice({
          text: err instanceof Error ? err.message : "OAuth poll failed.",
          kind: "warn",
        });
      }
    },
    [clearOauthPoll, refreshStatus],
  );

  const startCodexOAuth = async () => {
    setOauthBusy(true);
    setNotice(null);
    try {
      const resp = await postOnboardingOAuthStart({ provider: "openai-codex" });
      if (!resp.ok || !resp.flow_id) {
        throw new Error(resp.error || "Could not start OAuth flow.");
      }
      setOauthFlowId(resp.flow_id);
      setOauthUserCode(resp.user_code || "");
      setOauthVerificationUri(resp.verification_uri || "");
      oauthPollRef.current = setTimeout(() => void pollOauth(resp.flow_id!), 3000);
    } catch (err) {
      setOauthBusy(false);
      setNotice({
        text: err instanceof Error ? err.message : "OAuth start failed.",
        kind: "warn",
      });
    }
  };

  const cancelCodexOAuth = async () => {
    const flowId = oauthFlowId;
    clearOauthPoll();
    setOauthFlowId(null);
    setOauthBusy(false);
    if (flowId) {
      try {
        await postOnboardingOAuthCancel({ flow_id: flowId });
      } catch {
        /* best effort */
      }
    }
    setNotice({ text: "OAuth login cancelled.", kind: "info" });
  };

  const saveProviderSetup = async () => {
    if (!status) return;
    const trimmedProvider = provider.trim();
    const trimmedModel = model.trim();
    const trimmedKey = apiKey.trim();
    const trimmedBase = baseUrl.trim();
    const current = status.setup.current;
    const unchanged =
      current.provider === trimmedProvider &&
      (current.model || "") === trimmedModel &&
      (current.base_url || "") === trimmedBase;
    const currentIsOauth = !!status.setup.current_is_oauth;
    if (
      unchanged &&
      !trimmedKey &&
      (status.system.chat_ready || currentIsOauth)
    ) {
      return;
    }
    const body: Parameters<typeof postOnboardingSetup>[0] = {
      provider: trimmedProvider,
      model: trimmedModel,
    };
    if (trimmedKey) body.api_key = trimmedKey;
    if (trimmedBase) body.base_url = trimmedBase;
    try {
      const next = await postOnboardingSetup(body);
      setStatus(next);
    } catch (err) {
      if (err instanceof HermesApiError && err.status === 409) {
        const bodyWithConfirm = { ...body, confirm_overwrite: true };
        const next = await postOnboardingSetup(bodyWithConfirm);
        setStatus(next);
        return;
      }
      throw err;
    }
  };

  const saveDefaults = async () => {
    const trimmedWorkspace = workspace.trim();
    const trimmedModel = model.trim();
    const trimmedPassword = password.trim();
    if (!trimmedWorkspace) throw new Error("Choose a workspace path.");
    if (!trimmedModel) throw new Error("Choose a default model.");

    const known = (status?.workspaces.items ?? []).some((ws) => ws.path === trimmedWorkspace);
    if (!known) {
      await addWorkspace(trimmedWorkspace);
    }

    const body: Record<string, unknown> = { default_workspace: trimmedWorkspace };
    if (trimmedPassword) body._set_password = trimmedPassword;
    const saved = await saveSettings(body);
    setStatus((prev) =>
      prev
        ? {
            ...prev,
            settings: {
              ...prev.settings,
              password_enabled: !!saved.auth_enabled,
            },
          }
        : prev,
    );
    try {
      localStorage.setItem("hermes-webui-model", trimmedModel);
    } catch {
      /* quota */
    }
  };

  const finishWizard = async () => {
    await saveProviderSetup();
    await saveDefaults();
    const done = await postOnboardingComplete();
    setStatus(done);
    onComplete();
  };

  const skipWizard = async () => {
    setBusy(true);
    setNotice(null);
    try {
      await postOnboardingComplete();
      onComplete();
    } catch (err) {
      setNotice({
        text: err instanceof Error ? err.message : "Could not skip setup.",
        kind: "warn",
      });
    } finally {
      setBusy(false);
    }
  };

  const validateStep = async (): Promise<boolean> => {
    setNotice(null);
    if (currentStep === "provider") {
      if (!provider.trim()) {
        setNotice({ text: "Select a provider.", kind: "warn" });
        return false;
      }
      if (provider === "custom" && !baseUrl.trim()) {
        setNotice({ text: "Base URL is required for custom providers.", kind: "warn" });
        return false;
      }
      const p = getProvider(status, provider);
      if (p?.requires_base_url) {
        if (!baseUrl.trim()) {
          setNotice({ text: "Base URL is required.", kind: "warn" });
          return false;
        }
        const probeResult = await runProbe(true);
        if (probeResult !== "ok") {
          setNotice({
            text: "Could not reach the configured base URL. Run Test connection first.",
            kind: "warn",
          });
          return false;
        }
      }
      const needsKey = p && !p.key_optional && !status?.setup.current_is_oauth;
      if (needsKey && !apiKey.trim() && !status?.system.chat_ready) {
        setNotice({ text: "API key is required for this provider.", kind: "warn" });
        return false;
      }
    }
    if (currentStep === "workspace") {
      if (!workspace.trim()) {
        setNotice({ text: "Workspace path is required.", kind: "warn" });
        return false;
      }
      if (!model.trim()) {
        setNotice({ text: "Default model is required.", kind: "warn" });
        return false;
      }
    }
    return true;
  };

  const goNext = async () => {
    if (!(await validateStep())) return;
    if (step >= STEPS.length - 1) {
      setBusy(true);
      try {
        await finishWizard();
      } catch (err) {
        setNotice({
          text: err instanceof Error ? err.message : "Setup failed.",
          kind: "warn",
        });
      } finally {
        setBusy(false);
      }
      return;
    }
    setStep((s) => s + 1);
  };

  const goBack = () => {
    if (step === 0) return;
    setNotice(null);
    setStep((s) => s - 1);
  };

  const copyOAuthCode = async () => {
    try {
      await navigator.clipboard.writeText(oauthUserCode);
      setNotice({ text: "Code copied to clipboard.", kind: "success" });
    } catch {
      setNotice({ text: oauthUserCode, kind: "info" });
    }
  };

  const renderProviderStep = () => {
    if (!status) return null;
    const system = status.system;
    const setup = status.setup;
    const currentIsOauth = !!setup.current_is_oauth;
    const currentProviderName = setup.current.provider || "";
    const showCodexOAuth =
      currentIsOauth &&
      currentProviderName === "openai-codex" &&
      !system.chat_ready;

    const groupedOptions = (setup.categories?.length ?? 0)
      ? setup.categories!.map((cat) => {
          const opts = cat.providers
            .map((pid) => setup.providers?.find((p) => p.id === pid))
            .filter(Boolean) as OnboardingSetupProvider[];
          return (
            <optgroup key={cat.id} label={cat.label}>
              {opts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                  {p.quick ? " — Quick setup" : ""}
                </option>
              ))}
            </optgroup>
          );
        })
      : (setup.providers ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.label}
          </option>
        ));

    const showBaseUrl = !!selectedProvider?.requires_base_url;
    const probeBanner =
      probe.status !== "idle" ? (
        <p
          className={`text-xs rounded-xl px-3 py-2 border ${
            probe.status === "ok"
              ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
              : probe.status === "probing"
                ? "bg-indigo-500/10 border-indigo-500/20 text-indigo-700 dark:text-indigo-300"
                : "bg-red-500/10 border-red-500/20 text-red-600 dark:text-red-300"
          }`}
        >
          {probe.status === "probing"
            ? "Testing connection…"
            : probe.status === "ok"
              ? `Connected. ${(probe.models ?? []).length} model(s) available.`
              : `Could not reach base URL${probe.detail ? `: ${probe.detail}` : ""}`}
        </p>
      ) : null;

    return (
      <div className="space-y-4">
        {currentIsOauth && (
          <div
            className={`rounded-2xl border p-4 flex gap-3 ${
              system.chat_ready
                ? "border-emerald-500/30 bg-emerald-500/5"
                : "border-amber-500/30 bg-amber-500/5"
            }`}
          >
            <CheckCircle2
              className={`w-5 h-5 shrink-0 ${system.chat_ready ? "text-emerald-500" : "text-amber-500"}`}
            />
            <div className="text-sm space-y-2">
              <p className="font-medium text-zinc-900 dark:text-zinc-100">
                {system.chat_ready
                  ? `${currentProviderName} is authenticated`
                  : `${currentProviderName} needs authentication`}
              </p>
              {showCodexOAuth && (
                <div className="flex flex-wrap gap-2 items-center">
                  <button
                    type="button"
                    disabled={oauthBusy}
                    onClick={() => void startCodexOAuth()}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-60"
                  >
                    {oauthBusy ? "Starting…" : "Login with ChatGPT (Codex)"}
                  </button>
                  {oauthFlowId && (
                    <button
                      type="button"
                      onClick={() => void cancelCodexOAuth()}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium border border-zinc-300 dark:border-zinc-600"
                    >
                      Cancel OAuth
                    </button>
                  )}
                </div>
              )}
              {oauthUserCode && (
                <div className="rounded-xl bg-zinc-100 dark:bg-zinc-900/80 p-3 text-xs space-y-2">
                  <p>
                    Visit{" "}
                    <a
                      href={oauthVerificationUri}
                      target="_blank"
                      rel="noreferrer"
                      className="text-indigo-500 inline-flex items-center gap-1"
                    >
                      {oauthVerificationUri}
                      <ExternalLink className="w-3 h-3" />
                    </a>{" "}
                    and enter code <strong>{oauthUserCode}</strong>
                  </p>
                  <button
                    type="button"
                    onClick={() => void copyOAuthCode()}
                    className="inline-flex items-center gap-1 text-indigo-500"
                  >
                    <Copy className="w-3 h-3" /> Copy code
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
            Provider
          </span>
          <select
            value={provider}
            onChange={(e) => syncProviderDefaults(e.target.value)}
            className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
          >
            {groupedOptions}
          </select>
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
            API key {selectedProvider?.key_optional ? "(optional)" : ""}
          </span>
          <div className="relative flex items-center bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3">
            <KeyRound className="w-5 h-5 text-zinc-400 shrink-0" />
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              onBlur={() => void runProbe()}
              placeholder={
                selectedProvider?.key_optional
                  ? "Leave empty for keyless servers"
                  : selectedProvider?.env_var
                    ? `Paste ${selectedProvider.env_var}`
                    : "API key"
              }
              className="w-full bg-transparent border-none outline-none ml-3 text-sm"
              autoComplete="off"
            />
          </div>
        </label>

        {showBaseUrl && (
          <>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
                Base URL
              </span>
              <div className="relative flex items-center bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3">
                <Server className="w-5 h-5 text-zinc-400 shrink-0" />
                <input
                  value={baseUrl}
                  onChange={(e) => {
                    setBaseUrl(e.target.value);
                    scheduleProbe();
                  }}
                  onBlur={() => void runProbe()}
                  placeholder="http://127.0.0.1:1234/v1"
                  className="w-full bg-transparent border-none outline-none ml-3 text-sm"
                />
              </div>
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={probe.status === "probing"}
                onClick={() => void runProbe(true)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border border-zinc-300 dark:border-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-60"
              >
                Test connection
              </button>
            </div>
            {probeBanner}
          </>
        )}

        {setup.unsupported_note && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{setup.unsupported_note}</p>
        )}
        {system.provider_note && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{system.provider_note}</p>
        )}
      </div>
    );
  };

  const renderWorkspaceStep = () => {
    if (!status) return null;
    const choices = modelChoices(status, provider, probe);
    const workspaceOptions = (status.workspaces?.items?.length ?? 0)
      ? status.workspaces!.items
      : [{ name: "Home", path: workspace }];

    return (
      <div className="space-y-4">
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
            Workspace
          </span>
          <select
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
          >
            {workspaceOptions.map((ws) => (
              <option key={ws.path} value={ws.path}>
                {(ws.name || ws.path) + " — " + ws.path}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
            Or enter path
          </span>
          <input
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            placeholder="/path/to/workspace"
            className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
          />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
            Default model
          </span>
          {provider === "custom" ? (
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="provider/model-id"
              className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
            />
          ) : (
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
            >
              {choices.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
        </label>
      </div>
    );
  };

  const renderPasswordStep = () => (
    <div className="space-y-4">
      <label className="block space-y-1.5">
        <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide ml-1">
          Web UI password (optional)
        </span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Leave empty to skip"
          className="w-full bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3 text-sm"
          autoComplete="new-password"
        />
      </label>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Recommended when exposing Hermes on a network. You can change this later in settings.
      </p>
    </div>
  );

  const renderFinishStep = () => {
    const p = status ? getProvider(status, provider) : undefined;
    const passwordSummary = password.trim()
      ? status?.settings.password_enabled
        ? "Will replace existing password"
        : "Will enable password protection"
      : status?.settings.password_enabled
        ? "Keep existing password"
        : "No password (open access)";

    return (
      <div className="space-y-4">
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-200 dark:divide-zinc-800 text-sm">
          <div className="flex justify-between gap-4 px-4 py-3">
            <span className="text-zinc-500">Provider</span>
            <span className="font-medium text-right">{p?.label || provider || "—"}</span>
          </div>
          <div className="flex justify-between gap-4 px-4 py-3">
            <span className="text-zinc-500">Model</span>
            <span className="font-medium text-right break-all">{model || "—"}</span>
          </div>
          <div className="flex justify-between gap-4 px-4 py-3">
            <span className="text-zinc-500">Workspace</span>
            <span className="font-medium text-right break-all">{workspace || "—"}</span>
          </div>
          <div className="flex justify-between gap-4 px-4 py-3">
            <span className="text-zinc-500">Password</span>
            <span className="font-medium text-right">{passwordSummary}</span>
          </div>
        </div>
        {baseUrl && (
          <p className="text-xs text-zinc-500">
            <strong>Base URL:</strong> {baseUrl}
          </p>
        )}
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Hermes will save provider credentials, workspace defaults, and mark setup complete.
        </p>
      </div>
    );
  };

  const stepBody = () => {
    switch (currentStep) {
      case "provider":
        return renderProviderStep();
      case "workspace":
        return renderWorkspaceStep();
      case "password":
        return renderPasswordStep();
      case "finish":
        return renderFinishStep();
      default:
        return null;
    }
  };

  if (loading) {
    return (
      <div
        className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        aria-label="Hermes setup"
      >
        <Loader2 className="w-8 h-8 animate-spin text-indigo-400" />
      </div>
    );
  }

  const meta = STEP_META[currentStep];

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Hermes setup wizard"
    >
      <div className="w-full max-w-2xl relative">
        <button
          type="button"
          onClick={() => void skipWizard()}
          disabled={busy}
          className="absolute -top-10 right-0 text-xs text-zinc-400 hover:text-white flex items-center gap-1 disabled:opacity-50"
        >
          <X className="w-3.5 h-3.5" /> Skip setup
        </button>

        <div className="relative overflow-hidden rounded-[2rem] border border-white/20 dark:border-zinc-800 shadow-2xl bg-white dark:bg-[#18181b]">
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-zinc-400/50 dark:via-white/20 to-transparent" />

          <div className="p-8 pb-4 border-b border-zinc-100 dark:border-zinc-800/80">
            <div className="flex items-center gap-4 mb-6">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl blur opacity-30" />
                <div className="relative w-12 h-12 bg-gradient-to-br from-white to-zinc-100 dark:from-[#1a1a1e] dark:to-[#0d0d10] rounded-2xl flex items-center justify-center border border-white/50 dark:border-white/10">
                  <Sparkles className="w-6 h-6 text-indigo-500 dark:text-indigo-400" />
                </div>
              </div>
              <div>
                <h2 className="text-xl font-bold text-zinc-900 dark:text-white tracking-tight">
                  Welcome to Hermes
                </h2>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  First-run setup — step {step + 1} of {STEPS.length}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {STEPS.map((key, idx) => {
                const m = STEP_META[key];
                const active = idx === step;
                const done = idx < step;
                return (
                  <div
                    key={key}
                    className={`rounded-xl px-3 py-2 border text-left transition-colors ${
                      active
                        ? "border-indigo-500/50 bg-indigo-500/10"
                        : done
                          ? "border-emerald-500/30 bg-emerald-500/5"
                          : "border-zinc-200 dark:border-zinc-800 opacity-60"
                    }`}
                  >
                    <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                      {idx + 1}
                    </div>
                    <div className="text-xs font-semibold text-zinc-800 dark:text-zinc-200 truncate">
                      {m.title}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="px-8 py-6 min-h-[280px]">
            <h3 className="text-lg font-semibold text-zinc-900 dark:text-white mb-1">
              {meta.title}
            </h3>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5">{meta.description}</p>

            {notice && (
              <div
                className={`flex items-start gap-2 text-xs p-3 rounded-xl border mb-4 ${
                  notice.kind === "success"
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
                    : notice.kind === "warn"
                      ? "bg-amber-500/10 border-amber-500/20 text-amber-700 dark:text-amber-300"
                      : "bg-zinc-500/10 border-zinc-500/20 text-zinc-600 dark:text-zinc-300"
                }`}
              >
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{notice.text}</span>
              </div>
            )}

            {stepBody()}
          </div>

          <div className="px-8 pb-8 flex gap-3">
            <button
              type="button"
              onClick={goBack}
              disabled={step === 0 || busy}
              className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              type="button"
              onClick={() => void goNext()}
              disabled={busy}
              className="relative flex-1 group overflow-hidden rounded-xl p-px focus:outline-none focus:ring-2 focus:ring-indigo-500/50 disabled:opacity-70"
            >
              <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 bg-[length:200%_100%]" />
              <span className="relative flex items-center justify-center gap-2 w-full bg-white dark:bg-[#131316] group-hover:bg-transparent group-hover:text-white text-zinc-900 dark:text-white py-3 rounded-[11px] font-semibold text-sm transition-colors">
                {busy ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  <>
                    {step === STEPS.length - 1 ? "Open Hermes" : "Continue"}
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
