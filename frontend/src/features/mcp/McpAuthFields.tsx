import React from "react";
import { useLanguage } from "@/hooks/useLanguage";
import type { McpAuthFormState, McpAuthType } from "./mcpAuth";

type Props = {
  auth: McpAuthFormState;
  onChange: (next: McpAuthFormState) => void;
  authConfigured?: boolean;
};

export const McpAuthFields: React.FC<Props> = ({ auth, onChange, authConfigured }) => {
  const { t } = useLanguage();

  const setAuthType = (authType: McpAuthType) => {
    onChange({ ...auth, authType, bearerToken: "", apiKeyValue: "" });
  };

  return (
    <div className="space-y-3 rounded-lg border border-zinc-200/80 bg-zinc-50/50 p-3 dark:border-zinc-700/80 dark:bg-zinc-900/40">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-zinc-500">
          {t("settings.mcpAuth") || "Authentication"}
        </span>
        {authConfigured && auth.authType !== "none" ? (
          <span className="rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium uppercase text-emerald-700 dark:text-emerald-300">
            {t("settings.mcpAuthConfigured") || "Configured"}
          </span>
        ) : null}
      </div>

      <label className="block text-xs font-medium text-zinc-500">
        {t("settings.mcpAuthType") || "Auth method"}
        <select
          value={auth.authType}
          onChange={(e) => setAuthType(e.target.value as McpAuthType)}
          className="mt-1 w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          <option value="none">{t("settings.mcpAuthNone") || "None"}</option>
          <option value="bearer">{t("settings.mcpAuthBearer") || "Bearer token"}</option>
          <option value="api_key">{t("settings.mcpAuthApiKey") || "API key header"}</option>
          <option value="oauth">{t("settings.mcpAuthOAuth") || "OAuth 2.1 (PKCE)"}</option>
        </select>
      </label>

      {auth.authType === "bearer" ? (
        <label className="block text-xs font-medium text-zinc-500">
          {t("settings.mcpBearerToken") || "Bearer token"}
          <input
            type="password"
            value={auth.bearerToken}
            onChange={(e) => onChange({ ...auth, bearerToken: e.target.value })}
            placeholder={
              authConfigured
                ? t("settings.mcpSecretKeep") || "Leave blank to keep existing token"
                : t("settings.mcpBearerPlaceholder") || "sk-…"
            }
            autoComplete="off"
            className="mt-1 w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
      ) : null}

      {auth.authType === "api_key" ? (
        <>
          <label className="block text-xs font-medium text-zinc-500">
            {t("settings.mcpApiKeyHeader") || "Header name"}
            <input
              type="text"
              value={auth.apiKeyHeader}
              onChange={(e) => onChange({ ...auth, apiKeyHeader: e.target.value })}
              placeholder="X-Api-Key"
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
          </label>
          <label className="block text-xs font-medium text-zinc-500">
            {t("settings.mcpApiKeyValue") || "Header value"}
            <input
              type="password"
              value={auth.apiKeyValue}
              onChange={(e) => onChange({ ...auth, apiKeyValue: e.target.value })}
              placeholder={
                authConfigured
                  ? t("settings.mcpSecretKeep") || "Leave blank to keep existing value"
                  : t("settings.mcpApiKeyPlaceholder") || "your-api-key"
              }
              autoComplete="off"
              className="mt-1 w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
          </label>
        </>
      ) : null}

      {auth.authType === "oauth" ? (
        <p className="text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
          {t("settings.mcpAuthOAuthHint") ||
            "OAuth runs in the browser on first connect (PKCE). No static token is stored in config.yaml."}
        </p>
      ) : null}
    </div>
  );
};
