/**
 * Hermes model catalog API — picker options from GET /api/v1/models.
 * Replaces Langflow GET /api/v1/flows for model selection (M07).
 */
import { fetchJson } from "@/lib/api";
import type { ModelConfig } from "@/types";

export type HermesModelEntry = {
  id: string;
  label: string;
  [key: string]: unknown;
};

export type HermesModelGroup = {
  provider: string;
  provider_id?: string;
  models: HermesModelEntry[];
  [key: string]: unknown;
};

export type HermesModelsResponse = {
  groups: HermesModelGroup[];
  default_model?: string;
  active_provider?: string;
  [key: string]: unknown;
};

/** Flattened row for ModelSelector / useAgentModels. */
export type PickerModel = {
  id: string;
  name: string;
  desc: string;
  /** Hermes `provider_id` for chat/session `model_provider`. */
  hermesProvider?: string;
  providerId?: string;
};

export type HermesProviderSummary = {
  provider: string;
  display_name?: string;
  configured?: boolean;
  has_key?: boolean;
  [key: string]: unknown;
};

export type HermesProvidersResponse = {
  providers: HermesProviderSummary[];
  [key: string]: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Narrow unknown JSON to a models catalog with at least `groups`. */
export function narrowModelsResponse(value: unknown): HermesModelsResponse {
  if (!isRecord(value) || !Array.isArray(value.groups)) {
    return { groups: [] };
  }

  const groups = value.groups
    .filter(isRecord)
    .map((group) => ({
      ...group,
      provider: typeof group.provider === "string" ? group.provider : "",
      provider_id: typeof group.provider_id === "string" ? group.provider_id : undefined,
      models: Array.isArray(group.models)
        ? group.models
            .filter(isRecord)
            .map((model) => ({
              ...model,
              id: typeof model.id === "string" ? model.id : "",
              label:
                typeof model.label === "string"
                  ? model.label
                  : typeof model.id === "string"
                    ? model.id
                    : "",
            }))
            .filter((model) => model.id)
        : [],
    }))
    .filter((group) => group.models.length > 0);

  return {
    ...value,
    groups,
    default_model: typeof value.default_model === "string" ? value.default_model : undefined,
    active_provider:
      typeof value.active_provider === "string" ? value.active_provider : undefined,
  };
}

/** Flatten provider groups into picker rows (provider name as description). */
export function modelsToPickerOptions(catalog: HermesModelsResponse): PickerModel[] {
  const options: PickerModel[] = [];
  for (const group of catalog.groups) {
    if (!isRecord(group)) continue;
    if (group.models_endpoint_error) continue;
    const providerLabel = group.provider || group.provider_id || "Unknown provider";
    for (const model of group.models) {
      const providerId =
        typeof group.provider_id === "string" ? group.provider_id.trim() : "";
      options.push({
        id: model.id,
        name: model.label || model.id,
        desc: providerLabel,
        hermesProvider: providerId || undefined,
        providerId: providerId || undefined,
      });
    }
  }
  return options;
}

/** GET /api/v1/models — full Hermes model catalog. */
export async function listModels(): Promise<HermesModelsResponse> {
  const raw = await fetchJson<unknown>("/models");
  return narrowModelsResponse(raw);
}

/** GET /api/v1/providers — configured provider summaries (settings panel parity). */
export async function listProviders(): Promise<HermesProvidersResponse> {
  const raw = await fetchJson<unknown>("/providers");
  if (!isRecord(raw) || !Array.isArray(raw.providers)) {
    return { providers: [] };
  }
  return { providers: raw.providers.filter(isRecord) as HermesProviderSummary[] };
}

/** Provider slug for Hermes APIs — only when explicitly chosen from the catalog. */
export function modelProviderForHermes(config: ModelConfig): string | undefined {
  const id = config.modelProvider?.trim();
  return id || undefined;
}

/** Apply a picker row (and optional catalog active_provider) onto ModelConfig. */
export function configFromPickerModel(
  current: ModelConfig,
  model: PickerModel,
  catalogActiveProvider?: string,
): ModelConfig {
  const catalogProvider = catalogActiveProvider?.trim();
  return {
    ...current,
    modelId: model.id,
    name: model.name,
    modelProvider: model.hermesProvider || catalogProvider || undefined,
  };
}

export type SettingsModelDefaults = {
  default_model?: unknown;
  default_model_provider?: unknown;
};

/** Hydrate ModelConfig from GET /settings default_model fields (catalog supplement). */
export function hydrateModelFromSettings(
  current: ModelConfig,
  settings: SettingsModelDefaults,
  models: PickerModel[],
  catalogActiveProvider?: string,
): ModelConfig | null {
  const defaultModelId =
    typeof settings.default_model === "string" ? settings.default_model.trim() : "";
  if (!defaultModelId) return null;

  const settingsProvider =
    typeof settings.default_model_provider === "string"
      ? settings.default_model_provider.trim()
      : undefined;
  const catalogProvider = catalogActiveProvider?.trim();
  const matched = models.find((m) => m.id === defaultModelId);

  if (matched) {
    return configFromPickerModel(
      current,
      matched,
      settingsProvider || catalogProvider,
    );
  }

  return {
    ...current,
    modelId: defaultModelId,
    name: current.name && current.name !== "Select Agent" ? current.name : defaultModelId,
    modelProvider: settingsProvider || catalogProvider || undefined,
  };
}

/** Convenience: catalog flattened for the chat model picker. */
export async function listPickerModels(): Promise<{
  models: PickerModel[];
  defaultModelId?: string;
  activeProvider?: string;
}> {
  const catalog = await listModels();
  return {
    models: modelsToPickerOptions(catalog),
    defaultModelId: catalog.default_model,
    activeProvider: catalog.active_provider,
  };
}
