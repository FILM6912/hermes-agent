import React, { useState, useRef, useEffect } from "react";
import {
  Monitor,
  Sun,
  Moon,
  Laptop,
  Languages,
  ChevronDown,
  Check,
  FileText,
  Upload,
  Download,
  Trash2,
  PanelRight,
} from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";
import { useAppearance, FontFamily } from "@/hooks/useAppearance";
import { ChatSession } from "@/types";
import { ProfilePicker } from "@/components/shell/ProfilePicker";

interface GeneralTabProps {
  chatHistory: ChatSession[];
  onClearAllChats: () => Promise<boolean>;
}

export const GeneralTab: React.FC<GeneralTabProps> = ({
  onClearAllChats,
}) => {
  const {
    t,
    language,
    setLanguage,
    updateTranslations,
    resetTranslations,
    exportTranslations,
  } = useLanguage();
  const { theme, setTheme } = useTheme();
  const { fontSize, setFontSize, fontFamily, setFontFamily, autoExpandSidebarOnTool, setAutoExpandSidebarOnTool } = useAppearance();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [showLanguageDropdown, setShowLanguageDropdown] = useState(false);
  const [showFontDropdown, setShowFontDropdown] = useState(false);
  const [showClearAllConfirm, setShowClearAllConfirm] = useState(false);
  const [clearingHistory, setClearingHistory] = useState(false);
  const languageDropdownRef = useRef<HTMLDivElement>(null);
  const fontDropdownRef = useRef<HTMLDivElement>(null);
  const fonts: FontFamily[] = [
    "noto-sans",
    "noto-serif",
    "noto-mono",
    "sarabun",
    "kanit",
    "prompt",
    "mitr",
    "chakra-petch",
    "bai-jamjuree",
    "system-sans",
    "system-serif",
    "system-mono",
    "sans",
    "mono",
  ];

  // Click outside handler for dropdowns
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        showLanguageDropdown &&
        languageDropdownRef.current &&
        !languageDropdownRef.current.contains(event.target as Node)
      ) {
        setShowLanguageDropdown(false);
      }
      if (
        showFontDropdown &&
        fontDropdownRef.current &&
        !fontDropdownRef.current.contains(event.target as Node)
      ) {
        setShowFontDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showLanguageDropdown, showFontDropdown]);

  const handleExportCSV = () => {
    const csvContent = exportTranslations();
    const BOM = "\uFEFF";
    const blob = new Blob([BOM + csvContent], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "translations.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleImportCSV = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target?.result as string;
      const lines = text.split("\n");
      const newTranslations: { en: any; th: any } = { en: {}, th: {} };

      for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        const match = line.match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g);
        if (match && match.length >= 3) {
          const key = match[0].replace(/"/g, "");
          const enVal = match[1].replace(/"/g, "");
          const thVal = match[2].replace(/"/g, "");

          const setDeep = (obj: any, path: string, val: string) => {
            const keys = path.split(".");
            let current = obj;
            for (let j = 0; j < keys.length - 1; j++) {
              if (!current[keys[j]]) current[keys[j]] = {};
              current = current[keys[j]];
            }
            current[keys[keys.length - 1]] = val;
          };

          setDeep(newTranslations.en, key, enVal);
          setDeep(newTranslations.th, key, thVal);
        }
      }
      updateTranslations(newTranslations);
      if (fileInputRef.current) fileInputRef.current.value = "";
    };
    reader.readAsText(file);
  };

  return (
    <>
      <div className="max-w-4xl space-y-6">
        <div className="mb-2">
          <p className="text-sm text-zinc-500 dark:text-zinc-500">
            {t("settings.generalDesc")}
          </p>
        </div>

        {/* Theme & Language Group */}
        <div className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-visible shadow-sm dark:shadow-none">
          {/* Theme Row */}
          <div className="p-4 flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center gap-4">
              <div className="p-2 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] text-blue-500 dark:text-blue-400 border border-zinc-200 dark:border-zinc-800">
                <Monitor className="w-5 h-5" />
              </div>
              <div>
                <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                  {t("sidebar.theme")}
                </div>
                <div className="text-xs text-zinc-500 mt-0.5">
                  {theme === "system"
                    ? t("sidebar.system")
                    : theme === "dark"
                      ? t("sidebar.dark")
                      : t("sidebar.light")}
                </div>
              </div>
            </div>
            <div className="flex bg-zinc-100 dark:bg-[#1e1e20] rounded-lg p-1 border border-zinc-200 dark:border-zinc-800">
              <button
                onClick={() => setTheme("light")}
                className={`p-2 rounded-md transition-colors ${theme === "light" ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"}`}
              >
                <Sun className="w-4 h-4" />
              </button>
              <button
                onClick={() => setTheme("dark")}
                className={`p-2 rounded-md transition-colors ${theme === "dark" ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"}`}
              >
                <Moon className="w-4 h-4" />
              </button>
              <button
                onClick={() => setTheme("system")}
                className={`p-2 rounded-md transition-colors ${theme === "system" ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"}`}
              >
                <Laptop className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Language Row */}
          <div className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-2 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] text-purple-500 dark:text-purple-400 border border-zinc-200 dark:border-zinc-800">
                <Languages className="w-5 h-5" />
              </div>
              <div>
                <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                  {t("sidebar.language")}
                </div>
                <div className="text-xs text-zinc-500 mt-0.5">
                  {language === "th" ? "ไทย" : "English"}
                </div>
              </div>
            </div>
            <div className="relative min-w-[120px]" ref={languageDropdownRef}>
              <button
                onClick={() => setShowLanguageDropdown(!showLanguageDropdown)}
                className="w-full flex items-center justify-between bg-zinc-100 dark:bg-[#1e1e20] text-zinc-900 dark:text-zinc-200 text-sm border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors"
              >
                <span>{language === "en" ? "English" : "ไทย"}</span>
                <ChevronDown
                  className={`w-4 h-4 text-zinc-500 transition-transform ml-2 ${showLanguageDropdown ? "rotate-180" : ""}`}
                />
              </button>

              {showLanguageDropdown && (
                <div className="absolute top-full right-0 mt-1 w-full bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-xl overflow-hidden z-100 animate-in fade-in slide-in-from-top-1 duration-150">
                  <button
                    onClick={() => {
                      setLanguage("en");
                      setShowLanguageDropdown(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm transition-colors ${
                      language === "en"
                        ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                        : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <span>English</span>
                    {language === "en" && <Check className="w-4 h-4" />}
                  </button>
                  <button
                    onClick={() => {
                      setLanguage("th");
                      setShowLanguageDropdown(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm transition-colors ${
                      language === "th"
                        ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                        : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <span>ไทย</span>
                    {language === "th" && <Check className="w-4 h-4" />}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <ProfilePicker className="mt-0" />

        {/* Appearance Group (Font & Size) */}
        <div className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-visible shadow-sm dark:shadow-none">
          <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-white/2">
             <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-200 flex items-center gap-2">
               <Languages className="w-4 h-4 text-indigo-500" />
               {t("settings.appearance")}
             </h3>
          </div>
          
          {/* Font Family Row */}
          <div className="p-4 flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800">
            <div>
              <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                {t("settings.fontFamily")}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {t(`settings.font${fontFamily.split('-').map((s: string) => s.charAt(0).toUpperCase() + s.slice(1)).join('')}`)}
              </div>
            </div>
            
            <div className="relative min-w-[160px]" ref={fontDropdownRef}>
              <button
                onClick={() => setShowFontDropdown(!showFontDropdown)}
                className="w-full flex items-center justify-between bg-zinc-100 dark:bg-[#1e1e20] text-zinc-900 dark:text-zinc-200 text-sm border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-1.5 hover:bg-zinc-200 dark:hover:bg-zinc-800 transition-colors"
              >
                <span className={`truncate ${fontFamily.includes('mono') ? 'font-mono' : ''}`}>
                  {t(`settings.font${fontFamily.split('-').map((s: string) => s.charAt(0).toUpperCase() + s.slice(1)).join('')}`)}
                </span>
                <ChevronDown
                  className={`w-4 h-4 text-zinc-500 transition-transform ml-2 shrink-0 ${showFontDropdown ? "rotate-180" : ""}`}
                />
              </button>

              {showFontDropdown && (
                <div className="absolute top-full right-0 mt-1 w-full sm:w-[240px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-xl overflow-y-auto max-h-[300px] z-50 animate-in fade-in slide-in-from-top-1 duration-150">
                  {fonts.map((font) => (
                    <button
                      key={font}
                      onClick={() => {
                        setFontFamily(font);
                        setShowFontDropdown(false);
                      }}
                      className={`w-full flex items-center justify-between px-3 py-2 text-sm transition-colors ${
                        fontFamily === font
                          ? "bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 font-medium"
                          : "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      }`}
                    >
                      <span className={font === 'mono' || font === 'system-mono' ? 'font-mono' : ''}>
                        {t(`settings.font${font.split('-').map((s: string) => s.charAt(0).toUpperCase() + s.slice(1)).join('')}`)}
                      </span>
                      {fontFamily === font && <Check className="w-4 h-4" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Text Size Row */}
          <div className="p-4 flex items-center justify-between">
            <div>
              <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                {t("settings.fontSize")}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {t(`settings.size${fontSize.charAt(0).toUpperCase() + fontSize.slice(1)}`)}
              </div>
            </div>
            <div className="flex bg-zinc-100 dark:bg-[#1e1e20] rounded-lg p-1 border border-zinc-200 dark:border-zinc-800 overflow-x-auto max-w-[200px] sm:max-w-none">
              {(['xs', 'sm', 'base', 'lg', 'xl'] as const).map((size) => (
                <button
                  key={size}
                  onClick={() => setFontSize(size)}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all whitespace-nowrap ${
                    fontSize === size
                      ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm"
                      : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300"
                  }`}
                  style={{ fontSize: size === 'xs' ? '12px' : size === 'xl' ? '14px' : '13px' }}
                >
                  {t(`settings.size${size.charAt(0).toUpperCase() + size.slice(1)}`)}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Manage Language Card */}
        <div className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl p-6 shadow-sm dark:shadow-none">
          <div className="flex items-center gap-3 mb-2">
            <FileText className="w-5 h-5 text-blue-500" />
            <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-200">
              {t("settings.manageLanguage")}
            </h3>
          </div>
          <p className="text-xs text-zinc-500 mb-6 ml-8">
            {t("settings.manageLanguageDesc")}
          </p>

          <div className="flex items-center justify-between ml-8">
            <div className="flex gap-3">
              <div className="relative">
                <input
                  type="file"
                  accept=".csv"
                  ref={fileInputRef}
                  onChange={handleImportCSV}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-medium transition-colors shadow-sm"
                >
                  <Upload className="w-4 h-4" />
                  {t("settings.importCSV")}
                </button>
              </div>
              <button
                onClick={handleExportCSV}
                className="flex items-center gap-2 bg-zinc-100 dark:bg-[#1e1e20] hover:bg-zinc-200 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-800 px-4 py-2 rounded-lg text-xs font-medium transition-colors"
              >
                <Download className="w-4 h-4" />
                {t("settings.exportCSV")}
              </button>
            </div>
            <button
              type="button"
              onClick={resetTranslations}
              className="flex items-center gap-2 text-red-600 dark:text-red-500/80 hover:text-red-700 dark:hover:text-red-400 bg-red-50 dark:bg-red-500/10 hover:bg-red-100 dark:hover:bg-red-500/20 border border-red-200 dark:border-red-500/20 px-4 py-2 rounded-lg text-xs font-medium transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              {t("settings.resetDefaults")}
            </button>
          </div>
        </div>

        {/* Auto Expand Sidebar on Tool Use */}
        <div className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 flex items-center justify-between shadow-sm dark:shadow-none">
          <div className="flex items-center gap-4">
            <div className="p-2 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] text-indigo-500 dark:text-indigo-400 border border-zinc-200 dark:border-zinc-800">
              <PanelRight className="w-5 h-5" />
            </div>
            <div>
              <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                {t("settings.autoExpandSidebarOnTool")}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {t("settings.autoExpandSidebarOnToolDesc")}
              </div>
            </div>
          </div>
          <button
            onClick={() => setAutoExpandSidebarOnTool(!autoExpandSidebarOnTool)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              autoExpandSidebarOnTool
                ? "bg-indigo-600"
                : "bg-zinc-200 dark:bg-zinc-700"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                autoExpandSidebarOnTool ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>

        {/* Clear Chat History */}
        <div className="bg-white dark:bg-[#121212] border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 flex items-center justify-between shadow-sm dark:shadow-none">
          <div className="flex items-center gap-4">
            <div className="p-2 rounded-lg bg-zinc-100 dark:bg-[#1e1e20] text-red-500 dark:text-red-400 border border-zinc-200 dark:border-zinc-800">
              <Trash2 className="w-5 h-5" />
            </div>
            <div>
              <div className="font-semibold text-zinc-900 dark:text-zinc-200 text-sm">
                {t("settings.clearHistory")}
              </div>
              <div className="text-xs text-zinc-500 mt-0.5">
                {t("settings.clearHistoryDesc")}
              </div>
            </div>
          </div>
          <button
            onClick={() => setShowClearAllConfirm(true)}
            disabled={clearingHistory}
            className="bg-red-50 dark:bg-red-500/10 hover:bg-red-500/15 dark:hover:bg-red-500/20 disabled:opacity-50 disabled:cursor-not-allowed text-red-600 dark:text-red-500 border border-red-200 dark:border-red-500/30 px-4 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95 cursor-pointer"
          >
            {t("settings.clearAll")}
          </button>
        </div>
      </div>

      {/* Clear All Chats Confirmation Modal */}
      {showClearAllConfirm && (
        <div
          className="fixed inset-0 z-100 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
          onClick={() => setShowClearAllConfirm(false)}
        >
          <div
            className="bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 w-full max-w-sm rounded-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 text-center">
              <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-500" />
              </div>
              <h3 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100 mb-2">
                {t("settings.clearHistory")}
              </h3>
              <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-6">
                {t("settings.clearHistoryWarning")}
              </p>

              <div className="flex gap-3">
                <button
                  onClick={() => setShowClearAllConfirm(false)}
                  disabled={clearingHistory}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors disabled:opacity-50"
                >
                  {t("common.cancel")}
                </button>
                <button
                  onClick={async () => {
                    setClearingHistory(true);
                    try {
                      const ok = await onClearAllChats();
                      if (ok) {
                        setShowClearAllConfirm(false);
                      }
                    } finally {
                      setClearingHistory(false);
                    }
                  }}
                  disabled={clearingHistory}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white transition-colors"
                >
                  {clearingHistory ? t("settings.clearingHistory") : t("common.delete")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
