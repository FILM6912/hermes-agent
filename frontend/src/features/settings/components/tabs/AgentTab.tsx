import React, { useCallback } from "react";
import { Check, Pin, PinOff } from "lucide-react";
import { ModelConfig } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { useAgentModels } from "@/features/chat/hooks/useAgentModels";
import { saveDefaultModel } from "@/features/settings/services/modelsSettingsApi";
import { configFromPickerModel, PickerModel } from "@/services/hermes/models";

interface AgentTabProps {
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
}

export const AgentTab: React.FC<AgentTabProps> = ({
  modelConfig,
  onModelConfigChange,
}) => {
  const { t } = useLanguage();
  const { agentModels, pinnedAgentId, handlePinAgent } = useAgentModels({
    modelConfig,
    onModelConfigChange,
  });

  const persistDefaultModel = useCallback(async (modelId: string) => {
    try {
      await saveDefaultModel(modelId);
    } catch (error) {
      console.error("Failed to save default model:", error);
    }
  }, []);

  const handleSelectModel = useCallback(
    (model: PickerModel) => {
      onModelConfigChange(configFromPickerModel(modelConfig, model));
      void persistDefaultModel(model.id);
    },
    [modelConfig, onModelConfigChange, persistDefaultModel],
  );

  const handlePinModel = useCallback(
    (modelId: string) => {
      handlePinAgent(modelId);
    },
    [handlePinAgent],
  );

  return (
    <div className="max-w-4xl space-y-6">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        {t("settings.agentDesc") || "Choose the default Hermes model for new chats."}
      </p>
      <div className="space-y-2">
        {agentModels.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 py-12 text-center text-sm text-zinc-500 dark:border-zinc-700">
            No models available from Hermes.
          </div>
        ) : (
          agentModels.map((model) => {
            const selected = modelConfig.modelId === model.id;
            return (
              <div
                key={model.id}
                className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${
                  selected
                    ? "border-indigo-500/50 bg-indigo-500/5 dark:bg-indigo-500/10"
                    : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#121212]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => handlePinModel(model.id)}
                  className={`rounded-lg p-1.5 ${
                    pinnedAgentId === model.id
                      ? "text-emerald-500"
                      : "text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
                  }`}
                  title={pinnedAgentId === model.id ? "Unpin default" : "Pin as default"}
                >
                  {pinnedAgentId === model.id ? (
                    <Pin className="h-4 w-4 fill-current" />
                  ) : (
                    <PinOff className="h-4 w-4" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => handleSelectModel(model)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                    {model.name}
                  </div>
                  <div className="truncate text-xs text-zinc-500">{model.desc}</div>
                </button>
                {selected && <Check className="h-4 w-4 shrink-0 text-indigo-500" />}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
