import React, { useState } from "react";
import { Fingerprint, Loader2 } from "lucide-react";
import { useLanguage } from "@/hooks/useLanguage";
import { loginWithPasskey, type AuthLoginResponse, type AuthStatus } from "../services/authService";

interface PasskeyButtonProps {
  visible: boolean;
  disabled?: boolean;
  onSuccess: (login?: AuthLoginResponse) => void | Promise<AuthStatus | null>;
  onError: (message: string) => void;
}

function passkeySupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.get === "function"
  );
}

export const PasskeyButton: React.FC<PasskeyButtonProps> = ({
  visible,
  disabled = false,
  onSuccess,
  onError,
}) => {
  const { language } = useLanguage();
  const [loading, setLoading] = useState(false);

  if (!visible || !passkeySupported()) {
    return null;
  }

  const label =
    language === "th" ? "เข้าสู่ระบบด้วย Passkey" : "Sign in with passkey";

  const handleClick = async () => {
    setLoading(true);
    try {
      const loginData = await loginWithPasskey();
      await onSuccess(loginData);
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : language === "th"
            ? "ไม่สามารถใช้ Passkey ได้"
            : "Passkey sign-in failed";
      onError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled || loading}
      className="w-full flex items-center justify-center gap-2 rounded-xl border border-amber-500/35 bg-amber-500/5 px-4 py-3.5 text-sm font-semibold text-amber-700 dark:text-amber-400 transition-colors hover:bg-amber-500/10 disabled:opacity-60 disabled:cursor-not-allowed"
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <Fingerprint className="w-4 h-4" />
      )}
      <span>{label}</span>
    </button>
  );
};
