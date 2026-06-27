import type { ModelConfig } from "@/types";
import {
  configFromPickerModel,
  hydrateModelFromSettings,
  type PickerModel,
  type SettingsModelDefaults,
} from "@/services/hermes/models";

export type ReconcileModelSelectionInput = {
  current: ModelConfig;
  models: PickerModel[];
  /** Hermes config.yaml default from GET /settings (full load only). */
  serverDefaultId?: string;
  settings?: SettingsModelDefaults;
  localPinnedId?: string | null;
  catalogDefaultId?: string;
  activeProvider?: string;
  /**
   * Fresh boot only: profile/server default may beat empty composer state.
   * Catalog refresh and window focus must not reset an in-page selection.
   */
  preferBootDefault?: boolean;
};

export type ReconcileModelSelectionResult = {
  /** When null, keep current modelConfig unchanged. */
  nextConfig: ModelConfig | null;
  pinnedId: string | null;
  /** When set, sync localStorage pin key; undefined = leave storage unchanged. */
  pinStorageId?: string | null;
};

function modelInCatalog(models: PickerModel[], modelId: string): PickerModel | undefined {
  const id = modelId.trim();
  if (!id) return undefined;
  return models.find((m) => m.id === id);
}

/**
 * Decide whether loadModels should change composer model state (legacy
 * `_reconcileModelDropdownSelection` parity for Agent-UI).
 */
export function reconcileModelSelection(
  input: ReconcileModelSelectionInput,
): ReconcileModelSelectionResult {
  const {
    current,
    models,
    serverDefaultId = "",
    settings,
    localPinnedId = null,
    catalogDefaultId,
    activeProvider,
    preferBootDefault = false,
  } = input;

  const currentId = (current.modelId || "").trim();
  const currentInCatalog = currentId ? modelInCatalog(models, currentId) : undefined;

  if (currentInCatalog && !preferBootDefault) {
    return {
      nextConfig: null,
      pinnedId: localPinnedId,
    };
  }

  const pinnedId = (localPinnedId || "").trim();
  if (pinnedId) {
    const pinned = modelInCatalog(models, pinnedId);
    if (pinned) {
      return {
        nextConfig: configFromPickerModel(current, pinned, activeProvider),
        pinnedId,
      };
    }
  }

  const serverId = serverDefaultId.trim();
  if (preferBootDefault && serverId && settings) {
    const hydrated = hydrateModelFromSettings(
      current,
      settings,
      models,
      activeProvider,
    );
    if (hydrated) {
      return {
        nextConfig: hydrated,
        pinnedId: localPinnedId,
      };
    }
  }

  if (serverId && settings) {
    const hydrated = hydrateModelFromSettings(
      current,
      settings,
      models,
      activeProvider,
    );
    if (hydrated && (!currentId || !currentInCatalog)) {
      return {
        nextConfig: hydrated,
        pinnedId: localPinnedId,
      };
    }
  }

  const catalogDefault = (catalogDefaultId || "").trim();
  if (catalogDefault) {
    const matched = modelInCatalog(models, catalogDefault);
    if (matched && !currentId) {
      return {
        nextConfig: configFromPickerModel(current, matched, activeProvider),
        pinnedId: localPinnedId,
      };
    }
  }

  if (!currentId && models.length > 0) {
    return {
      nextConfig: configFromPickerModel(current, models[0], activeProvider),
      pinnedId: localPinnedId,
    };
  }

  return {
    nextConfig: null,
    pinnedId: localPinnedId,
  };
}
