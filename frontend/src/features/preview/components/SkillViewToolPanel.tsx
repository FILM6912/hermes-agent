import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { ProcessStep } from "@/types";
import { useLanguage } from "@/hooks/useLanguage";
import { fetchSkillContent } from "@/features/skills/api/skillsApi";
import { SkillMarkdownView } from "@/features/skills/components/SkillMarkdownView";
import {
  isSkillViewToolName,
  parseSkillViewFromStep,
  skillViewNeedsContentFetch,
  type SkillViewOutput,
} from "@/features/preview/utils/parseSkillViewToolPayload";

const sectionHeadingClass =
  "text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400";

const SkillSection = ({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) => (
  <section className="space-y-2">
    <h3 className={sectionHeadingClass}>{title}</h3>
    {children}
  </section>
);

export type SkillViewToolPanelProps = {
  step: ProcessStep;
};

export const SkillViewToolPanel: React.FC<SkillViewToolPanelProps> = ({ step }) => {
  const { t } = useLanguage();
  const isError = step.type === "error";
  const { input, output: parsedOutput } = useMemo(
    () => parseSkillViewFromStep(step),
    [step.content, step.preview, step.toolName, step.title],
  );
  const [fetchedContent, setFetchedContent] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const fetchedSkillRef = useRef<string | null>(null);

  const skillName =
    parsedOutput?.name ??
    input?.name ??
    (isSkillViewToolName(step.toolName ?? step.title)
      ? (step.title ?? step.toolName ?? "skill")
      : "skill");
  const inlineContent = parsedOutput?.content?.trim() ?? "";
  const needsFetch = skillViewNeedsContentFetch(input, parsedOutput);

  useEffect(() => {
    setFetchedContent(null);
    setFetchError(null);
    setFetching(false);
    fetchedSkillRef.current = null;
  }, [skillName]);

  useEffect(() => {
    if (inlineContent || !needsFetch) {
      setFetching(false);
      return;
    }
    if (fetchedSkillRef.current === skillName) {
      setFetching(false);
      return;
    }

    let cancelled = false;
    setFetching(true);
    void fetchSkillContent(skillName)
      .then((data) => {
        if (cancelled) return;
        fetchedSkillRef.current = skillName;
        if (data.error || data.success === false) {
          setFetchError(data.error ?? "Failed to load skill content");
          return;
        }
        if (data.content?.trim()) {
          setFetchedContent(data.content);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFetchError(err instanceof Error ? err.message : "Failed to load skill content");
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });

    return () => {
      cancelled = true;
    };
  }, [skillName, needsFetch, inlineContent]);

  const output: SkillViewOutput | null = useMemo(() => {
    if (!parsedOutput && !fetchedContent) return parsedOutput;
    const content = parsedOutput?.content?.trim() || fetchedContent || undefined;
    if (!parsedOutput && fetchedContent) {
      return {
        success: true,
        name: skillName,
        tags: [],
        relatedSkills: [],
        content,
      };
    }
    if (!parsedOutput) return null;
    return {
      ...parsedOutput,
      content,
    };
  }, [fetchedContent, parsedOutput, skillName]);

  const showPending =
    !output?.content?.trim() &&
    !output?.description &&
    !output?.error &&
    !fetchError &&
    (step.status === "running" || fetching);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 pb-3 dark:border-zinc-800">
        <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{skillName}</span>
        {step.duration ? (
          <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">{step.duration}</span>
        ) : null}
        {fetching && !output?.content?.trim() && !output?.description ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" aria-hidden />
        ) : step.status === "completed" && !isError && output?.success !== false ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
        ) : null}
        {isError || output?.success === false ? (
          <span className="inline-flex items-center gap-1 rounded-md bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950/50 dark:text-red-300">
            <AlertCircle className="h-3 w-3" />
            {t("preview.toolError") || "Error"}
          </span>
        ) : null}
      </div>

      {input ? (
        <SkillSection title={t("preview.skillViewRequest") || "Request"}>
          <p className="text-sm text-zinc-800 dark:text-zinc-200">
            <span className="text-zinc-500 dark:text-zinc-400">
              {t("preview.skillViewSkillName") || "Skill"}
              {": "}
            </span>
            <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[13px] text-violet-700 dark:bg-zinc-800 dark:text-violet-300">
              {input.name}
            </code>
          </p>
        </SkillSection>
      ) : null}

      {output?.description ? (
        <SkillSection title={t("preview.skillViewDescription") || "Description"}>
          <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {output.description}
          </p>
        </SkillSection>
      ) : null}

      {output?.tags.length ? (
        <SkillSection title={t("preview.skillViewTags") || "Tags"}>
          <ul className="flex flex-wrap gap-1.5">
            {output.tags.map((tag) => (
              <li
                key={tag}
                className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px] font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
              >
                {tag}
              </li>
            ))}
          </ul>
        </SkillSection>
      ) : null}

      {output?.relatedSkills.length ? (
        <SkillSection title={t("preview.skillViewRelated") || "Related skills"}>
          <ul className="flex flex-wrap gap-1.5">
            {output.relatedSkills.map((name) => (
              <li
                key={name}
                className="rounded-md border border-zinc-200 px-2 py-0.5 font-mono text-[11px] text-zinc-700 dark:border-zinc-700 dark:text-zinc-300"
              >
                {name}
              </li>
            ))}
          </ul>
        </SkillSection>
      ) : null}

      {output?.content?.trim() ? (
        <SkillSection title={t("preview.skillViewContent") || "Skill instructions"}>
          <div className="rounded-lg border border-zinc-200 bg-white px-3 py-3 dark:border-zinc-800 dark:bg-zinc-950/40">
            <SkillMarkdownView content={output.content} />
          </div>
        </SkillSection>
      ) : null}

      {output?.error ? (
        <SkillSection title={t("preview.toolError") || "Error"}>
          <p className="text-sm text-red-700 dark:text-red-300">{output.error}</p>
        </SkillSection>
      ) : null}

      {fetchError ? (
        <SkillSection title={t("preview.toolError") || "Error"}>
          <p className="text-sm text-red-700 dark:text-red-300">{fetchError}</p>
        </SkillSection>
      ) : null}

      {showPending ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {t("preview.toolOutputPending") || "Waiting for tool result…"}
        </p>
      ) : null}

      {!showPending &&
      !output?.content?.trim() &&
      !output?.description &&
      !output?.error &&
      !fetchError ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {t("chat.activityNoDetail") || "No additional details."}
        </p>
      ) : null}
    </div>
  );
};
