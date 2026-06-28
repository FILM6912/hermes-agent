import React, { useState, useEffect, useRef } from "react";
import {
  ArrowRight,
  Loader2,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  KeyRound,
  MoreVertical,
  Sun,
  Moon,
  Laptop,
  Languages,
  Mail,
} from "lucide-react";
import { useLocation, Link, useNavigate } from "react-router-dom";
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";
import {
  getAuthStatus,
  login,
  isShellAuthenticated,
  type AuthLoginResponse,
  type AuthStatus,
} from "../services/authService";
import {
  normalizeLegacyLoginUrl,
  resolvePostLoginPath,
  isFullPageRedirectPath,
  navigateToFullPagePath,
} from "../utils/loginRedirect";
import { PasskeyButton } from "./PasskeyButton";

interface AuthPageProps {
  /** Refresh shell auth state; must settle before navigating to /chat. */
  onLogin: (login?: AuthLoginResponse) => void | Promise<AuthStatus | null>;
}

export const AuthPage: React.FC<AuthPageProps> = ({ onLogin }) => {
  const { t, language, setLanguage } = useLanguage();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const isLogin = location.pathname === "/login" || location.pathname === "/";
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [multiUser, setMultiUser] = useState(false);
  const [passkeysEnabled, setPasskeysEnabled] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);

  // Menu State
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const [formData, setFormData] = useState({
    email: "",
    password: "",
    confirmPassword: "",
  });

  const finishLogin = async (loginData?: AuthLoginResponse): Promise<AuthStatus | null> => {
    const target = resolvePostLoginPath(location);
    const fullPage = isFullPageRedirectPath(target);
    if (!fullPage) {
      window.history.replaceState(null, "", `/#${target.startsWith("/") ? target : `/${target}`}`);
    }
    const nextStatus = await onLogin(loginData);
    if (!nextStatus || !isShellAuthenticated(nextStatus)) {
      setError(t("auth.sessionNotEstablished"));
      setIsLoading(false);
      return null;
    }
    if (fullPage) {
      if (!navigateToFullPagePath(target)) {
        setError("Could not open API docs. Sign in again or open /docs from the address bar.");
        setIsLoading(false);
      }
      return nextStatus;
    }
    navigate(target, { replace: true });
    return nextStatus;
  };

  useEffect(() => {
    setMounted(true);
    normalizeLegacyLoginUrl();

    let cancelled = false;
    getAuthStatus()
      .then((status) => {
        if (cancelled) return;
        if (status.multi_user) setMultiUser(true);
        if (status.passkeys_enabled) setPasskeysEnabled(true);
        if (status.logged_in) void finishLogin();
      })
      .catch(() => {
        /* keep single-field login if status probe fails */
      })
      .finally(() => {
        if (!cancelled) setStatusLoading(false);
      });

    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowMenu(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);

    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
    setError("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError("");

    if (!isLogin) {
      if (formData.password !== formData.confirmPassword) {
        setError("Passwords do not match");
        setIsLoading(false);
        return;
      }
      setError("Account registration is not available on this server.");
      setIsLoading(false);
      return;
    }

    const email = formData.email.trim().toLowerCase();
    if (multiUser && !email) {
      setError(t("auth.emailRequired"));
      setIsLoading(false);
      return;
    }

    try {
      const loginData = await login({
        password: formData.password,
        email: multiUser ? email : undefined,
      });
      await finishLogin(loginData);
      return;
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : t("auth.loginError");
      setError(message);
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-zinc-50 dark:bg-[#050505] relative overflow-hidden selection:bg-indigo-500/30 text-zinc-900 dark:text-zinc-100 transition-colors duration-300 animate-page-enter">
      {/* --- Settings Menu (Top Right) --- */}
      <div className="absolute top-6 right-6 z-50" ref={menuRef}>
        <button
          onClick={() => setShowMenu(!showMenu)}
          className={`p-1 transition-colors duration-200 rounded-full ${showMenu ? "text-zinc-900 dark:text-white bg-zinc-200/50 dark:bg-white/10" : "text-zinc-400 hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-white"}`}
        >
          <MoreVertical className="w-6 h-6" />
        </button>

        {showMenu && (
          <div className="absolute right-0 mt-3 w-56 bg-white/90 dark:bg-[#0c0c0e]/90 backdrop-blur-xl border border-zinc-200 dark:border-white/10 rounded-2xl shadow-2xl p-2 animate-in fade-in zoom-in-95 duration-200 origin-top-right ring-1 ring-black/5">
            {/* Theme Section */}
            <div className="p-2">
              <div className="text-[10px] font-bold text-zinc-500 mb-2 uppercase tracking-wider px-1">
                {t("sidebar.theme")}
              </div>
              <div className="flex bg-zinc-100 dark:bg-black/40 rounded-xl p-1 border border-zinc-200 dark:border-white/5">
                <button
                  onClick={() => setTheme("light")}
                  className={`flex-1 flex items-center justify-center p-2 rounded-lg transition-all ${theme === "light" ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-zinc-300"}`}
                  title={t("sidebar.light")}
                >
                  <Sun className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setTheme("dark")}
                  className={`flex-1 flex items-center justify-center p-2 rounded-lg transition-all ${theme === "dark" ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-zinc-300"}`}
                  title={t("sidebar.dark")}
                >
                  <Moon className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setTheme("system")}
                  className={`flex-1 flex items-center justify-center p-2 rounded-lg transition-all ${theme === "system" ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-sm" : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-500 dark:hover:text-zinc-300"}`}
                  title={t("sidebar.system")}
                >
                  <Laptop className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="h-[1px] bg-zinc-200 dark:bg-white/5 my-1 mx-2"></div>

            {/* Language Section */}
            <div className="p-1">
              <button
                onClick={() => {
                  setLanguage(language === "en" ? "th" : "en");
                  setShowMenu(false);
                }}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs transition-colors text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-zinc-200"
              >
                <div className="p-1.5 bg-indigo-500/10 rounded-lg text-indigo-500 dark:text-indigo-400">
                  <Languages className="w-4 h-4" />
                </div>
                <span className="flex-1 text-left font-medium">
                  {language === "en"
                    ? "Switch to Thai"
                    : "เปลี่ยนเป็นภาษาอังกฤษ"}
                </span>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* --- Main Card --- */}
      <div
        className={`w-full max-w-[420px] z-10 p-6 transition-all duration-700 ease-out transform ${mounted ? "translate-y-0 opacity-100" : "translate-y-10 opacity-0"}`}
      >
        <div className="relative overflow-hidden rounded-[2rem] border border-white/20 dark:border-zinc-800 shadow-2xl bg-white dark:bg-[#18181b] group">
          {/* Top shimmer border */}
          <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-zinc-400/50 dark:via-white/20 to-transparent opacity-50"></div>

          <div className="p-8 pb-6">
            {/* Logo/Icon */}
            <div className="flex flex-col items-center justify-center mb-8">
              <div className="relative mb-6 group-hover:scale-110 transition-transform duration-500">
                <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl blur opacity-20 dark:opacity-40 group-hover:opacity-40 dark:group-hover:opacity-60 transition-opacity duration-500"></div>
                <div className="relative w-16 h-16 bg-gradient-to-br from-white to-zinc-100 dark:from-[#1a1a1e] dark:to-[#0d0d10] rounded-2xl flex items-center justify-center border border-white/50 dark:border-white/10 shadow-xl">
                  <Sparkles className="w-8 h-8 text-indigo-500 dark:text-indigo-400" />
                </div>
              </div>

              <div className="text-center space-y-2">
                <h1 className="text-3xl font-bold text-zinc-900 dark:text-white tracking-tight">
                  {isLogin ? t("auth.welcomeBack") : t("auth.createAccount")}
                </h1>
                <p className="text-zinc-500 dark:text-zinc-400 text-sm">
                  {isLogin ? t("auth.subtitleLogin") : t("auth.subtitleSignup")}
                </p>
              </div>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Username (multi-user installs only) */}
              {multiUser && (
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400 ml-1 tracking-wide uppercase">
                    {t("settings.email")}
                  </label>
                  <div className="relative group/input">
                    <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/20 to-purple-500/20 rounded-xl blur-sm opacity-0 group-focus-within/input:opacity-100 transition-opacity duration-500"></div>
                    <div className="relative flex items-center bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within/input:border-indigo-500/50 group-focus-within/input:bg-white dark:group-focus-within/input:bg-[#050505] group-focus-within/input:shadow-lg dark:group-focus-within/input:shadow-none">
                      <Mail className="w-5 h-5 text-zinc-400 dark:text-zinc-500 group-focus-within/input:text-indigo-500 dark:group-focus-within/input:text-indigo-400 transition-colors" />
                      <input
                        type="email"
                        name="email"
                        value={formData.email}
                        onChange={handleChange}
                        className="w-full bg-transparent border-none outline-none text-zinc-900 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 ml-3 text-sm font-medium"
                        placeholder={t("auth.emailPlaceholder")}
                        autoComplete="email"
                        required
                        disabled={statusLoading}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Password Input */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400 ml-1 tracking-wide uppercase">
                  {t("auth.password")}
                </label>
                <div className="relative group/input">
                  <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/20 to-purple-500/20 rounded-xl blur-sm opacity-0 group-focus-within/input:opacity-100 transition-opacity duration-500"></div>
                  <div className="relative flex items-center bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within/input:border-indigo-500/50 group-focus-within/input:bg-white dark:group-focus-within/input:bg-[#050505] group-focus-within/input:shadow-lg dark:group-focus-within/input:shadow-none">
                    <KeyRound className="w-5 h-5 text-zinc-400 dark:text-zinc-500 group-focus-within/input:text-indigo-500 dark:group-focus-within/input:text-indigo-400 transition-colors" />
                    <input
                      type={showPassword ? "text" : "password"}
                      name="password"
                      value={formData.password}
                      onChange={handleChange}
                      className="w-full bg-transparent border-none outline-none text-zinc-900 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 ml-3 text-sm font-medium"
                      placeholder={multiUser ? "Password" : "Enter password"}
                      required
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300 transition-colors"
                    >
                      {showPassword ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* Confirm Password (Animated) */}
              <div
                className={`space-y-1.5 overflow-hidden transition-all duration-500 ease-in-out ${!isLogin ? "max-h-24 opacity-100" : "max-h-0 opacity-0"}`}
              >
                <label className="text-xs font-medium text-zinc-500 dark:text-zinc-400 ml-1 tracking-wide uppercase">
                  {t("auth.confirmPassword")}
                </label>
                <div className="relative group/input">
                  <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/20 to-purple-500/20 rounded-xl blur-sm opacity-0 group-focus-within/input:opacity-100 transition-opacity duration-500"></div>
                  <div className="relative flex items-center bg-zinc-50/80 dark:bg-[#09090b] border border-zinc-200 dark:border-zinc-800/80 rounded-xl px-4 py-3.5 transition-all duration-300 group-focus-within/input:border-indigo-500/50 group-focus-within/input:bg-white dark:group-focus-within/input:bg-[#050505] group-focus-within/input:shadow-lg dark:group-focus-within/input:shadow-none">
                    <CheckCircle2 className="w-5 h-5 text-zinc-400 dark:text-zinc-500 group-focus-within/input:text-indigo-500 dark:group-focus-within/input:text-indigo-400 transition-colors" />
                    <input
                      type="password"
                      name="confirmPassword"
                      value={formData.confirmPassword}
                      onChange={handleChange}
                      className="w-full bg-transparent border-none outline-none text-zinc-900 dark:text-zinc-200 placeholder-zinc-400 dark:placeholder-zinc-600 ml-3 text-sm font-medium"
                      placeholder="Repeat password"
                      autoComplete="new-password"
                      required={!isLogin}
                    />
                  </div>
                </div>
              </div>

              {/* Error Message */}
              {error && (
                <div className="flex items-center gap-2 text-red-500 dark:text-red-400 text-xs bg-red-50 dark:bg-red-500/10 p-3 rounded-xl border border-red-200 dark:border-red-500/20 animate-in slide-in-from-left-2 fade-in">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isLoading || statusLoading}
                className="relative w-full group overflow-hidden rounded-xl p-[1px] focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:ring-offset-2 focus:ring-offset-zinc-100 dark:focus:ring-offset-[#09090b] disabled:opacity-70 disabled:cursor-not-allowed mt-2"
              >
                <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-indigo-500 animate-[shimmer_2s_linear_infinite] bg-[length:200%_100%]"></span>
                <span className="relative flex items-center justify-center gap-2 w-full bg-white dark:bg-[#131316] text-zinc-900 dark:text-white py-3.5 rounded-[11px] transition-all group-hover:bg-transparent group-hover:text-white font-semibold tracking-wide border border-transparent dark:border-transparent group-hover:border-white/20">
                  {isLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>
                        {isLogin
                          ? t("auth.signingIn")
                          : t("auth.creatingAccount")}
                      </span>
                    </>
                  ) : (
                    <>
                      <span>
                        {isLogin ? t("auth.login") : t("auth.signup")}
                      </span>
                      <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                    </>
                  )}
                </span>
              </button>
            </form>

            {isLogin && (
              <div className="mt-4">
                <PasskeyButton
                  visible={passkeysEnabled}
                  disabled={isLoading || statusLoading}
                  onSuccess={finishLogin}
                  onError={(message) => setError(message)}
                />
              </div>
            )}

            {/* Toggle Login/Signup */}
            <div className="mt-8 text-center">
              <p className="text-sm text-zinc-500 dark:text-zinc-500">
                {isLogin ? t("auth.noAccount") : t("auth.hasAccount")}{" "}
                <Link
                  to={isLogin ? "/register" : "/login"}
                  onClick={() => {
                    setError("");
                    setFormData({
                      email: "",
                      password: "",
                      confirmPassword: "",
                    });
                  }}
                  className="font-semibold text-zinc-800 dark:text-zinc-300 hover:text-indigo-600 dark:hover:text-white transition-colors relative inline-block group/link focus:outline-none"
                >
                  <span className="relative z-10">
                    {isLogin ? t("auth.signup") : t("auth.login")}
                  </span>
                  <span className="absolute bottom-0 left-0 w-0 h-[1px] bg-indigo-500 transition-all duration-300 group-hover/link:w-full"></span>
                </Link>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
