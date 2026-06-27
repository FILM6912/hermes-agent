import React, { useEffect } from "react";
import { Check, ChevronDown, Loader2, UserCircle2 } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useAuthRole } from "@/features/auth/hooks/useAuthRole";
import type { HermesProfileSwitchResponse } from "@/services/hermes/profiles";

export type ProfileChipProps = {
  onProfileSwitched?: (result: HermesProfileSwitchResponse) => void;
  menuRef?: React.RefObject<HTMLDivElement | null>;
  isOpen?: boolean;
  onToggle?: () => void;
  disabled?: boolean;
};

export const ProfileChip: React.FC<ProfileChipProps> = ({
  onProfileSwitched,
  menuRef,
  isOpen = false,
  onToggle,
  disabled = false,
}) => {
  const { t } = useLanguage();
  const { canManageProfiles, canSwitchAllProfiles, canSwitchAssignedProfiles, multiUser } = useAuthRole();
  const {
    activeProfile,
    profiles,
    loading,
    switching,
    error,
    setActiveProfile,
    refreshProfiles,
  } = useActiveProfile();

  const canSwitch = canManageProfiles || canSwitchAllProfiles || canSwitchAssignedProfiles || !multiUser;

  useEffect(() => {
    if (isOpen) void refreshProfiles();
  }, [isOpen, refreshProfiles]);

  const handleSwitch = async (name: string) => {
    if (!canSwitch || name === activeProfile || switching) return;
    try {
      const result = await setActiveProfile(name);
      onToggle?.();
      onProfileSwitched?.(result);
    } catch {
      // setActiveProfile records error state
    }
  };

  const label =
    activeProfile ||
    t("settings.profileSelect") ||
    "Profile";

  return (
    <div className="relative" ref={menuRef}>
      {isOpen && canSwitch && (
        <div className="absolute top-full mt-2 left-0 w-[min(16rem,calc(100vw-1.5rem))] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl z-50 flex flex-col animate-in slide-in-from-top-2 fade-in duration-200 overflow-hidden">
          <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50 text-[10px] font-bold text-zinc-500 uppercase tracking-wider">
            {t("settings.profiles") || "Profiles"}
          </div>
          <div className="p-2 max-h-56 overflow-y-auto scrollbar-hide">
            {loading && profiles.length === 0 ? (
              <div className="flex items-center justify-center gap-2 text-xs text-zinc-500 py-6">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{t("common.loading") || "Loading…"}</span>
              </div>
            ) : error ? (
              <div className="text-xs text-red-500 text-center py-4 px-2">{error}</div>
            ) : profiles.length === 0 ? (
              <div className="text-xs text-zinc-500 text-center py-4 italic">
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
                    className={`w-full flex items-center justify-between gap-2 p-2 rounded-lg text-left transition-colors ${
                      isActive
                        ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400"
                        : "hover:bg-zinc-100 dark:hover:bg-zinc-800/50 text-zinc-700 dark:text-zinc-300"
                    } disabled:opacity-60`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium truncate">{profile.name}</div>
                      {profile.model && (
                        <div className="text-[10px] text-zinc-500 truncate">{profile.model}</div>
                      )}
                    </div>
                    {isBusy ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                    ) : isActive ? (
                      <Check className="w-3.5 h-3.5 shrink-0" />
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
      <button
        type="button"
        disabled={disabled || loading || !!switching || (canSwitch && !onToggle)}
        onClick={canSwitch ? onToggle : undefined}
        className={`flex items-center gap-1.5 max-w-[min(7rem,28vw)] sm:max-w-[140px] px-3 py-1.5 rounded-full border transition-all ${
          isOpen || activeProfile
            ? "bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-zinc-800 text-indigo-700 dark:text-indigo-400"
            : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 dark:text-zinc-400"
        } disabled:opacity-60`}
        title={
          canSwitch
            ? t("settings.agentProfileDesc") || "Switch Hermes agent profile"
            : label
        }
      >
        <UserCircle2 className="w-3.5 h-3.5 shrink-0" />
        <span className="text-xs font-medium truncate">
          {loading ? "…" : label}
        </span>
        {canSwitch && (
          switching ? (
            <Loader2 className="w-3 h-3 animate-spin shrink-0" />
          ) : (
            <ChevronDown
              className={`w-3 h-3 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
            />
          )
        )}
      </button>
    </div>
  );
};
