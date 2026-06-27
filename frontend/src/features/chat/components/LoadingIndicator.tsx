import React from "react";
import { Loader2 } from "lucide-react";
import { AIIcon } from "./AIIcon";
import { ModelConfig } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";

interface LoadingIndicatorProps {
  modelConfig: ModelConfig;
}

export const LoadingIndicator: React.FC<LoadingIndicatorProps> = ({
  modelConfig,
}) => {
  const { t } = useLanguage();

  return (
    <div className="flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-300 items-start">
      <div className="mb-2 flex items-center gap-2 px-1">
        <div className="w-6 h-6 rounded-full bg-linear-to-br from-[#1447E6] to-[#0d35b8] flex items-center justify-center">
          <AIIcon size="sm" className="text-white w-3 h-3" />
        </div>
        <span className="text-xs text-zinc-500 font-medium">
          {modelConfig.name.toUpperCase()}
        </span>
      </div>
      <div className="pl-4 py-2 flex items-center gap-2 text-xs text-zinc-500">
        <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
        <span>{t("chat.thinking")}</span>
        <div className="flex space-x-1.5" aria-hidden="true">
          <div className="w-1.5 h-1.5 bg-zinc-400 dark:bg-zinc-600 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
          <div className="w-1.5 h-1.5 bg-zinc-400 dark:bg-zinc-600 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
          <div className="w-1.5 h-1.5 bg-zinc-400 dark:bg-zinc-600 rounded-full animate-bounce"></div>
        </div>
      </div>
    </div>
  );
};
