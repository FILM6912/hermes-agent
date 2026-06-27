import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { AlertCircle, AlertTriangle, Check, CheckCircle2, Copy, Info, X } from "lucide-react";
import { copyTextToClipboard } from "@/lib/clipboard";

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastOptions {
  type?: ToastType;
  duration?: number;
}

interface ToastContextValue {
  showToast: (message: string, options?: ToastOptions) => void;
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_MS = 3200;
const ERROR_MS = 4500;

const TYPE_STYLES: Record<ToastType, string> = {
  success:
    "bg-emerald-950/95 text-emerald-50 shadow-[0_8px_28px_rgba(0,0,0,0.45)] dark:bg-emerald-950/95 dark:text-emerald-50",
  error:
    "bg-rose-950/95 text-rose-50 shadow-[0_8px_28px_rgba(0,0,0,0.45)] dark:bg-rose-950/95 dark:text-rose-50",
  info:
    "bg-sky-950/95 text-sky-50 shadow-[0_8px_28px_rgba(0,0,0,0.45)] dark:bg-sky-950/95 dark:text-sky-50",
  warning:
    "bg-amber-950/95 text-amber-50 shadow-[0_8px_28px_rgba(0,0,0,0.45)] dark:bg-amber-950/95 dark:text-amber-50",
};

const TYPE_ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
  warning: AlertTriangle,
} as const;

function inferToastType(message: string, explicit?: ToastType): ToastType {
  if (explicit) return explicit;
  const low = message.toLowerCase();
  if (/fail|error|denied|invalid|unavailable/.test(low)) return "error";
  if (/warn|skipped|queued/.test(low)) return "warning";
  if (/saved|created|updated|removed|deleted|success|copied/.test(low)) return "success";
  return "info";
}

export function toastMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ToastProvider({ children }: { children: React.ReactNode }): React.ReactElement {
  const [toast, setToast] = useState<{ message: string; type: ToastType } | null>(null);
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const timerRef = useRef<number | null>(null);
  const pauseRef = useRef(false);

  const clearTimer = () => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const dismiss = useCallback(() => {
    clearTimer();
    setVisible(false);
    setCopied(false);
    setCopyFailed(false);
    window.setTimeout(() => setToast(null), 200);
  }, []);

  const scheduleDismiss = useCallback(
    (duration: number) => {
      clearTimer();
      timerRef.current = window.setTimeout(() => {
        if (!pauseRef.current) dismiss();
      }, duration);
    },
    [dismiss],
  );

  const showToast = useCallback(
    (message: string, options?: ToastOptions) => {
      const type = inferToastType(message, options?.type);
      const duration = options?.duration ?? (type === "error" ? ERROR_MS : DEFAULT_MS);
      pauseRef.current = false;
      setCopied(false);
      setCopyFailed(false);
      clearTimer();
      setToast({ message, type });
      window.requestAnimationFrame(() => setVisible(true));
      scheduleDismiss(duration);
    },
    [scheduleDismiss],
  );

  const handleCopy = useCallback(async () => {
    if (!toast) return;
    const ok = await copyTextToClipboard(toast.message);
    if (ok) {
      setCopyFailed(false);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } else {
      setCopied(false);
      setCopyFailed(true);
      window.setTimeout(() => setCopyFailed(false), 1500);
    }
  }, [toast]);

  const value = useMemo<ToastContextValue>(
    () => ({
      showToast,
      success: (message: string) => showToast(message, { type: "success" }),
      error: (message: string) => showToast(message, { type: "error" }),
    }),
    [showToast],
  );

  const Icon = toast ? TYPE_ICONS[toast.type] : Info;

  return (
    <ToastContext.Provider value={value}>
      {children}
      {typeof document !== "undefined" &&
        createPortal(
          toast ? (
            <div
              className="pointer-events-none fixed inset-x-0 top-0 z-[10001] flex justify-end p-6"
              aria-live="polite"
            >
              <div
                role="status"
                className={`pointer-events-auto flex max-w-[min(520px,calc(100vw-48px))] items-start gap-2.5 rounded-[10px] border-0 px-4 py-2.5 text-[13px] font-medium outline-none ring-0 transition-all duration-200 ease-out ${TYPE_STYLES[toast.type]} ${
                  visible ? "translate-y-0 opacity-100" : "-translate-y-1.5 opacity-0"
                }`}
                onMouseEnter={() => {
                  pauseRef.current = true;
                  clearTimer();
                }}
                onMouseLeave={() => {
                  pauseRef.current = false;
                  scheduleDismiss(1200);
                }}
              >
                <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere] whitespace-pre-wrap">
                  {toast.message}
                </span>
                {toast.type === "error" ? (
                  <button
                    type="button"
                    onClick={() => void handleCopy()}
                    className="rounded-md px-2 py-0.5 text-[11px] font-semibold opacity-85 transition-opacity hover:opacity-100"
                    aria-label="Copy error message"
                  >
                    {copied ? (
                      <span className="inline-flex items-center gap-1">
                        <Check className="h-3 w-3" />
                        Copied
                      </span>
                    ) : copyFailed ? (
                      <span>Failed</span>
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <Copy className="h-3 w-3" />
                        Copy
                      </span>
                    )}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={dismiss}
                  className="rounded-md p-0.5 opacity-70 transition-opacity hover:opacity-100"
                  aria-label="Dismiss notification"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : null,
          document.body,
        )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return ctx;
}
