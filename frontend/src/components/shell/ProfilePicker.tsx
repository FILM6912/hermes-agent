import React, { useState } from "react";
import { Check, ChevronDown, Loader2, RefreshCw, UserCircle2 } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useActiveProfile } from "@/hooks/useActiveProfile";

export type ProfilePickerProps = {
  /** Called after a successful profile switch (e.g. reload models/sessions). */
  onProfileSwitched?: (profileName: string) => void;
  className?: string;
};

export const ProfilePicker: React.FC<ProfilePickerProps> = ({
  onProfileSwitched,
  className = "",
}) => {
  const { t } = useLanguage();
  const {
    activeProfile,
    profiles,
    loading,
    switching,
    error,
    setActiveProfile,
    refreshProfiles,
  } = useActiveProfile();
  const [isOpen, setIsOpen] = useState(false);

  const handleSwitch = async (name: string) => {
    if (name === activeProfile || switching) return;
    try {
      const result = await setActiveProfile(name);
      setIsOpen(false);
      onProfileSwitched?.(result.active);
    } catch {
      // setActiveProfile records error state
    }
  };

  const active = profiles.find((p) => p.name === activeProfile);
  const label = active?.name || activeProfile || t("settings.profileSelect") || "Select profile";

  return (
    <div
      className={`bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-visible shadow-sm dark:shadow-none ${className}`}
    >
      <div className="p-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <div className="p-2 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] text-emerald-500 dark:text-emerald-400 border border-zinc-200 dark:border-zinc-800 shrink-0">
            <UserCircle2 className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
              {t("settings.agentProfile") || "Agent profile"}
            </div>
            <div className="text-xs text-zinc-500 mt-0.5 truncate">
              {t("settings.agentProfileDesc") ||
                "Switch Hermes agent profile for this browser session"}
            </div>
          </div>
        </div>

        <div className="relative min-w-[160px] shrink-0">
          <button
            type="button"
            disabled={loading || !!switching}
            onClick={() => setIsOpen((open) => !open)}
            className="w-full flex items-center justify-between bg-zinc-100 dark:bg-[#1e1e20] text-zinc-900 dark:text-zinc-200 text-sm border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors disabled:opacity-60"
          >
            <span className="truncate">{loading ? "…" : label}</span>
            {loading || switching ? (
              <Loader2 className="w-4 h-4 ml-2 animate-spin shrink-0" />
            ) : (
              <ChevronDown
                className={`w-4 h-4 text-zinc-500 transition-transform ml-2 shrink-0 ${isOpen ? "rotate-180" : ""}`}
              />
            )}
          </button>

          {isOpen && !loading && (
            <div className="absolute top-full right-0 mt-1 w-full sm:min-w-[240px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-xl overflow-hidden z-50 animate-in fade-in slide-in-from-top-1 duration-150">
              <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 flex items-center justify-between">
                <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
                  {t("settings.profiles") || "Profiles"}
                </span>
                <button
                  type="button"
                  onClick={() => void refreshProfiles()}
                  className="p-1 rounded-md text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  title={t("common.refresh") || "Refresh"}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="p-1 max-h-60 overflow-y-auto">
                {profiles.length === 0 ? (
                  <div className="px-3 py-4 text-center text-xs text-zinc-500">
                    {t("settings.noProfiles") || "No profiles available"}
                  </div>
                ) : (
                  profiles.map((profile) => {
                    const isActive = profile.name === activeProfile;
                    const isBusy = switching === profile.name;
                    return (
                      <button
                        key={profile.name}
                        type="button"
                        disabled={!!switching}
                        onClick={() => void handleSwitch(profile.name)}
                        className={`w-full flex items-center justify-between px-3 py-2 text-sm rounded-lg transition-colors ${
                          isActive
                            ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                            : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        } disabled:opacity-60`}
                      >
                        <div className="flex flex-col items-start min-w-0">
                          <span className="truncate">{profile.name}</span>
                          {profile.model && (
                            <span className="text-[10px] opacity-60 truncate max-w-full">
                              {profile.model}
                            </span>
                          )}
                        </div>
                        {isBusy ? (
                          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                        ) : isActive ? (
                          <Check className="w-4 h-4 shrink-0" />
                        ) : null}
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="px-4 pb-4">
          <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
        </div>
      )}
    </div>
  );
};
