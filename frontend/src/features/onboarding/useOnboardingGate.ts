import { useCallback, useEffect, useState } from "react";
import { fetchOnboardingStatus } from "./api";

/**
 * Loads onboarding status when the shell is authenticated.
 * Returns true when the first-run wizard should block the UI.
 */
export function useOnboardingGate(isAuthenticated: boolean) {
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [checked, setChecked] = useState(false);

  const reload = useCallback(async () => {
    if (!isAuthenticated) {
      setShowOnboarding(false);
      setChecked(true);
      return;
    }
    try {
      const status = await fetchOnboardingStatus();
      setShowOnboarding(!status.completed);
    } catch {
      setShowOnboarding(false);
    } finally {
      setChecked(true);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    setChecked(false);
    void reload();
  }, [reload]);

  const dismiss = useCallback(() => {
    setShowOnboarding(false);
    void reload();
  }, [reload]);

  return {
    showOnboarding: isAuthenticated && showOnboarding,
    onboardingChecked: checked,
    reloadOnboarding: reload,
    dismissOnboarding: dismiss,
  };
}
