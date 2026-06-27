import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  Check,
  Sparkles,
  Pin,
  PinOff,
  Lock,
  Search,
  X,
} from "lucide-react";
import { ModelConfig } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";

interface ModelSelectorProps {
  isOpen: boolean;
  onToggle: () => void;
  modelConfig: ModelConfig;
  agentModels: { id: string; name: string; desc: string }[];
  pinnedAgentId: string | null;
  onModelSelect: (modelId: string, modelName: string) => void;
  onPinAgent: (agentId: string) => void;
  menuRef: React.RefObject<HTMLDivElement>;
  menuPanelRef?: React.RefObject<HTMLDivElement | null>;
  /** When true, agent is locked to this chat; show lock icon and disable changing until new chat */
  isLocked?: boolean;
  /** Resolved name for current chat's agent (avoids "Select Agent" flash on refresh) */
  resolvedAgentName?: string;
}

type MenuPosition = {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
};

const MENU_WIDTH = 320;
const MENU_CHROME_HEIGHT = 96;

function computeMenuPosition(trigger: HTMLElement): MenuPosition {
  const rect = trigger.getBoundingClientRect();
  const width = Math.min(MENU_WIDTH, window.innerWidth - 16);
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
  const spaceBelow = window.innerHeight - rect.bottom - 12;
  const spaceAbove = rect.top - 12;
  const openBelow = spaceBelow >= 180 || spaceBelow >= spaceAbove;
  const maxHeight = Math.min(320, Math.max(160, openBelow ? spaceBelow : spaceAbove));
  const top = openBelow ? rect.bottom + 8 : Math.max(8, rect.top - maxHeight - 8);
  return { top, left, width, maxHeight };
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  isOpen,
  onToggle,
  modelConfig,
  agentModels,
  pinnedAgentId,
  onModelSelect,
  onPinAgent,
  menuRef,
  menuPanelRef,
  isLocked = false,
  resolvedAgentName,
}) => {
  const { t } = useLanguage();
  const [searchQuery, setSearchQuery] = useState("");
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const rawName =
    isLocked && resolvedAgentName
      ? resolvedAgentName
      : modelConfig.name || t("chat.selectAgent");
  const displayName = rawName?.startsWith("Agent ")
    ? rawName.slice(6).trim()
    : rawName;
  const chipTitle = modelConfig.modelId
    ? `${displayName} (${modelConfig.modelId})`
    : displayName;

  const filteredModels = useMemo(() => {
    const term = searchQuery.trim().toLowerCase();
    const list = !term
      ? agentModels
      : agentModels.filter((m) => {
          const haystack = `${m.name} ${m.id} ${m.desc}`.toLowerCase();
          return haystack.includes(term);
        });
    if (!pinnedAgentId || term) return list;
    const pinned = list.find((m) => m.id === pinnedAgentId);
    if (!pinned) return list;
    return [pinned, ...list.filter((m) => m.id !== pinnedAgentId)];
  }, [agentModels, searchQuery, pinnedAgentId]);

  useLayoutEffect(() => {
    if (!isOpen || isLocked || !triggerRef.current) {
      setMenuPosition(null);
      return;
    }
    const updatePosition = () => {
      if (!triggerRef.current) return;
      setMenuPosition(computeMenuPosition(triggerRef.current));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [isOpen, isLocked, filteredModels.length]);

  useEffect(() => {
    if (!isOpen) {
      setSearchQuery("");
      return;
    }
    const id = window.requestAnimationFrame(() => {
      searchInputRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [isOpen]);

  const menu =
    isOpen && !isLocked && menuPosition
      ? createPortal(
          <div
            ref={menuPanelRef}
            className="bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl z-[120] flex flex-col animate-in slide-in-from-top-2 fade-in duration-200 overflow-hidden"
            style={{
              position: "fixed",
              top: menuPosition.top,
              left: menuPosition.left,
              width: menuPosition.width,
              maxHeight: menuPosition.maxHeight,
            }}
          >
            <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
              {t("chat.availableModels")}
            </div>
            <div className="px-2 py-2 border-b border-zinc-200 dark:border-zinc-800">
              <div className="flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 focus-within:border-indigo-400 dark:focus-within:border-indigo-500 transition-colors">
                <Search className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                <input
                  ref={searchInputRef}
                  type="search"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      e.stopPropagation();
                      if (searchQuery) {
                        setSearchQuery("");
                      } else {
                        onToggle();
                      }
                    }
                  }}
                  placeholder={t("chat.modelSearchPlaceholder")}
                  spellCheck={false}
                  autoComplete="off"
                  className="flex-1 min-w-0 bg-transparent text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-500 outline-none"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSearchQuery("");
                      searchInputRef.current?.focus();
                    }}
                    className="p-0.5 rounded-full text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors shrink-0"
                    title={t("chat.modelSearchClear")}
                    aria-label={t("chat.modelSearchClear")}
                  >
                    <X className="w-3 h-3" />
                  </button>
                ) : null}
              </div>
            </div>
            <div
              className="p-1 overflow-y-auto scrollbar-hide"
              style={{
                maxHeight: Math.max(120, menuPosition.maxHeight - MENU_CHROME_HEIGHT),
              }}
            >
              {filteredModels.map((m) => (
                <div key={m.id} className="group relative flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onPinAgent(m.id);
                    }}
                    className={`p-1.5 rounded-lg transition-all shrink-0 ${
                      pinnedAgentId === m.id
                        ? "text-emerald-500 hover:text-emerald-600 dark:text-emerald-400 dark:hover:text-emerald-300"
                        : "text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                    title={
                      pinnedAgentId === m.id
                        ? t("chat.unpinAgent")
                        : t("chat.pinAgent")
                    }
                  >
                    {pinnedAgentId === m.id ? (
                      <Pin className="w-3.5 h-3.5 fill-current" />
                    ) : (
                      <PinOff className="w-3.5 h-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => {
                      onModelSelect(m.id, m.name);
                      onToggle();
                    }}
                    className={`flex-1 text-left px-2 py-2 rounded-lg text-xs flex items-start gap-2 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 transition-colors ${
                      modelConfig.modelId === m.id
                        ? "bg-zinc-100 dark:bg-zinc-800/50"
                        : ""
                    }`}
                  >
                    <div
                      className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${modelConfig.modelId === m.id ? "bg-indigo-500" : "bg-zinc-400 dark:bg-zinc-700"}`}
                    />
                    <div className="flex flex-col min-w-0 flex-1 gap-0.5">
                      <span className="font-medium break-words leading-snug">{m.name}</span>
                      <span className="text-[10px] opacity-60 break-all leading-snug">
                        {m.id}
                      </span>
                      {m.desc ? (
                        <span className="text-[10px] opacity-50 break-words leading-snug">
                          {m.desc}
                        </span>
                      ) : null}
                    </div>
                    {modelConfig.modelId === m.id && (
                      <Check className="w-3 h-3 text-emerald-500 shrink-0 mt-0.5" />
                    )}
                  </button>
                </div>
              ))}

              {agentModels.length > 0 && filteredModels.length === 0 && (
                <div className="px-3 py-6 text-center text-xs text-zinc-400 dark:text-zinc-500">
                  {t("chat.modelSearchNoResults")}
                </div>
              )}

              {agentModels.length === 0 && (
                <div className="px-3 py-6 text-center text-xs text-zinc-400 dark:text-zinc-500 animate-content-fade-in">
                  <Sparkles className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="mb-1">
                    {t("chat.noAgents") || "No models available"}
                  </p>
                  <p className="text-[10px]">
                    {t("chat.configureAgents") || "Configure providers in Settings"}
                  </p>
                </div>
              )}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <div className="relative shrink-0" ref={menuRef}>
        <button
          ref={triggerRef}
          type="button"
          onClick={isLocked ? undefined : onToggle}
          className={`flex max-w-full items-center gap-2 px-3 py-1.5 rounded-full border transition-all ${
            isLocked
              ? "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 text-zinc-600 dark:text-zinc-400 cursor-default"
              : isOpen
                ? "bg-zinc-100 dark:bg-zinc-800 border-zinc-300 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100"
                : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
          }`}
          title={
            isLocked
              ? (t("chat.agentLocked") ?? "สร้างแชทใหม่เพื่อเปลี่ยน Agent")
              : chipTitle
          }
        >
          <div className="flex items-center gap-1.5 shrink-0">
            {isLocked ? (
              <Lock className="w-3.5 h-3.5 text-zinc-500 dark:text-zinc-400 shrink-0" />
            ) : (
              <div
                className={`w-2 h-2 rounded-full ${
                  pinnedAgentId === modelConfig.modelId
                    ? "bg-emerald-500"
                    : "bg-blue-500"
                }`}
              />
            )}
          </div>
          <span className="text-xs font-medium max-w-[min(11rem,42vw)] sm:max-w-[220px] lg:max-w-[280px] truncate">
            {displayName}
          </span>
          {!isLocked && (
            <ChevronDown
              className={`w-3 h-3 text-zinc-500 ml-1 transition-transform shrink-0 ${isOpen ? "rotate-180" : ""}`}
            />
          )}
        </button>
      </div>
      {menu}
    </>
  );
};
