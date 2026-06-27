import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";

export type FontSize = "xs" | "sm" | "base" | "lg" | "xl";
export type FontFamily = 
  | "sans" 
  | "mono" 
  | "noto-sans" 
  | "noto-serif"
  | "noto-mono"
  | "sarabun"
  | "kanit"
  | "prompt"
  | "mitr"
  | "chakra-petch"
  | "bai-jamjuree"
  | "system-sans"
  | "system-serif"
  | "system-mono";

interface AppearanceContextType {
  fontSize: FontSize;
  setFontSize: (size: FontSize) => void;
  fontFamily: FontFamily;
  setFontFamily: (family: FontFamily) => void;
  autoExpandSidebarOnTool: boolean;
  setAutoExpandSidebarOnTool: (value: boolean) => void;
}

const AppearanceContext = createContext<AppearanceContextType | undefined>(
  undefined
);

const FONT_SIZE_MAP: Record<FontSize, string> = {
  xs: "14px",
  sm: "15px",
  base: "16px",
  lg: "18px",
  xl: "20px",
};

const FONT_FAMILY_MAP: Record<FontFamily, string> = {
  "sans": "Inter, sans-serif",
  "mono": "'JetBrains Mono', monospace",
  "noto-sans": "'Noto Sans', 'Noto Sans Thai', sans-serif",
  "noto-serif": "'Noto Serif', 'Noto Serif Thai', serif",
  "noto-mono": "'Noto Sans Mono', 'Noto Sans Thai-Mono', monospace",
  "sarabun": "Sarabun, sans-serif",
  "kanit": "Kanit, sans-serif",
  "prompt": "Prompt, sans-serif",
  "mitr": "Mitr, sans-serif",
  "chakra-petch": "'Chakra Petch', sans-serif",
  "bai-jamjuree": "'Bai Jamjuree', sans-serif",
  "system-sans": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif",
  "system-serif": "ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif",
  "system-mono": "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
};

export const AppearanceProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [fontSize, setFontSizeState] = useState<FontSize>(() => {
    return (localStorage.getItem("app_font_size") as FontSize) || "base";
  });

  const [fontFamily, setFontFamilyState] = useState<FontFamily>(() => {
    return (localStorage.getItem("app_font_family") as FontFamily) || "sans";
  });

  const [autoExpandSidebarOnTool, setAutoExpandSidebarOnToolState] = useState<boolean>(() => {
    const stored = localStorage.getItem("app_auto_expand_sidebar_on_tool");
    return stored === null ? false : stored === "true";
  });

  useEffect(() => {
    const root = window.document.documentElement;
    root.style.fontSize = FONT_SIZE_MAP[fontSize];
    localStorage.setItem("app_font_size", fontSize);
  }, [fontSize]);

  useEffect(() => {
    const root = window.document.documentElement;
    const body = window.document.body;
    const fontValue = FONT_FAMILY_MAP[fontFamily];
    
    root.style.setProperty("--app-font-family", fontValue);
    root.style.setProperty("--font-family-sans", fontValue);
    
    if (body) {
      body.style.setProperty("--app-font-family", fontValue);
      body.style.setProperty("--font-family-sans", fontValue);
    }
    
    localStorage.setItem("app_font_family", fontFamily);
  }, [fontFamily]);

  useEffect(() => {
    localStorage.setItem("app_auto_expand_sidebar_on_tool", String(autoExpandSidebarOnTool));
  }, [autoExpandSidebarOnTool]);

  const value = {
    fontSize,
    setFontSize: setFontSizeState,
    fontFamily,
    setFontFamily: setFontFamilyState,
    autoExpandSidebarOnTool,
    setAutoExpandSidebarOnTool: setAutoExpandSidebarOnToolState,
  };

  return (
    <AppearanceContext.Provider value={value}>
      {children}
    </AppearanceContext.Provider>
  );
};

export const useAppearance = () => {
  const context = useContext(AppearanceContext);
  if (context === undefined) {
    throw new Error("useAppearance must be used within an AppearanceProvider");
  }
  return context;
};
