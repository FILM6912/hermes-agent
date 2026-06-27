import React from "react";
import {
  FileCode2,
  Braces,
  Terminal,
  Database,
  FileText,
  Globe,
  Palette,
  Settings,
} from "lucide-react";

export type LanguageDisplayConfig = {
  label: string;
  color: string;
  icon: React.ReactNode;
};

const DEFAULT: LanguageDisplayConfig = {
  label: "Plain",
  color: "#71717a",
  icon: <FileText className="w-3.5 h-3.5" />,
};

const MAP: Record<string, Omit<LanguageDisplayConfig, "icon"> & { Icon: React.ComponentType<{ className?: string }> }> = {
  js: { label: "JavaScript", color: "#eab308", Icon: Braces },
  javascript: { label: "JavaScript", color: "#eab308", Icon: Braces },
  jsx: { label: "JSX", color: "#eab308", Icon: Braces },
  ts: { label: "TypeScript", color: "#3b82f6", Icon: Braces },
  typescript: { label: "TypeScript", color: "#3b82f6", Icon: Braces },
  tsx: { label: "TSX", color: "#3b82f6", Icon: Braces },
  py: { label: "Python", color: "#22c55e", Icon: Terminal },
  python: { label: "Python", color: "#22c55e", Icon: Terminal },
  json: { label: "JSON", color: "#f59e0b", Icon: Braces },
  html: { label: "HTML", color: "#f97316", Icon: Globe },
  css: { label: "CSS", color: "#06b6d4", Icon: Palette },
  scss: { label: "SCSS", color: "#ec4899", Icon: Palette },
  md: { label: "Markdown", color: "#a1a1aa", Icon: FileText },
  markdown: { label: "Markdown", color: "#a1a1aa", Icon: FileText },
  sql: { label: "SQL", color: "#8b5cf6", Icon: Database },
  sh: { label: "Shell", color: "#84cc16", Icon: Terminal },
  bash: { label: "Bash", color: "#84cc16", Icon: Terminal },
  yaml: { label: "YAML", color: "#14b8a6", Icon: Settings },
  yml: { label: "YAML", color: "#14b8a6", Icon: Settings },
  xml: { label: "XML", color: "#f97316", Icon: FileCode2 },
  svg: { label: "SVG", color: "#f97316", Icon: Globe },
  go: { label: "Go", color: "#22d3ee", Icon: FileCode2 },
  rust: { label: "Rust", color: "#f97316", Icon: FileCode2 },
  java: { label: "Java", color: "#ef4444", Icon: FileCode2 },
  cpp: { label: "C++", color: "#6366f1", Icon: FileCode2 },
  c: { label: "C", color: "#6366f1", Icon: FileCode2 },
};

export function getLanguageConfig(languageOrExt: string): LanguageDisplayConfig {
  const key = (languageOrExt || "").toLowerCase().replace(/^\./, "");
  const entry = MAP[key];
  if (!entry) return DEFAULT;
  const { Icon, ...rest } = entry;
  return {
    ...rest,
    icon: <Icon className="w-3.5 h-3.5" />,
  };
}
