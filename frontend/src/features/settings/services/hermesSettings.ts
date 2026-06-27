import { fetchJson } from "@/lib/api";
import type { FontSize } from "@/hooks/useAppearance";
import type { Theme } from "@/hooks/useTheme";
import type { Language } from "@/translations";

const SETTINGS_PATH = "/settings";

const HERMES_THEMES = new Set<HermesTheme>(["light", "dark", "system"]);
const HERMES_FONT_SIZES = new Set<HermesFontSize>(["small", "default", "large", "xlarge"]);
const UI_LANGUAGES = new Set<Language>(["en", "th"]);

/** Theme values from Hermes `app/domain/config.py` (`_SETTINGS_THEME_VALUES`). */
export type HermesTheme = "light" | "dark" | "system";

/** Font size values from Hermes default settings. */
export type HermesFontSize = "small" | "default" | "large" | "xlarge";

/**
 * Documented settings keys (Hermes `DEFAULT_SETTINGS` + GET/POST response extras).
 * Full payload may include additional keys; use `Record<string, unknown>` at boundaries.
 */
export interface HermesSettingsKnown {
  theme?: HermesTheme;
  skin?: string;
  font_size?: HermesFontSize;
  language?: string;
  bot_name?: string;
  send_key?: string;
  show_token_usage?: boolean;
  show_quota_chip?: boolean;
  sound_enabled?: boolean;
  notifications_enabled?: boolean;
  show_thinking?: boolean;
  simplified_tool_calling?: boolean;
  sidebar_density?: "compact" | "detailed";
  busy_input_mode?: "queue" | "interrupt" | "steer";
  onboarding_completed?: boolean;
  /** Present on GET; stripped on save. */
  password_env_var?: boolean;
  /** Present on GET when version metadata is available. */
  webui_version?: string;
  agent_version?: string;
  /** Present on POST save responses. */
  auth_enabled?: boolean;
  logged_in?: boolean;
  auth_just_enabled?: boolean;
}

export type HermesSettings = HermesSettingsKnown & Record<string, unknown>;

export async function fetchSettings(): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(SETTINGS_PATH);
}

export async function saveSettings(
  partial: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(SETTINGS_PATH, {
    method: "POST",
    body: partial,
  });
}

/** Map Agent-UI font size tokens to Hermes `font_size`. */
export function uiFontSizeToHermes(size: FontSize): HermesFontSize {
  switch (size) {
    case "xs":
    case "sm":
      return "small";
    case "lg":
      return "large";
    case "xl":
      return "xlarge";
    default:
      return "default";
  }
}

/** Map Hermes `font_size` to Agent-UI font size tokens. */
export function hermesFontSizeToUi(size: unknown): FontSize | null {
  switch (size) {
    case "small":
      return "sm";
    case "large":
      return "lg";
    case "xlarge":
      return "xl";
    case "default":
      return "base";
    default:
      return null;
  }
}

export function normalizeHermesTheme(value: unknown): Theme | null {
  return typeof value === "string" && HERMES_THEMES.has(value as HermesTheme)
    ? (value as Theme)
    : null;
}

export function normalizeHermesLanguage(value: unknown): Language | null {
  if (typeof value !== "string") return null;
  const code = value.split("-")[0]?.toLowerCase();
  return UI_LANGUAGES.has(code as Language) ? (code as Language) : null;
}

export function uiPreferencesToHermesPayload(prefs: {
  theme: Theme;
  language: Language;
  fontSize: FontSize;
}): Pick<HermesSettingsKnown, "theme" | "language" | "font_size"> {
  return {
    theme: prefs.theme,
    language: prefs.language,
    font_size: uiFontSizeToHermes(prefs.fontSize),
  };
}

/** Extract UI preferences from a Hermes settings payload. */
export function hermesSettingsToUiPreferences(settings: Record<string, unknown>): {
  theme?: Theme;
  language?: Language;
  fontSize?: FontSize;
} {
  const theme = normalizeHermesTheme(settings.theme);
  const language = normalizeHermesLanguage(settings.language);
  const fontSize =
    typeof settings.font_size === "string" && HERMES_FONT_SIZES.has(settings.font_size as HermesFontSize)
      ? hermesFontSizeToUi(settings.font_size) ?? undefined
      : undefined;
  return {
    ...(theme != null ? { theme } : {}),
    ...(language != null ? { language } : {}),
    ...(fontSize != null ? { fontSize } : {}),
  };
}
