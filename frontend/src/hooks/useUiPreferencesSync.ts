import { useCallback, useEffect, useRef } from "react";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { useAppearance, type FontSize } from "@/hooks/useAppearance";
import {
  fetchSettings,
  saveSettings,
  hermesSettingsToUiPreferences,
  uiPreferencesToHermesPayload,
} from "@/features/settings/services/hermesSettings";
import type { Language } from "@/translations";

const SETTINGS_SAVE_DEBOUNCE_MS = 450;

function readStoredLanguage(): Language | null {
  const saved = localStorage.getItem("language");
  return saved === "en" || saved === "th" ? saved : null;
}

function readStoredTheme(): Theme | null {
  const saved = localStorage.getItem("theme");
  return saved === "light" || saved === "dark" || saved === "system"
    ? saved
    : null;
}

function readStoredFontSize(): FontSize | null {
  const saved = localStorage.getItem("app_font_size");
  return saved === "xs" ||
    saved === "sm" ||
    saved === "base" ||
    saved === "lg" ||
    saved === "xl"
    ? saved
    : null;
}

/**
 * Keep UI language/theme/font size aligned with Hermes settings.
 * Local browser prefs win on login; changes anywhere debounce to POST /settings.
 */
export function useUiPreferencesSync(isAuthenticated: boolean): void {
  const { language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  const { fontSize, setFontSize } = useAppearance();

  const hydratedRef = useRef(false);
  const skipSaveRef = useRef(true);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!isAuthenticated) {
      hydratedRef.current = false;
      skipSaveRef.current = true;
      return;
    }
    if (hydratedRef.current) return;

    let cancelled = false;

    void (async () => {
      try {
        const remote = await fetchSettings();
        if (cancelled) return;

        const prefs = hermesSettingsToUiPreferences(remote);
        const localLang = readStoredLanguage();
        const localTheme = readStoredTheme();
        const localFontSize = readStoredFontSize();

        const effectiveLanguage = localLang ?? prefs.language ?? language;
        const effectiveTheme = localTheme ?? prefs.theme ?? theme;
        const effectiveFontSize = localFontSize ?? prefs.fontSize ?? fontSize;

        if (effectiveLanguage !== language) setLanguage(effectiveLanguage);
        if (effectiveTheme !== theme) setTheme(effectiveTheme);
        if (effectiveFontSize !== fontSize) setFontSize(effectiveFontSize);

        await saveSettings(
          uiPreferencesToHermesPayload({
            theme: effectiveTheme,
            language: effectiveLanguage,
            fontSize: effectiveFontSize,
          }),
        );
      } catch (error) {
        console.error("Failed to sync UI preferences:", error);
      } finally {
        if (!cancelled) {
          hydratedRef.current = true;
          skipSaveRef.current = false;
        }
      }
    })();

    return () => {
      cancelled = true;
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate once per auth session
  }, [isAuthenticated]);

  const persistSettings = useCallback(async () => {
    try {
      await saveSettings(
        uiPreferencesToHermesPayload({ theme, language, fontSize }),
      );
    } catch (error) {
      console.error("Failed to save UI preferences:", error);
    }
  }, [theme, language, fontSize]);

  useEffect(() => {
    if (!isAuthenticated || skipSaveRef.current) return;

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      void persistSettings();
    }, SETTINGS_SAVE_DEBOUNCE_MS);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [theme, language, fontSize, isAuthenticated, persistSettings]);
}
