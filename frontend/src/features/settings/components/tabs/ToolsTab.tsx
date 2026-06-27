import React, { useState } from "react";
import {
  Plus,
  Wrench,
  Play,
  List,
  CheckSquare,
  Check,
  Pencil,
  Trash2,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { ModelConfig } from "@/types";

interface ToolsTabProps {
  modelConfig: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
}

export const ToolsTab: React.FC<ToolsTabProps> = ({
  modelConfig,
  onModelConfigChange,
}) => {
  const { t } = useLanguage();
  const [mcpInput, setMcpInput] = useState("");

  const handleAddMcp = () => {
    if (!mcpInput.trim()) return;
    const currentServers = modelConfig.mcpServers || [];
    if (!currentServers.includes(mcpInput)) {
      onModelConfigChange({
        ...modelConfig,
        mcpServers: [...currentServers, mcpInput],
      });
    }
    setMcpInput("");
  };

  const handleRemoveMcp = (server: string) => {
    const currentServers = modelConfig.mcpServers || [];
    onModelConfigChange({
      ...modelConfig,
      mcpServers: currentServers.filter((s) => s !== server),
    });
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex justify-between items-center mb-6">
        <p className="text-zinc-500 dark:text-zinc-400 text-sm">
          {t("settings.toolsDesc")}
        </p>
        <div className="flex gap-3">
          <div className="relative group">
            <input
              type="text"
              value={mcpInput}
              onChange={(e) => setMcpInput(e.target.value)}
              placeholder="http://192.168.99.1:9000/mcp"
              className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-700 dark:text-zinc-300 focus:outline-none focus:border-blue-500 w-72 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 font-mono shadow-sm dark:shadow-none"
              onKeyDown={(e) => e.key === "Enter" && handleAddMcp()}
            />
          </div>
          <button
            onClick={handleAddMcp}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition-colors shadow-lg shadow-blue-500/20"
          >
            <Plus className="w-4 h-4" />
            {t("settings.addTool")}
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {!modelConfig.mcpServers || modelConfig.mcpServers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-400 dark:text-zinc-500 text-sm border border-dashed border-zinc-300 dark:border-zinc-800 rounded-xl bg-zinc-50 dark:bg-[#121212]/50">
            <Wrench className="w-8 h-8 mb-3 opacity-50" />
            <span>{t("settings.noTools")}</span>
          </div>
        ) : (
          modelConfig.mcpServers.map((server, idx) => (
            <div
              key={idx}
              className="flex items-center justify-between p-3 bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors group shadow-sm dark:shadow-none"
            >
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] flex items-center justify-center border border-zinc-200 dark:border-zinc-800 text-orange-600/80">
                  <Wrench className="w-5 h-5" />
                </div>
                <div>
                  <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                    MCP Server
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700">
                      SSE
                    </span>
                    <div className="text-xs text-zinc-500 truncate max-w-[300px] font-mono">
                      {server}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-zinc-500">
                <button className="p-2 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-500/10 rounded-lg transition-colors">
                  <Play className="w-4 h-4" />
                </button>
                <button className="p-2 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors">
                  <List className="w-4 h-4" />
                </button>
                <button className="p-2 hover:text-green-500 hover:bg-green-50 dark:hover:bg-green-500/10 rounded-lg transition-colors">
                  <CheckSquare className="w-4 h-4 text-green-500" />
                </button>

                <div className="flex items-center gap-1.5 bg-green-50 dark:bg-green-500/10 text-green-600 dark:text-green-500 px-2.5 py-1 rounded-md text-[10px] font-bold border border-green-200 dark:border-green-500/20 uppercase tracking-wider mx-2">
                  <Check className="w-3 h-3" />
                  {t("settings.active")}
                </div>

                <button className="p-2 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-lg transition-colors">
                  <Pencil className="w-4 h-4" />
                </button>
                <button
                  onClick={() => handleRemoveMcp(server)}
                  className="p-2 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
