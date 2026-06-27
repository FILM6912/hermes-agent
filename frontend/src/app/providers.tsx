import { HashRouter } from "react-router-dom";
import { ThemeProvider } from "@/hooks/useTheme";
import { LanguageProvider } from "@/hooks/useLanguage";
import { AppearanceProvider } from "@/hooks/useAppearance";
import { ActiveProfileProvider } from "@/hooks/useActiveProfile";
import { ToastProvider } from "@/components/toast/ToastProvider";

interface ProvidersProps {
  children: React.ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <ThemeProvider>
      <AppearanceProvider>
        <LanguageProvider>
          <ActiveProfileProvider>
            <ToastProvider>
              <HashRouter>{children}</HashRouter>
            </ToastProvider>
          </ActiveProfileProvider>
        </LanguageProvider>
      </AppearanceProvider>
    </ThemeProvider>
  );
}
