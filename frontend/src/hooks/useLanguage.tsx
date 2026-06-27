import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  ReactNode,
} from "react";
import { translations as initialTranslations, Language } from "@/translations";
import { deepMerge } from "@/lib/deepMerge";

const CUSTOM_TRANSLATIONS_KEY = "hermes_custom_translations";

type TranslationOverlay = {
  en: Record<string, unknown>;
  th: Record<string, unknown>;
};

function loadTranslationOverlay(): TranslationOverlay {
  try {
    const raw = localStorage.getItem(CUSTOM_TRANSLATIONS_KEY);
    if (!raw) return { en: {}, th: {} };
    const parsed = JSON.parse(raw) as Partial<TranslationOverlay>;
    return {
      en:
        parsed?.en && typeof parsed.en === "object" && !Array.isArray(parsed.en)
          ? parsed.en
          : {},
      th:
        parsed?.th && typeof parsed.th === "object" && !Array.isArray(parsed.th)
          ? parsed.th
          : {},
    };
  } catch {
    return { en: {}, th: {} };
  }
}

function mergeWithOverlay(overlay: TranslationOverlay) {
  return {
    en: deepMerge(initialTranslations.en, overlay.en),
    th: deepMerge(initialTranslations.th, overlay.th),
  };
}

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (path: string) => string;
  updateTranslations: (newTranslations: Record<string, any>) => void;
  resetTranslations: () => void;
  exportTranslations: () => string;
}

const LanguageContext = createContext<LanguageContextType | undefined>(
  undefined,
);

interface LanguageProviderProps {
  children: ReactNode;
}

export const LanguageProvider: React.FC<LanguageProviderProps> = ({
  children,
}) => {
  const [language, setLanguageState] = useState<Language>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("language");
      return (saved === "en" || saved === "th" ? saved : "en") as Language;
    }
    return "en";
  });

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    localStorage.setItem("language", lang);
  };

  const [overlay, setOverlay] = useState<TranslationOverlay>(loadTranslationOverlay);
  const translations = useMemo(() => mergeWithOverlay(overlay), [overlay]);

  const t = (path: string): string => {
    const keys = path.split(".");
    let current: any = translations[language];

    for (const key of keys) {
      if (current === undefined || current[key] === undefined) {
        let fallback: any = initialTranslations[language];
        for (const k of keys) {
          if (fallback && fallback[k]) fallback = fallback[k];
          else return path;
        }
        return fallback as string;
      }
      current = current[key];
    }

    return current as string;
  };

  const updateTranslations = (newTranslations: Record<string, any>) => {
    setOverlay((prev) => {
      const next: TranslationOverlay = {
        en: deepMerge(prev.en, newTranslations.en ?? {}),
        th: deepMerge(prev.th, newTranslations.th ?? {}),
      };
      localStorage.setItem(CUSTOM_TRANSLATIONS_KEY, JSON.stringify(next));
      return next;
    });
  };

  const resetTranslations = () => {
    localStorage.removeItem(CUSTOM_TRANSLATIONS_KEY);
    setOverlay({ en: {}, th: {} });
  };

  const exportTranslations = (): string => {
    const flatten = (obj: any, prefix = ""): Record<string, string> => {
      let acc: Record<string, string> = {};
      for (const k in obj) {
        if (typeof obj[k] === "object") {
          Object.assign(acc, flatten(obj[k], prefix ? `${prefix}.${k}` : k));
        } else {
          acc[prefix ? `${prefix}.${k}` : k] = obj[k];
        }
      }
      return acc;
    };

    const enFlat = flatten(translations.en);
    const thFlat = flatten(translations.th);

    let csv = "key,en,th\n";
    const allKeys = new Set([...Object.keys(enFlat), ...Object.keys(thFlat)]);

    allKeys.forEach((key) => {
      const enVal = (enFlat[key] || "").replace(/"/g, '""');
      const thVal = (thFlat[key] || "").replace(/"/g, '""');
      csv += `${key},"${enVal}","${thVal}"\n`;
    });

    return csv;
  };

  return (
    <LanguageContext.Provider
      value={{
        language,
        setLanguage,
        t,
        updateTranslations,
        resetTranslations,
        exportTranslations,
      }}
    >
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
};
