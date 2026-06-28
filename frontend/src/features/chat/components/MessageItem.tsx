import React, { useState } from "react";
import { AIIcon } from "./AIIcon";
import {
  Copy,
  RotateCw,
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  File as FileIcon,
  Loader2,
} from "lucide-react";
import { Message, ModelConfig, ProcessStep } from "@/types";
import { LegacyThinkingTrace } from "./ThinkingTrace";
import { ActivityTimeline } from "./ActivityTimeline";
import {
  shouldUseActivityTimeline,
  thinkingStepsOnly,
  toolStepsOnly,
} from "../utils/activityTimeline";
import {
  deriveContentFromBlocks,
  resolveMessageBlocks,
} from "../utils/messageBlocks";
import { isDistinctThinking } from "../utils/thinkingDisplay";
import { stripMediaTokens } from "../utils/mediaTokens";
import type { MessageBlock } from "@/types";
import { ToolCard } from "./ToolCard";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { useLanguage } from "@/hooks/useLanguage";
import { AttachmentImage } from "./AttachmentImage";
import {
  attachmentPreviewUrls,
  resolveAttachmentDisplayUrl,
} from "@/services/hermes/attachments";

const FILE_EXT_PATTERN =
  /(?:docx?|xlsx?|pptx?|pdf|txt|csv|md|rtf|odt|ods|odp|zip|rar|7z|json|xml|html?|png|jpe?g|gif|webp|svg|mp3|mp4|wav|mov)/i;

const normalizeCitationSyntax = (content: string): string => {
  if (!content) return content;

  // Normalize common citation styles from code chat tools:
  // - 【label†https://example.com】 -> [label](https://example.com)
  // - 〖label†https://example.com〗 -> [label](https://example.com)
  // - 【label†ref-id】            -> [label](ref-id)
  let next = content.replace(/[【〖]([^†\]\n]+)†([^\]】〗\n]+)[】〗]/g, (_match, rawLabel, rawRef) => {
    const label = String(rawLabel).trim();
    const ref = String(rawRef).trim();
    if (!label || !ref) return _match;
    return `[${label}](${ref})`;
  });

  // Convert filenames inside footnote definitions to markdown links so they become clickable.
  // Example: "[^1]: Brake_OffLine_Specification_LessonLearned.docx"
  //      -> "[^1]: [Brake_OffLine_Specification_LessonLearned.docx](Brake_OffLine_Specification_LessonLearned.docx)"
  next = next.replace(
    new RegExp(
      String.raw`^(\s*\[\^[^\]\n]+\]:\s*)([^\s\[\<][^\s\<\>]*?\.` + FILE_EXT_PATTERN.source + String.raw`)(\s|$)`,
      "gim"
    ),
    (_match, prefix, fileName, tail) => `${prefix}[${fileName}](${fileName})${tail}`
  );

  return next;
};

function prepareAssistantMarkdown(mainContent: string): string | null {
  let text = mainContent;

  if (text.includes("<|begin_of_solution|>")) {
    const parts = text.split("<|begin_of_solution|>");
    text = parts.slice(1).join("<|begin_of_solution|>");
    text = text.replace("<|end_of_solution|>", "");
  }

  text = text.replace(/<think>[\s\S]*?<\/redacted_thinking>/g, "");
  text = text.replace(/<think>[\s\S]*$/, "");
  text = stripMediaTokens(text);
  text = text.trim();

  if (!text) return null;

  const coloredContent = text.replace(
    /“([\s\S]*?)”/g,
    '<span class="text-orange-500 font-medium">$1</span>',
  );
  return normalizeCitationSyntax(coloredContent);
}

function trimTrailingInvisible(text: string): string {
  return text.replace(/[ \t\r\n]+$/g, "");
}

interface MessageItemProps {
  message: Message;
  isLastMessage: boolean;
  isLoading: boolean;
  isStreaming: boolean;
  copiedId: string | null;
  modelConfig: ModelConfig;
  onCopy: (id: string, text: string) => void;
  onRegenerate: (id: string) => void;
  onEdit?: (id: string, newContent: string) => void;
  onVersionChange?: (id: string, newIndex: number) => void;
  onViewImage: (url: string | string[]) => void;
  editingId: string | null;
  editValue: string;
  onStartEdit: (msg: Message) => void;
  onSubmitEdit: (id: string) => void;
  onCancelEdit: () => void;
  setEditValue: (value: string) => void;
  markdownComponents: any;
  // AI version props
  onAIVersionChange?: (id: string, newIndex: number) => void;
  onRegenVersionChange?: (id: string, aiIndex: number, regenIndex: number) => void;
  /** Resolved agent name to avoid flashing on refresh */
  resolvedAgentName?: string;
  /** Active Hermes session id — used to resolve attachment preview URLs. */
  sessionId?: string;
  /** Composer workspace fallback for `.uploads/` previews. */
  composerWorkspace?: string;
  onOpenToolInPreview?: (step: ProcessStep) => void;
}

export const MessageItem: React.FC<MessageItemProps> = ({
  message: msg,
  isLastMessage,
  isLoading,
  isStreaming,
  copiedId,
  modelConfig,
  onCopy,
  onRegenerate,
  onVersionChange,
  onViewImage,
  editingId,
  editValue,
  onStartEdit,
  onSubmitEdit,
  onCancelEdit,
  setEditValue,
  markdownComponents,
  onAIVersionChange: _onAIVersionChange,
  onRegenVersionChange,
  resolvedAgentName,
  sessionId,
  composerWorkspace,
  onOpenToolInPreview,
}) => {
  const { t } = useLanguage();
  const [resolvedAttachmentUrls, setResolvedAttachmentUrls] = useState<
    Record<number, string>
  >({});
  const isAssistant = msg.role === "assistant";
  const displayContent = msg.content;
  const isGenerating =
    isStreaming && isAssistant && (isLastMessage || !msg.content);
  const hasVersions = msg.versions && msg.versions.length > 1;
  const currentVersion = (msg.currentVersionIndex || 0) + 1;
  const totalVersions = msg.versions?.length || 1;
  const isEditing = editingId === msg.id;
  const currentVersionIndex = msg.currentVersionIndex || 0;

  // Get current version (for both user and assistant messages)
  const currentMessageVersion = msg.versions?.[currentVersionIndex];

  // AI versions (from current message version)
  const currentAIIndex = currentMessageVersion?.currentAIIndex || 0;
  const currentAIVersion = currentMessageVersion?.aiVersions?.[currentAIIndex];

  // Regen versions (for current AI version)
  const currentRegenIndex = currentAIVersion?.currentRegenIndex || 0;
  const totalRegenVersions = currentAIVersion?.regenVersions?.length || 1;
  const hasRegenVersions = totalRegenVersions > 1;

  const hasSteps = Boolean(msg.steps && msg.steps.length > 0);
  const bodyBlocks = isAssistant ? resolveMessageBlocks(msg) : [];
  const hasBlockBody = bodyBlocks.some(
    (b) =>
      (b.type === "text" && b.content.trim()) ||
      b.type === "thinking" ||
      b.type === "tools",
  );
  const showAssistantBody =
    isAssistant && (Boolean(msg.content) || hasSteps || hasBlockBody || isGenerating);
  const showTypingCursor = isAssistant && isLastMessage && isGenerating;

  return (
    <div
      className={`msg-container flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-300 ${msg.role === "user" ? "items-end" : "items-start"}`}
    >
      <div className="mb-3 flex items-center gap-2 px-1">
        {isAssistant && (
          <div className="w-8 h-8 rounded-full bg-linear-to-br from-[#1447E6] to-[#0d35b8] flex items-center justify-center">
            <AIIcon size="sm" className="text-white" />
          </div>
        )}
        <span className="text-xs text-zinc-500 font-medium">
          {msg.role === "user" ? t("chat.you") : (resolvedAgentName || modelConfig.name || t("chat.selectAgent")).toUpperCase()}
        </span>
      </div>

      {/* Assistant Message Controls */}

      {showAssistantBody && (
        <div className="w-full">
          {/* Legacy tag-based thinking (skip when structured blocks already carry reasoning) */}
          {(() => {
            if (!msg.content) return null;
            if (bodyBlocks.some((b) => b.type === "thinking")) return null;

            const hasThinkTag = msg.content.includes("<think>");
            const hasSolutionTag = msg.content.includes("<|begin_of_solution|>");

            if (!hasThinkTag && !hasSolutionTag) return null;

            const answerForCompare =
              deriveContentFromBlocks(bodyBlocks) ||
              prepareAssistantMarkdown(msg.content) ||
              "";

            const thinkBlocks = [];

            // Handle <think> tags
            if (hasThinkTag) {
              const closedMatches = [...msg.content.matchAll(/<think>([\s\S]*?)<\/redacted_thinking>/g)];
              for (const match of closedMatches) {
                thinkBlocks.push({ content: match[1], isComplete: true, label: t("chat.thoughtProcess") || "Thought Process" });
              }

              const lastCloseIndex = msg.content.lastIndexOf('</think>');
              const lastOpenIndex = msg.content.lastIndexOf('<think>');

              if (lastOpenIndex > lastCloseIndex) {
                const openContent = msg.content.substring(
                  lastOpenIndex + "<think>".length,
                );
                const solutionTagIndex = openContent.indexOf('<|begin_of_solution|>');
                const finalContent = solutionTagIndex !== -1 ? openContent.substring(0, solutionTagIndex) : openContent;
                thinkBlocks.push({ content: finalContent, isComplete: solutionTagIndex !== -1, label: t("chat.thoughtProcess") || "Thought Process" });
              }
            }

            // Handle <|begin_of_solution|> tags (often used in specialized models)
            if (hasSolutionTag) {
              const firstSolutionIndex = msg.content.indexOf('<|begin_of_solution|>');
              let preSolutionContent = msg.content.substring(0, firstSolutionIndex);

              preSolutionContent = preSolutionContent.replace(
                /<think>[\s\S]*?<\/redacted_thinking>/g,
                "",
              ).trim();
              preSolutionContent = preSolutionContent.replace(/\|$/, '').trim();

              if (preSolutionContent) {
                const isDuplicate = thinkBlocks.some(block => block.content.trim() === preSolutionContent);
                if (!isDuplicate) {
                  thinkBlocks.push({
                    content: preSolutionContent,
                    isComplete: true,
                    label: t("chat.process") || "Process"
                  });
                }
              }
            }

            const distinctThinkBlocks = thinkBlocks.filter((block) =>
              isDistinctThinking(block.content, answerForCompare),
            );
            if (distinctThinkBlocks.length === 0) return null;

            return (
              <div className="mt-1 mb-2 w-full space-y-2">
                {distinctThinkBlocks.map((block, idx) => (
                  <LegacyThinkingTrace
                    key={idx}
                    block={block}
                    isStreaming={isStreaming}
                  />
                ))}
              </div>
            );
          })()}

          {(() => {
            const lastStepId = msg.steps?.[msg.steps.length - 1]?.id;
            const useStructuredBlocks =
              Boolean(msg.blocks?.length) || bodyBlocks.length > 1;
            const textBlockIndexes = bodyBlocks
              .map((block, index) => ({ block, index }))
              .filter(({ block }) => block.type === "text" && Boolean(prepareAssistantMarkdown(block.content)))
              .map(({ index }) => index);
            const lastTextBlockIndex =
              textBlockIndexes.length > 0
                ? textBlockIndexes[textBlockIndexes.length - 1]
                : -1;

            const answerText =
              deriveContentFromBlocks(bodyBlocks) ||
              prepareAssistantMarkdown(msg.content) ||
              "";

            const renderBlock = (block: MessageBlock, index: number) => {
              if (block.type === "thinking") {
                const visibleSteps = block.steps.filter((step) =>
                  isDistinctThinking(step.content, answerText),
                );
                if (visibleSteps.length === 0) return null;
                return (
                  <div key={`think-${index}`} className="w-full">
                    <ActivityTimeline
                      steps={visibleSteps}
                      isStreaming={isStreaming && isLastMessage && isGenerating}
                      onOpenToolInPanel={onOpenToolInPreview}
                    />
                  </div>
                );
              }
              if (block.type === "tools") {
                const useActivity = shouldUseActivityTimeline(block.steps);
                if (!block.steps.length) return null;
                return (
                  <div key={`tools-${index}`} className="w-full">
                    {useActivity ? (
                      <ActivityTimeline
                        steps={block.steps}
                        isStreaming={isStreaming && isLastMessage && isGenerating}
                        onOpenToolInPanel={onOpenToolInPreview}
                      />
                    ) : (
                      block.steps.map((step) => (
                        <ToolCard
                          key={step.id}
                          step={step}
                          isLastStep={step.id === lastStepId && isGenerating}
                          onOpenInPanel={onOpenToolInPreview}
                        />
                      ))
                    )}
                  </div>
                );
              }
              const normalized = prepareAssistantMarkdown(block.content);
              if (!normalized) return null;
              const shouldShowCursor = showTypingCursor && index === lastTextBlockIndex;
              const baseContent = shouldShowCursor
                ? trimTrailingInvisible(normalized)
                : normalized;
              return (
                <div
                  key={`text-${index}`}
                  className={`leading-relaxed group relative w-full text-zinc-800 dark:text-zinc-300 pl-1 ${
                    shouldShowCursor ? "typing-cursor-inline" : ""
                  }`}
                >
                  <Markdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw]}
                    components={markdownComponents as any}
                  >
                    {baseContent}
                  </Markdown>
                </div>
              );
            };

            if (useStructuredBlocks) {
              return (
                <div className="w-full space-y-2">
                  {bodyBlocks.map((block, index) => renderBlock(block, index))}
                </div>
              );
            }

            if (!hasSteps) return null;

            const allSteps = msg.steps!;
            const thinking = thinkingStepsOnly(allSteps).filter((step) =>
              isDistinctThinking(step.content, answerText),
            );
            const tools = toolStepsOnly(allSteps);
            const useActivity = shouldUseActivityTimeline(allSteps);

            return (
              <div className="w-full mb-4 space-y-1">
                {thinking.length > 0 ? (
                  <ActivityTimeline
                    steps={thinking}
                    isStreaming={isStreaming && isLastMessage && isGenerating}
                  />
                ) : null}
                {useActivity && tools.length > 0 ? (
                  <ActivityTimeline
                    steps={tools}
                    isStreaming={isStreaming && isLastMessage && isGenerating}
                    onOpenToolInPanel={onOpenToolInPreview}
                  />
                ) : (
                  tools.map((step) => (
                    <ToolCard
                      key={step.id}
                      step={step}
                      isLastStep={step.id === lastStepId && isGenerating}
                      onOpenInPanel={onOpenToolInPreview}
                    />
                  ))
                )}
              </div>
            );
          })()}

          {!msg.blocks?.length && msg.content && bodyBlocks.length <= 1 && (
            <div
              className={`leading-relaxed group relative w-full text-zinc-800 dark:text-zinc-300 pl-1 ${
                showTypingCursor ? "typing-cursor-inline" : ""
              }`}
            >
              {(() => {
                const normalized = prepareAssistantMarkdown(msg.content);
                if (!normalized) return null;
                const baseContent = showTypingCursor
                  ? trimTrailingInvisible(normalized)
                  : normalized;
                return (
                  <Markdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw]}
                    components={markdownComponents as any}
                  >
                    {baseContent}
                  </Markdown>
                );
              })()}
            </div>
          )}

          {isGenerating && !msg.content && !hasSteps && !hasBlockBody && (
            <div className="flex items-center gap-2 pl-1 mb-2 text-xs text-zinc-500">
              <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
              <span>{t("chat.thinking")}</span>
            </div>
          )}
        </div>
      )}

      {/* User Message (Simple Display) */}
      {!isAssistant && (
        <div className={`text-sm md:text-base leading-relaxed group relative ${msg.role === "user"
          ? "w-full flex flex-col items-end"
          : "w-full text-zinc-800 dark:text-zinc-300 pl-1"
          }`}>
          {msg.role === "user" ? (
            isEditing ? (
              <div className="w-full bg-background dark:bg-zinc-900 rounded-2xl p-3 border border-border dark:border-zinc-700 shadow-sm">
                <textarea
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className="w-full bg-transparent text-zinc-700 dark:text-zinc-100 resize-none outline-none text-sm leading-relaxed p-1"
                  rows={Math.max(2, editValue.split("\n").length)}
                  autoFocus
                />
                <div className="flex justify-end gap-2 mt-3 pt-2 border-t border-zinc-200 dark:border-zinc-700">
                  <button
                    onClick={onCancelEdit}
                    className="px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors"
                  >
                    {t("chat.cancel")}
                  </button>
                  <button
                    onClick={() => onSubmitEdit(msg.id)}
                    className="px-3 py-1.5 text-xs font-medium bg-linear-to-r from-[#1447E6] to-[#0d35b8] text-white hover:from-[#0d35b8] hover:to-[#082a8f] rounded-lg transition-all shadow-sm active:scale-95"
                  >
                    {t("chat.saveSubmit")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-end gap-1 w-full">
                {/* Attachments Display */}
                {msg.attachments && msg.attachments.length > 0 && (
                  <div className="flex flex-wrap justify-end gap-2 mb-1 w-full">
                    {msg.attachments.map((att, i) => {
                      const previewUrls = attachmentPreviewUrls(sessionId, att, {
                        workspace: composerWorkspace?.trim() || undefined,
                      });
                      const resolvedUrl = resolvedAttachmentUrls[i];
                      const lightboxUrls = resolvedUrl
                        ? [
                            resolvedUrl,
                            ...previewUrls.filter((url) => url !== resolvedUrl),
                          ]
                        : previewUrls;
                      return att.type === "image" ? (
                        <div
                          key={i}
                          onClick={() =>
                            onViewImage(
                              lightboxUrls.length > 0
                                ? lightboxUrls
                                : [
                                    resolveAttachmentDisplayUrl(sessionId, att, {
                                      workspace: composerWorkspace?.trim() || undefined,
                                    }),
                                  ].filter(
                                    Boolean,
                                  ),
                            )
                          }
                          className="group/img relative inline-block overflow-hidden rounded-xl cursor-zoom-in"
                        >
                          <AttachmentImage
                            urls={previewUrls}
                            alt={att.name}
                            onResolvedUrl={(url) =>
                              setResolvedAttachmentUrls((prev) =>
                                prev[i] === url ? prev : { ...prev, [i]: url },
                              )
                            }
                            className="block max-w-[150px] max-h-[150px] rounded-xl object-cover hover:scale-105 transition-transform duration-300"
                          />
                        </div>
                      ) : (
                        <div
                          key={i}
                          className="flex items-center gap-2 bg-muted border border-border px-3 py-2 rounded-xl text-xs text-foreground"
                        >
                          <FileIcon className="w-3.5 h-3.5 text-[#1447E6] dark:text-blue-400" />
                          <span className="truncate max-w-[120px]">
                            {att.name}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}

                {displayContent && (
                  <div className="bg-linear-to-br from-blue-50 to-blue-100 dark:from-blue-950/30 dark:to-blue-900/30 text-zinc-700 dark:text-zinc-100 px-4 py-3 rounded-2xl rounded-tr-sm shadow-sm border border-blue-200 dark:border-blue-900/50 whitespace-pre-wrap text-left relative group">
                    {displayContent}
                  </div>
                )}

                {/* User Message Controls (Edit / Versions) */}
                <div className="msg-actions flex items-center gap-2 mt-1 px-1">
                  {hasVersions && onVersionChange && (
                    <div className="flex items-center gap-1 p-0.5">
                      <button
                        onClick={() =>
                          onVersionChange(
                            msg.id,
                            (msg.currentVersionIndex || 0) - 1,
                          )
                        }
                        disabled={(msg.currentVersionIndex || 0) === 0 || isStreaming}
                        className="p-1 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer transition-colors"
                      >
                        <ChevronLeft className="w-3 h-3" />
                      </button>
                      <span className="text-[10px] font-medium text-zinc-500 px-1 min-w-[24px] text-center">
                        {currentVersion} / {totalVersions}
                      </span>
                      <button
                        onClick={() =>
                          onVersionChange(
                            msg.id,
                            (msg.currentVersionIndex || 0) + 1,
                          )
                        }
                        disabled={currentVersion === totalVersions || isStreaming}
                        className="p-1 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer transition-colors"
                      >
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                  <button
                    onClick={() => onStartEdit(msg)}
                    className="p-1.5 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-all cursor-pointer active:scale-95"
                    title={t("chat.edit")}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => onCopy(msg.id, msg.content)}
                    className="p-1.5 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-all cursor-pointer active:scale-95"
                    title={t("chat.copy")}
                  >
                    {copiedId === msg.id ? (
                      <Check className="w-3.5 h-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              </div>
            )
          ) : (
            null
          )}
        </div>
      )}



      {/* Assistant Message Controls */}
      {
        isAssistant && !isGenerating && (
          <div className="flex items-center gap-4 mt-3 pl-1 select-none">
            {/* Regen Version Controls - Show when has regen versions */}
            {hasRegenVersions && onRegenVersionChange && (
              <div className="msg-actions flex items-center gap-1 p-0.5">
                <button
                  onClick={() => onRegenVersionChange(msg.id, currentAIIndex, currentRegenIndex - 1)}
                  disabled={currentRegenIndex === 0 || isStreaming}
                  className="p-1 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer transition-colors"
                  title="Previous regen version"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-[10px] font-medium text-zinc-500 px-1 min-w-[30px] text-center">
                  {currentRegenIndex + 1} / {totalRegenVersions}
                </span>
                <button
                  onClick={() => onRegenVersionChange(msg.id, currentAIIndex, currentRegenIndex + 1)}
                  disabled={currentRegenIndex === totalRegenVersions - 1 || isStreaming}
                  className="p-1 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer transition-colors"
                  title="Next regen version"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}

            <div className="msg-actions flex items-center gap-1">
              <button
                onClick={() => onCopy(msg.id, msg.content)}
                className="p-1.5 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-all cursor-pointer active:scale-95"
                title={t("chat.copy")}
              >
                {copiedId === msg.id ? (
                  <Check className="w-3.5 h-3.5 text-emerald-500" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
              <button
                onClick={() => onRegenerate(msg.id)}
                disabled={isLoading || isStreaming}
                className="p-1.5 hover:bg-zinc-300 dark:hover:bg-zinc-700/50 rounded-md text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 transition-all cursor-pointer active:scale-95"
                title={t("chat.regenerate")}
              >
                <RotateCw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )
      }

      {/* Suggestion Loading Animation */}
      {null}
      <style>{`
        @keyframes cursor-blink {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
        .typing-cursor-inline > :last-child::after {
          content: "";
          display: inline-block;
          width: 2px;
          height: 1em;
          margin-left: 2px;
          vertical-align: -0.15em;
          background: rgb(249 115 22);
          animation: cursor-blink 0.5s steps(1, end) infinite;
        }
        :is(.dark) .typing-cursor-inline > :last-child::after {
          background: rgb(251 146 60);
        }
      `}</style>
    </div >
  );
};
