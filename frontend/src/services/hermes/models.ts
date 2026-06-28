import { fetchJson } from "@/lib/api";
import type { ModelConfig } from "@/types";

export type PickerModel = {
  id: string;
  name: string;
  desc: string;
  hermesProvider?: string;
  /** Legacy label from GET /models groups. */
  label?: string;
};

export type SettingsModelDefaults = {
  default_model?: string;
  default_model_provider?: string;
  [key: string]: unknown;
};

export type HermesProviderSummary = {
  id?: string;
  provider?: string;
  name?: string;
  display_name?: string;
  [key: string]: unknown;
};

export type PickerModelsResult = {
  models: PickerModel[];
  defaultModelId: string;
  activeProvider?: string;
};

type ModelsApiGroup = {
  provider?: string;
  provider_id?: string;
  models?: Array<{ id: string; label?: string }>;
  extra_models?: Array<{ id: string; label?: string }>;
};

type ModelsApiResponse = {
  groups?: ModelsApiGroup[];
  default_model?: string;
  active_provider?: string;
  configured_model_badges?: Record<string, { provider?: string }>;
};

function flattenGroupsToPickerModels(data: ModelsApiResponse): PickerModel[] {
  const models: PickerModel[] = [];
  const seen = new Set<string>();

  for (const group of data.groups ?? []) {
    const hermesProvider = group.provider_id?.trim() || group.provider?.trim() || undefined;
    const providerLabel = group.provider?.trim() || hermesProvider || "";
    const entries = [...(group.models ?? []), ...(group.extra_models ?? [])];

    for (const entry of entries) {
      const id = entry?.id?.trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const label = entry.label?.trim() || id;
      models.push({
        id,
        name: label,
        desc: providerLabel ? `${providerLabel} · ${id}` : id,
        hermesProvider,
        label,
      });
    }
  }

  if (models.length === 0) {
    const fallbackId = data.default_model?.trim();
    if (fallbackId) {
      models.push({
        id: fallbackId,
        name: fallbackId,
        desc: fallbackId,
        hermesProvider: data.active_provider?.trim() || undefined,
      });
    }
  }

  return models;
}

/** GET /api/v1/models — flatten provider groups for the composer picker. */
export async function listPickerModels(): Promise<PickerModelsResult> {
  try {
    const data = await fetchJson<ModelsApiResponse>("/models");
    return {
      models: flattenGroupsToPickerModels(data),
      defaultModelId: data.default_model?.trim() ?? "",
      activeProvider: data.active_provider?.trim() || undefined,
    };
  } catch {
    return { models: [], defaultModelId: "", activeProvider: undefined };
  }
}

export function configFromPickerModel(
  current: ModelConfig,
  picked: PickerModel,
  activeProvider?: string,
): ModelConfig {
  const name = picked.name || picked.label || picked.id;
  return {
    ...current,
    modelId: picked.id,
    name,
    modelProvider: picked.hermesProvider ?? activeProvider ?? current.modelProvider,
  };
}

export function hydrateModelFromSettings(
  current: ModelConfig,
  settings: SettingsModelDefaults,
  models: PickerModel[],
  activeProvider?: string,
): ModelConfig | null {
  const serverId = settings.default_model?.trim() ?? "";
  if (!serverId) return null;

  const matched = models.find((m) => m.id === serverId);
  if (matched) {
    return configFromPickerModel(current, matched, activeProvider);
  }

  const provider =
    (typeof settings.default_model_provider === "string"
      ? settings.default_model_provider.trim()
      : "") ||
    activeProvider ||
    current.modelProvider;

  return {
    ...current,
    modelId: serverId,
    name: serverId,
    modelProvider: provider || undefined,
  };
}

export function modelProviderForHermes(
  modelConfig: ModelConfig,
): string | undefined {
  const provider = modelConfig.modelProvider?.trim();
  return provider || undefined;
}
