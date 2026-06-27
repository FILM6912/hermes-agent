import React from "react";
import {
  Settings,
  Sun,
  Moon,
  Laptop,
  Languages,
  LogOut,
  ChevronDown,
  Check,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";

interface SettingsMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenSettings: () => void;
  onLogout?: () => void;
  isPreviewOpen: boolean;
  menuRef: React.RefObject<HTMLDivElement>;
  languageDropdownRef: React.RefObject<HTMLDivElement>;
}

export const SettingsMenu: React.FC<SettingsMenuProps> = ({
  isOpen,
  onClose,
  onOpenSettings,
  onLogout,
  isPreviewOpen,
  menuRef,
  languageDropdownRef,
}) => {
  const { t, language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  const [showLanguageDropdown, setShowLanguageDropdown] = React.useState(false);

  if (!isOpen) return null;

  return (
    <div
      ref={menuRef}
      className={`absolute top-14 bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-2xl p-3 z-50 animate-in slide-in-from-top-2 fade-in duration-200 min-w-[280px] ${
        isPreviewOpen ? "right-4" : "right-12"
      }`}
    >
      {/* Theme Section */}
      <div className="mb-3">
        <div className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-2 uppercase tracking-wider px-1">
          {t("sidebar.theme")}
        </div>
        <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-1 border border-zinc-200 dark:border-zinc-800">
          <button
            onClick={() => setTheme("light")}
            className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
              theme === "light"
                ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
            }`}
          >
            <Sun className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setTheme("dark")}
            className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
              theme === "dark"
                ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
            }`}
          >
            <Moon className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setTheme("system")}
            className={`flex-1 flex items-center justify-center gap-1.5 p-2 rounded-md transition-all text-xs font-medium ${
              theme === "system"
                ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-zinc-100"
                : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
            }`}
          >
            <Laptop className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50"></div>

      {/* Language Dropdown */}
      <div className="px-2 py-1" ref={languageDropdownRef}>
        <div className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-2 uppercase tracking-wider">
          {t("sidebar.language")}
        </div>
        <div className="relative">
          <button
            onClick={() => setShowLanguageDropdown(!showLanguageDropdown)}
            className="w-full flex items-center justify-between bg-zinc-100 dark:bg-zinc-900 text-zinc-900 dark:text-zinc-200 text-sm border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors"
          >
            <div className="flex items-center gap-2">
              <Languages className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
              <span>{language === "en" ? "English" : "ไทย"}</span>
            </div>
            <ChevronDown
              className={`w-4 h-4 text-zinc-500 transition-transform ${showLanguageDropdown ? "rotate-180" : ""}`}
            />
          </button>

          {showLanguageDropdown && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg overflow-hidden z-50 animate-in fade-in slide-in-from-top-1 duration-150">
              <button
                onClick={() => {
                  setLanguage("en");
                  setShowLanguageDropdown(false);
                }}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                  language === "en"
                    ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                    : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                }`}
              >
                <span className="flex-1 text-left">English</span>
                {language === "en" && <Check className="w-4 h-4" />}
              </button>
              <button
                onClick={() => {
                  setLanguage("th");
                  setShowLanguageDropdown(false);
                }}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                  language === "th"
                    ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                    : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                }`}
              >
                <span className="flex-1 text-left">ไทย</span>
                {language === "th" && <Check className="w-4 h-4" />}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="my-2 border-t border-zinc-200 dark:border-zinc-800/50"></div>

      {/* Go to Settings Page */}
      <button
        onClick={() => {
          onClose();
          onOpenSettings();
        }}
        className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 font-medium"
      >
        <Settings className="w-4 h-4 shrink-0 text-zinc-500 dark:text-zinc-400" />
        <span className="flex-1 text-left">{t("settings.title")}</span>
      </button>

      {/* Logout Button */}
      {onLogout && (
        <button
          onClick={() => {
            onClose();
            onLogout();
          }}
          className="w-full flex items-center gap-3 px-2 py-2.5 rounded-lg text-sm transition-colors text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 font-medium"
        >
          <LogOut className="w-4 h-4 shrink-0" />
          <span className="flex-1 text-left">{t("sidebar.logout")}</span>
        </button>
      )}
    </div>
  );
};
