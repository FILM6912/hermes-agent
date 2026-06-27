import React, { useMemo, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import { useMarkdownComponents } from "@/features/chat/hooks/useMarkdownComponents";
import { stripSkillFrontmatter } from "../utils/skillMarkdown";
import "katex/dist/katex.min.css";

interface SkillMarkdownViewProps {
  content: string;
  className?: string;
}

const headingClass = {
  h4: "text-base font-medium text-zinc-900 dark:text-zinc-100 mb-2 mt-3",
  h5: "text-sm font-semibold text-zinc-900 dark:text-zinc-100 mb-2 mt-3",
  h6: "text-sm font-medium uppercase tracking-wide text-zinc-600 dark:text-zinc-400 mb-2 mt-3",
} as const;

export const SkillMarkdownView: React.FC<SkillMarkdownViewProps> = ({
  content,
  className = "",
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const baseComponents = useMarkdownComponents({
    onViewImage: (url) => {
      const target = Array.isArray(url) ? url[0] : url;
      if (target) window.open(target, "_blank", "noopener,noreferrer");
    },
    scrollRootRef: scrollRef,
  });

  const components = useMemo(
    () => ({
      ...baseComponents,
      h4: ({ children }: { children?: React.ReactNode }) => (
        <h4 className={headingClass.h4}>{children}</h4>
      ),
      h5: ({ children }: { children?: React.ReactNode }) => (
        <h5 className={headingClass.h5}>{children}</h5>
      ),
      h6: ({ children }: { children?: React.ReactNode }) => (
        <h6 className={headingClass.h6}>{children}</h6>
      ),
    }),
    [baseComponents],
  );

  const { frontmatter, body } = stripSkillFrontmatter(content);

  return (
    <div ref={scrollRef} className={`space-y-4 ${className}`}>
      {frontmatter && (
        <details className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
          <summary className="cursor-pointer text-xs font-medium text-zinc-600 dark:text-zinc-400">
            Skill metadata
          </summary>
          <pre className="mt-2 overflow-x-auto font-mono text-[11px] leading-relaxed text-zinc-600 dark:text-zinc-400">
            {frontmatter}
          </pre>
        </details>
      )}
      <div className="skill-markdown min-w-0 text-[15px] leading-relaxed text-zinc-800 dark:text-zinc-300">
        <Markdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeRaw, rehypeKatex]}
          components={components as React.ComponentProps<typeof Markdown>["components"]}
        >
          {body || "(empty)"}
        </Markdown>
      </div>
    </div>
  );
};
