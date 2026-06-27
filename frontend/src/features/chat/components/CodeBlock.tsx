import React, { useState } from "react";
import { Play, Copy, Check } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  vscDarkPlus,
  vs,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import { useTheme } from "../../../hooks/useTheme";
import { useLanguage } from "@/hooks/useLanguage";
import { getLanguageConfig } from "@/lib/languageUtils";
import { copyTextToClipboard } from "@/lib/clipboard";

const CopyButton = ({ code }: { code: string }) => {
  const { t } = useLanguage();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyTextToClipboard(code);
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1.5 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded transition-colors"
      title={copied ? t("codeBlock.copied") : t("codeBlock.copy")}
    >
      {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
};

interface CodeBlockProps {
  className?: string;
  children: React.ReactNode;
  onPreviewRequest?: (content: string) => void;
  [key: string]: any;
}

export const CodeBlock = React.memo<CodeBlockProps>(
  ({ className, children, onPreviewRequest, ...props }) => {
    const match = /language-(\w+)/.exec(className || "");
    const language = match ? match[1] : "";
    const content = String(children).replace(/\n$/, ""); 
    const isInline = !match && !content.includes("\n");

    const isPreviewable = ["html", "svg"].includes(language);
    const [isPreview, setIsPreview] = useState(false);
    const { isDark } = useTheme();
    const config = getLanguageConfig(language);

    if (isInline) {
      return (
        <code
          className="bg-zinc-200 dark:bg-zinc-800/80 text-zinc-800 dark:text-zinc-200 px-1.5 py-0.5 rounded text-[0.9em] font-mono border border-zinc-300 dark:border-zinc-700/50"
          {...props}
        >
          {children}
        </code>
      );
    }

    return (
      <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-[#0c0c0e] overflow-hidden my-4 w-full shadow-md group">
        <div className="flex items-center justify-between px-3 py-2 bg-zinc-50 dark:bg-[#18181b] border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center" style={{ color: config.color }}>
              {config.icon}
            </div>
            <span className="text-xs font-mono font-medium" style={{ color: config.color }}>
              {config.label}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <CopyButton code={content} />
            {/* Run Button for HTML */}
            {language === "html" && onPreviewRequest && (
              <button
                onClick={() => onPreviewRequest(content)}
                className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/20 hover:bg-emerald-200 dark:hover:bg-emerald-900/40 rounded transition-colors"
              >
                <Play className="w-3 h-3" />
                Run / Preview
              </button>
            )}

            {isPreviewable && (
              <div className="flex bg-zinc-100 dark:bg-zinc-900 rounded-lg p-0.5 border border-zinc-200 dark:border-zinc-800">
                <button
                  onClick={() => setIsPreview(false)}
                  className={`px-2 py-1 text-xs rounded-md transition-all font-medium ${!isPreview ? "bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm" : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"}`}
                >
                  Code
                </button>
                <button
                  onClick={() => setIsPreview(true)}
                  className={`px-2 py-1 text-xs rounded-md transition-all font-medium ${isPreview ? "bg-indigo-600 text-white shadow-sm" : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300"}`}
                >
                  Preview
                </button>
              </div>
            )}
          </div>
        </div>

        {isPreview && isPreviewable ? (
          <div className="bg-white p-0 overflow-hidden relative">
            <iframe
              srcDoc={content}
              className="w-full border-0 min-h-[300px]"
              sandbox="allow-scripts"
              title="Preview"
            />
          </div>
        ) : (
          <SyntaxHighlighter
            language={language}
            style={isDark ? vscDarkPlus : vs}
            customStyle={{
              margin: 0,
              padding: "1rem",
              fontSize: "0.875rem",
              lineHeight: "1.5",
              background: "transparent",
            }}
            codeTagProps={{
              style: {
                fontFamily: "monospace",
              },
            }}
            wrapLongLines={true}
            {...props}
          >
            {content}
          </SyntaxHighlighter>
        )}
      </div>
    );
  },
);

CodeBlock.displayName = "CodeBlock";
