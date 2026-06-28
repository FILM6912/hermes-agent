import { useEffect, useState, useRef, useCallback } from "react";
import { ModelConfig } from "@/types";
import { fetchSettings } from "@/features/settings/services/hermesSettings";
import { listPickerModels, PickerModel } from "@/services/hermes/models";
import { reconcileModelSelection } from "@/features/chat/modelSelection";

const PINNED_MODEL_KEY = "pinned_model_id";
/** Legacy Langflow pin key — read once for migration, then cleared on re-pin. */
const LEGACY_PINNED_AGENT_KEY = "pinned_agent_id";

interface UseAgentModelsProps {
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
  /** When false, skip model/settings fetches (e.g. login page). Default true. */
  enabled?: boolean;
}

function readPinnedModelId(): string | null {
  return (
    localStorage.getItem(PINNED_MODEL_KEY) ||
    localStorage.getItem(LEGACY_PINNED_AGENT_KEY)
  );
}

function writePinnedModelId(modelId: string | null): void {
  if (!modelId) {
    localStorage.removeItem(PINNED_MODEL_KEY);
    localStorage.removeItem(LEGACY_PINNED_AGENT_KEY);
    return;
  }
  localStorage.setItem(PINNED_MODEL_KEY, modelId);
  localStorage.removeItem(LEGACY_PINNED_AGENT_KEY);
}

export const useAgentModels = ({
  modelConfig,
  onModelConfigChange,
  enabled = true,
}: UseAgentModelsProps) => {
  const [agentModels, setAgentModels] = useState<PickerModel[]>([]);
  const [pinnedAgentId, setPinnedAgentId] = useState<string | null>(() => readPinnedModelId());
  const hasLoadedCatalogRef = useRef(false);

  const modelConfigRef = useRef(modelConfig);
  useEffect(() => {
    modelConfigRef.current = modelConfig;
  }, [modelConfig]);

  const applyReconcileResult = useCallback(
    (result: ReturnType<typeof reconcileModelSelection>) => {
      setPinnedAgentId(result.pinnedId);
      if (result.pinStorageId !== undefined) {
        writePinnedModelId(result.pinStorageId);
      }
      if (result.nextConfig) {
        const current = modelConfigRef.current;
        const next = result.nextConfig;
        if (
          next.modelId !== current.modelId ||
          next.modelProvider !== current.modelProvider ||
          next.name !== current.name
        ) {
          onModelConfigChange(next);
        }
      }
    },
    [onModelConfigChange],
  );

  const loadModels = useCallback(
    async (opts?: { modelsOnly?: boolean }) => {
      try {
        const pickerResult = await listPickerModels();
        const { models, defaultModelId, activeProvider } = pickerResult;
        setAgentModels(models);

        const current = modelConfigRef.current;
        const preferBootDefault =
          !hasLoadedCatalogRef.current && !(current.modelId || "").trim();
        hasLoadedCatalogRef.current = true;

        if (opts?.modelsOnly) {
          const result = reconcileModelSelection({
            current,
            models,
            localPinnedId: readPinnedModelId(),
            catalogDefaultId: defaultModelId,
            activeProvider,
            preferBootDefault: false,
          });
          applyReconcileResult(result);
          return;
        }

        const settings = await fetchSettings();
        const serverDefaultId =
          typeof settings.default_model === "string" ? settings.default_model.trim() : "";

        const result = reconcileModelSelection({
          current,
          models,
          serverDefaultId,
          settings,
          localPinnedId: readPinnedModelId(),
          catalogDefaultId: defaultModelId,
          activeProvider,
          preferBootDefault,
        });
        applyReconcileResult(result);
      } catch (error) {
        console.error("Failed to load Hermes models:", error);
        setAgentModels([]);
      }
    },
    [applyReconcileResult],
  );

  useEffect(() => {
    if (!enabled) return;

    loadModels();

    const handleFocus = () => {
      if (enabled) loadModels();
    };
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [loadModels, enabled]);

  const handlePinAgent = useCallback(
    (modelId: string) => {
      if (pinnedAgentId === modelId) {
        setPinnedAgentId(null);
        writePinnedModelId(null);
        return;
      }
      setPinnedAgentId(modelId);
      writePinnedModelId(modelId);
    },
    [pinnedAgentId],
  );

  return {
    agentModels,
    pinnedAgentId,
    handlePinAgent,
    reloadModels: loadModels,
  };
};
