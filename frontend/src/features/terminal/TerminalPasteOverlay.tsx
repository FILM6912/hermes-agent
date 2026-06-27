import React, { useEffect, useRef } from "react";

interface TerminalPasteOverlayProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (text: string) => void;
}

export const TerminalPasteOverlay: React.FC<TerminalPasteOverlayProps> = ({
  open,
  onClose,
  onSubmit,
}) => {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const submit = () => {
    const value = inputRef.current?.value ?? "";
    if (!value) return;
    onSubmit(value);
    onClose();
  };

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Paste into terminal"
        className="w-full max-w-lg rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-xl"
      >
        <h2 className="text-sm font-semibold text-zinc-100">วางข้อความใน Terminal</h2>
        <p className="mt-1 text-xs leading-relaxed text-zinc-400">
          เข้าผ่าน HTTP/IP แล้วเบราว์เซอร์บล็อก clipboard โดยตรง — กด{" "}
          <kbd className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-[10px]">Ctrl+V</kbd>{" "}
          ในช่องด้านล่าง แล้วกด Paste
        </p>
        <textarea
          ref={inputRef}
          rows={5}
          className="mt-3 w-full resize-y rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/30"
          placeholder="Paste here…"
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Paste
          </button>
        </div>
      </div>
    </div>
  );
};
