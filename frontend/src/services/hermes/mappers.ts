/**
 * Map Hermes session/message payloads to Agent-UI ChatSession / Message types.
 */
import {
  Attachment,
  ChatSession,
  Message,
  MessageBlock,
  ProcessStep,
} from "@/types";
import type {
  HermesSessionDetail,
  HermesSessionMessage,
  HermesSessionSummary,
} from "@/types/hermes/sessions";
import { mergeAttachmentsWithContentMarker } from "./attachments";
import { formatClarifyEchoMessage } from "@/features/clarify/utils/formatClarifyEcho";
import { buildAssistantBlocksFromTextAndTools } from "@/features/chat/utils/messageBlocks";
import { contextUsageFromHermesSession } from "@/features/chat/utils/contextUsage";
import {
  finalizeRunningProcessSteps,
  finalizeRunningStepsInBlocks,
} from "@/features/chat/utils/finalizeRunningProcessSteps";
import {
  combinedReasoningText,
  isDistinctThinking,
} from "@/features/chat/utils/thinkingDisplay";
import {
  compressionAnchorFromHermesDetail,
  isContextCompressionMarker,
} from "@/features/chat/utils/compressionAnchor";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

function parseJsonObject(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) return value;
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  try {
    const parsed = JSON.parse(text);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function inferToolNameFromPayload(payload: Record<string, unknown> | null): string | null {
  if (!payload) return null;
  if ("bytes_written" in payload || "dirs_created" in payload) return "write_file";
  if ("content" in payload || "contents" in payload) return "read_file";
  if ("matches" in payload || "results" in payload) return "search_files";
  if ("exit_code" in payload || "stdout" in payload || "stderr" in payload) return "terminal";
  return null;
}

/** Extract display text from Hermes message content (string or content blocks). */
export function extractMessageContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (content === null || content === undefined) return "";
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") return block;
        if (!isRecord(block)) return "";
        if (block.type === "reasoning") return "";
        if (typeof block.text === "string") return block.text;
        if (typeof block.content === "string") return block.content;
        return "";
      })
      .filter((part) => part.length > 0)
      .join("\n");
  }
  if (isRecord(content)) {
    if (typeof content.text === "string") return content.text;
    if (typeof content.content === "string") return content.content;
  }
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
}

function mapAttachments(raw: unknown): Attachment[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  const attachments: Attachment[] = [];
  for (const item of raw) {
    if (typeof item === "string" && item.trim()) {
      const path = item.trim();
      const name = path.split(/[/\\]/).pop() || "attachment";
      attachments.push({
        name,
        type: name.match(/\.(png|jpe?g|gif|webp|svg)$/i) ? "image" : "file",
        content: path,
        path,
      });
      continue;
    }
    if (!isRecord(item)) continue;
    const storagePath = asString(item.path || item.url);
    const workspaceRel = asString(item.workspace_rel);
    const legacyContent = asString(item.content);
    const displayPath = storagePath || legacyContent || workspaceRel;
    if (!displayPath) continue;
    const mime = asString(item.mime_type || item.mimeType);
    const lookupName =
      asString(item.name) ||
      storagePath.split(/[/\\]/).pop() ||
      workspaceRel.split(/[/\\]/).pop() ||
      "attachment";
    attachments.push({
      name: lookupName,
      type:
        mime.startsWith("image/") ||
        /\.(png|jpe?g|gif|webp|svg)$/i.test(displayPath)
          ? "image"
          : "file",
      content: storagePath || workspaceRel || legacyContent,
      path: storagePath || workspaceRel || legacyContent,
      workspace_rel: workspaceRel || undefined,
      mimeType: mime || undefined,
    });
  }
  return attachments.length > 0 ? attachments : undefined;
}

type HermesLiveToolCall = {
  id: string;
  name: string;
  preview?: string;
  args?: unknown;
  snippet?: string;
  done: boolean;
  cancelled?: boolean;
  isError?: boolean;
  duration?: number;
  /** Assistant display-text length when this tool started (stream block interleaving). */
  afterTextLength?: number;
};

const CANCEL_MARKER_PATTERNS = [
  "task cancelled",
  "task canceled",
  "response interrupted",
] as const;

function isHermesCancelMarkerMessage(msg: HermesSessionMessage): boolean {
  const content = extractMessageContent(msg.content).trim().toLowerCase();
  if (!content) return false;
  return CANCEL_MARKER_PATTERNS.some((pattern) => content.includes(pattern));
}

function assistantRunHasCancelMarker(
  run: { msg: HermesSessionMessage; index: number }[],
): boolean {
  return run.some(
    (entry) => entry.msg._error === true || isHermesCancelMarkerMessage(entry.msg),
  );
}

/** Mark incomplete live tool calls as cancelled (stream abort / user stop). */
export function finalizeLiveToolCallsForCancel(
  tools: HermesLiveToolCall[],
): HermesLiveToolCall[] {
  return tools.map((tool) =>
    tool.done ? tool : { ...tool, done: true, cancelled: true },
  );
}

function liveToolStatus(tool: HermesLiveToolCall): ProcessStep["status"] {
  if (!tool.done) return "running";
  if (tool.cancelled) return "cancelled";
  return tool.isError ? "completed" : "completed";
}

import { displayVirtualPathsInToolArgs } from "@/services/hermes/displayVirtualPaths";

function formatToolArgs(args: unknown): string {
  const displayed = displayVirtualPathsInToolArgs(args);
  if (typeof displayed === "string") return displayed;
  if (displayed === undefined || displayed === null) return "";
  try {
    return JSON.stringify(displayed, null, 2);
  } catch {
    return String(displayed);
  }
}

/** SSE tool_complete sends result in `preview`; session rows may use snippet/output/result. */
function toolResultSnippetFromPayload(
  payload: Record<string, unknown>,
  fallback = "",
): string {
  return (
    asString(payload.snippet) ||
    asString(payload.preview) ||
    asString(payload.output) ||
    asString(payload.result) ||
    fallback
  );
}

function liveToolCallToProcessStep(tool: HermesLiveToolCall): ProcessStep {
  const argsText = formatToolArgs(tool.args);
  const snippet = asString(tool.snippet) || asString(tool.preview);
  const duration =
    typeof tool.duration === "number" && Number.isFinite(tool.duration)
      ? `${tool.duration}s`
      : undefined;

  return {
    id: tool.id,
    type: tool.isError ? "error" : "command",
    title: tool.name,
    toolName: tool.name,
    preview: tool.preview,
    content: `${argsText ? `Input:\n\`\`\`json\n${argsText}\n\`\`\`` : ""}${snippet ? `\n\nOutput:\n${snippet}` : ""}`,
    duration,
    status: liveToolStatus(tool),
    isExpanded: false,
    afterTextLength: tool.afterTextLength,
  };
}

/** Reasoning trace from session row (legacy ui.js: reasoning_content || reasoning). */
export function reasoningTextFromHermesMessage(msg: HermesSessionMessage): string {
  const fromBlocks = extractReasoningFromContentBlocks(msg.content);
  if (fromBlocks) return fromBlocks;
  const rc = asString(msg.reasoning_content);
  const r = asString(msg.reasoning);
  return (rc || r).trim();
}

function extractReasoningFromContentBlocks(content: unknown): string {
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const part of content) {
    if (!isRecord(part)) continue;
    const partType = asString(part.type);
    if (partType !== "reasoning" && partType !== "thinking") continue;
    const text =
      asString(part.thinking) ||
      asString(part.reasoning) ||
      asString(part.text) ||
      asString(part.content);
    if (text.trim()) parts.push(text);
  }
  return parts.join("\n").trim();
}

function thinkingStepsFromHermesReasoning(
  msg: HermesSessionMessage,
  answerContent: string,
  index: number,
): ProcessStep[] {
  const text = reasoningTextFromHermesMessage(msg);
  if (!text || !isDistinctThinking(text, answerContent)) return [];
  const step = reasoningTextToProcessStep(text, {
    id: `reasoning-${index}`,
    status: "completed",
  });
  return step ? [step] : [];
}

/** Map accumulated live reasoning text to a thinking ProcessStep. */
export function reasoningTextToProcessStep(
  text: string,
  options?: { id?: string; status?: ProcessStep["status"] },
): ProcessStep | null {
  const content = text.trim();
  if (!content) return null;
  return {
    id: options?.id ?? "reasoning-live",
    type: "thinking",
    title: "Reasoning",
    content,
    status: options?.status ?? "running",
    isExpanded: false,
  };
}

/** Build ProcessStep[] from live SSE tool + reasoning state. */
export function buildLiveStreamProcessSteps(options: {
  reasoningText?: string;
  committedReasoning?: string[];
  tools?: HermesLiveToolCall[];
}): ProcessStep[] {
  const steps: ProcessStep[] = [];
  const combined = combinedReasoningText(
    options.committedReasoning ?? [],
    options.reasoningText ?? "",
  );
  const liveTail = (options.reasoningText ?? "").trim();
  const reasoning = reasoningTextToProcessStep(combined, {
    id: "reasoning-live",
    status: liveTail ? "running" : "completed",
  });
  if (reasoning) steps.push(reasoning);

  for (const tool of options.tools ?? []) {
    if (tool.name === "clarify") continue;
    steps.push(liveToolCallToProcessStep(tool));
  }
  return steps;
}

/** Apply an SSE `tool` event to the live tool-call list. */
export function applyStreamToolEvent(
  tools: HermesLiveToolCall[],
  payload: Record<string, unknown>,
  options?: { afterTextLength?: number },
): HermesLiveToolCall[] {
  const name = asString(payload.name, "tool");
  if (name === "clarify") return tools;

  const resultSnippet = toolResultSnippetFromPayload(payload);
  const next: HermesLiveToolCall = {
    id: asString(payload.tid, `live-${name}-${tools.length}`),
    name,
    preview: asString(payload.preview) || undefined,
    args: payload.args ?? {},
    snippet: resultSnippet || undefined,
    done: false,
    afterTextLength: options?.afterTextLength,
  };
  return [...tools, next];
}

/** Apply an SSE `tool_complete` event to the live tool-call list. */
export function applyStreamToolCompleteEvent(
  tools: HermesLiveToolCall[],
  payload: Record<string, unknown>,
  options?: { afterTextLength?: number },
): HermesLiveToolCall[] {
  const name = asString(payload.name, "tool");
  if (name === "clarify") return tools;

  const next = [...tools];
  let target: HermesLiveToolCall | null = null;
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const current = next[i];
    if (!current.done && (!name || current.name === name)) {
      target = current;
      break;
    }
  }

  const resultSnippet = toolResultSnippetFromPayload(payload, target?.snippet ?? target?.preview ?? "");

  if (!target) {
    next.push({
      id: asString(payload.tid, `live-${name}-${next.length}`),
      name,
      preview: asString(payload.preview) || undefined,
      args: payload.args ?? {},
      snippet: resultSnippet || undefined,
      done: true,
      isError: Boolean(payload.is_error),
      duration: typeof payload.duration === "number" ? payload.duration : undefined,
      afterTextLength: options?.afterTextLength,
    });
    return next;
  }

  const idx = next.indexOf(target);
  next[idx] = {
    ...target,
    preview: asString(payload.preview, target.preview ?? "") || undefined,
    args: payload.args ?? target.args,
    snippet: resultSnippet || undefined,
    done: true,
    isError: Boolean(payload.is_error),
    duration: typeof payload.duration === "number" ? payload.duration : undefined,
  };
  return next;
}

export function mapToolCallsToSteps(
  toolCalls: unknown,
  options?: { markIncompleteAsCancelled?: boolean },
): ProcessStep[] | undefined {
  if (!Array.isArray(toolCalls) || toolCalls.length === 0) return undefined;
  const steps: ProcessStep[] = [];
  for (const tc of toolCalls) {
    if (!isRecord(tc)) continue;
    const functionName = isRecord(tc.function) ? asString(tc.function.name) : "";
    const parsedContent =
      parseJsonObject(tc.content) ??
      parseJsonObject(tc.output) ??
      parseJsonObject(tc.result) ??
      parseJsonObject(tc.snippet);
    const inferredName = inferToolNameFromPayload(parsedContent);
    const rawName = asString(tc.name || tc.tool_name || functionName);
    const name = rawName || inferredName || "tool";
    if (name === "clarify") continue;
    const fallbackSnippet =
      typeof tc.content === "string"
        ? tc.content
        : parsedContent
          ? JSON.stringify(parsedContent)
          : "";
    const snippet = asString(tc.snippet || tc.output || tc.result || fallbackSnippet);
    const args = tc.args ?? tc.arguments;
    const argsText =
      typeof args === "string"
        ? args
        : args
          ? JSON.stringify(args, null, 2)
          : "";
    const preview = asString(tc.preview);
    const statusValue = asString(tc.status).toLowerCase();
    const isDone =
      tc.done === true ||
      tc.completed === true ||
      tc.is_error === true ||
      Boolean(snippet) ||
      Boolean(parsedContent) ||
      statusValue === "done" ||
      statusValue === "completed" ||
      statusValue === "success" ||
      statusValue === "failed" ||
      statusValue === "error";
    const status: ProcessStep["status"] = isDone
      ? "completed"
      : options?.markIncompleteAsCancelled
        ? "cancelled"
        : "running";
    steps.push({
      id: asString(tc.tid || tc.id, `tool-${name}-${steps.length}`),
      type: "command",
      title: name,
      toolName: name,
      preview: preview || undefined,
      content: `${argsText ? `Input:\n\`\`\`json\n${argsText}\n\`\`\`` : ""}${snippet ? `\n\nOutput:\n${snippet}` : ""}`,
      status,
      isExpanded: false,
    });
  }
  return steps.length > 0 ? steps : undefined;
}

function messageId(msg: HermesSessionMessage, index: number): string {
  const id = asString(msg.id || msg.message_id);
  return id || `hermes-msg-${index}`;
}

function toolCallName(tc: unknown): string {
  if (!isRecord(tc)) return "";
  const functionName = isRecord(tc.function) ? asString(tc.function.name) : "";
  return asString(tc.name || tc.tool_name || functionName);
}

function isClarifyToolCall(tc: unknown): boolean {
  return toolCallName(tc) === "clarify";
}

function assistantToolCalls(msg: HermesSessionMessage): unknown[] {
  const partial = msg._partial_tool_calls;
  const toolCalls = msg.tool_calls;
  if (Array.isArray(toolCalls) && toolCalls.length > 0) return toolCalls;
  if (Array.isArray(partial) && partial.length > 0) return partial;
  return [];
}

function isOnlyClarifyAssistantStub(msg: HermesSessionMessage): boolean {
  if (asString(msg.role) !== "assistant") return false;
  if (extractMessageContent(msg.content).trim()) return false;
  const calls = assistantToolCalls(msg);
  if (calls.length === 0) return false;
  return calls.every(isClarifyToolCall);
}

/** Parse clarify tool_complete SSE / snippet JSON into a transcript line. */
export function clarifyEchoContentFromStreamPayload(
  payload: Record<string, unknown>,
): string | null {
  if (asString(payload.name) !== "clarify") return null;
  const parsed =
    parseJsonObject(payload.preview) ??
    parseJsonObject(payload.snippet) ??
    parseJsonObject(payload.args);
  if (!parsed) return null;

  const answer = asString(parsed.user_response).trim();
  if (!answer) return null;

  const question = asString(parsed.question).trim();
  return formatClarifyEchoMessage(question, answer);
}

/** Build a user bubble from a completed clarify tool result row in session history. */
export function mapClarifyToolMessageToUserMessage(
  msg: HermesSessionMessage,
  index: number,
): Message | null {
  const role = asString(msg.role);
  const name = asString(msg.name || msg.tool_name);
  if (role !== "tool" || name !== "clarify") return null;

  const parsed =
    parseJsonObject(msg.content) ??
    parseJsonObject(extractMessageContent(msg.content));
  if (!parsed) return null;

  const answer = asString(parsed.user_response).trim();
  if (!answer) return null;

  const question = asString(parsed.question).trim();
  const content = formatClarifyEchoMessage(question, answer);
  const timestamp = asNumber(msg.timestamp, Date.now());

  return {
    id: messageId(msg, index),
    role: "user",
    content,
    timestamp,
    versions: [{ content, timestamp }],
    currentVersionIndex: 0,
  };
}

const EMPTY_RECOVERY_USER_PREFIX =
  "You just executed tool calls but returned an empty response.";

export const EMPTY_RECOVERY_ASSISTANT_NOTICE =
  "โมเดลยังไม่ตอบหลังเรียกเครื่องมือ — กำลังดึงให้ดำเนินการต่อ...";

export function isEmptyRecoveryUserNudge(msg: HermesSessionMessage): boolean {
  if (asString(msg.role) !== "user") return false;
  if (msg._empty_recovery_synthetic === true) return true;
  const text = extractMessageContent(msg.content).trim();
  return text.startsWith(EMPTY_RECOVERY_USER_PREFIX);
}

export function isEmptyRecoveryAssistantPlaceholder(
  msg: HermesSessionMessage,
): boolean {
  if (asString(msg.role) !== "assistant") return false;
  if (extractMessageContent(msg.content).trim() !== "(empty)") return false;
  return msg._empty_recovery_synthetic === true;
}

/** Agent steering rows stored as user turns ([System:…] / [IMPORTANT:…]). */
export function isAgentInjectedUserTurn(msg: HermesSessionMessage): boolean {
  if (isEmptyRecoveryUserNudge(msg)) return true;
  if (asString(msg.role) !== "user") return false;
  const text = extractMessageContent(msg.content).trim();
  if (!text) return false;
  return text.startsWith("[System:") || text.startsWith("[IMPORTANT:");
}

function isDisplayableHermesMessage(msg: HermesSessionMessage): boolean {
  if (isContextCompressionMarker(msg)) return false;
  const role = asString(msg.role);
  if (role === "tool" || role === "system") return false;
  if (isEmptyRecoveryAssistantPlaceholder(msg)) return false;
  if (role === "user" && isAgentInjectedUserTurn(msg)) return false;
  if (role !== "assistant") return true;
  if (isOnlyClarifyAssistantStub(msg)) return false;
  const content = extractMessageContent(msg.content).trim();
  if (content) return true;
  const calls = assistantToolCalls(msg);
  if (calls.some((tc) => !isClarifyToolCall(tc))) return true;
  return false;
}

/** Map one Hermes session message row to UI Message. */
export function mapHermesMessageToMessage(
  msg: HermesSessionMessage,
  index: number,
): Message | null {
  if (isEmptyRecoveryUserNudge(msg)) {
    const timestamp = asNumber(msg.timestamp, Date.now());
    const content = EMPTY_RECOVERY_ASSISTANT_NOTICE;
    return {
      id: messageId(msg, index),
      role: "assistant",
      content,
      timestamp,
      versions: [{ content, timestamp }],
      currentVersionIndex: 0,
    };
  }
  if (!isDisplayableHermesMessage(msg)) return null;
  const roleRaw = asString(msg.role);
  const role = roleRaw === "user" ? "user" : "assistant";
  const rawContent = extractMessageContent(msg.content);
  const content = rawContent;
  const steps =
    mapToolCallsToSteps(msg.tool_calls) ??
    mapToolCallsToSteps(msg._partial_tool_calls, {
      markIncompleteAsCancelled: Boolean(msg._partial),
    });
  const timestamp = asNumber(msg.timestamp, Date.now());
  let attachments = mergeAttachmentsWithContentMarker(
    mapAttachments(msg.attachments),
    rawContent,
  );

  return {
    id: messageId(msg, index),
    role,
    content,
    timestamp,
    attachments,
    steps,
    versions: [{ content, attachments, steps, timestamp }],
    currentVersionIndex: 0,
  };
}

function sessionToolsForAssistantIndex(
  sessionToolCalls: unknown,
  assistantMsgIdx: number,
): ProcessStep[] {
  if (!Array.isArray(sessionToolCalls)) return [];
  const raw: unknown[] = [];
  for (const tc of sessionToolCalls) {
    if (!isRecord(tc)) continue;
    const idx = tc.assistant_msg_idx;
    if (typeof idx === "number" && idx === assistantMsgIdx) raw.push(tc);
  }
  return mapToolCallsToSteps(raw) ?? [];
}

function mergeToolSteps(...groups: (ProcessStep[] | undefined)[]): ProcessStep[] {
  const out: ProcessStep[] = [];
  const seenIndex = new Map<string, number>();
  for (const group of groups) {
    for (const step of group ?? []) {
      const existingIndex = seenIndex.get(step.id);
      if (existingIndex === undefined) {
        seenIndex.set(step.id, out.length);
        out.push(step);
        continue;
      }

      const existing = out[existingIndex];
      const shouldReplace =
        (existing.status === "running" &&
          (step.status === "completed" || step.status === "cancelled")) ||
        (existing.status !== "completed" &&
          existing.status !== "cancelled" &&
          step.status === "completed") ||
        (!existing.content?.trim() && Boolean(step.content?.trim())) ||
        (!existing.preview?.trim() && Boolean(step.preview?.trim()));
      if (shouldReplace) {
        out[existingIndex] = step;
      }
    }
  }
  return out;
}

function toolStepFromContentBlock(block: Record<string, unknown>): ProcessStep | null {
  if (asString(block.type) !== "tool_use") return null;
  const steps = mapToolCallsToSteps([
    {
      id: block.id,
      name: block.name,
      arguments: block.input ?? block.args,
    },
  ]);
  return steps?.[0] ?? null;
}

/** Preserve Anthropic-style content[] order (text segments interleaved with tool_use). */
function blocksFromInterleavedContent(
  content: unknown,
  extraTools: ProcessStep[],
): MessageBlock[] | null {
  if (!Array.isArray(content)) return null;
  const blocks: MessageBlock[] = [];
  let textParts: string[] = [];
  const reasoningParts: string[] = [];
  const flushText = () => {
    const joined = textParts.join("\n").trim();
    if (joined) blocks.push({ type: "text", content: joined });
    textParts = [];
  };
  const appendTool = (step: ProcessStep) => {
    flushText();
    const last = blocks[blocks.length - 1];
    if (last?.type === "tools") {
      blocks[blocks.length - 1] = { type: "tools", steps: [...last.steps, step] };
    } else {
      blocks.push({ type: "tools", steps: [step] });
    }
  };

  let sawToolUse = false;
  for (const part of content) {
    if (!isRecord(part)) continue;
    const partType = asString(part.type);
    if (partType === "tool_use") {
      sawToolUse = true;
      const step = toolStepFromContentBlock(part);
      if (step) appendTool(step);
      continue;
    }
    if (partType === "reasoning" || partType === "thinking") {
      const trace =
        asString(part.thinking) ||
        asString(part.reasoning) ||
        asString(part.text) ||
        asString(part.content);
      if (trace.trim()) reasoningParts.push(trace);
      continue;
    }
    const text =
      typeof part.text === "string"
        ? part.text
        : typeof part.content === "string"
          ? part.content
          : "";
    if (text.trim()) textParts.push(text);
  }
  flushText();

  if (!sawToolUse) return null;

  if (reasoningParts.length > 0) {
    const step = reasoningTextToProcessStep(reasoningParts.join("\n"), {
      id: "reasoning-content-blocks",
      status: "completed",
    });
    if (step) blocks.unshift({ type: "thinking", steps: [step] });
  }

  for (const step of extraTools) {
    const inBlocks = blocks.some(
      (b) => b.type === "tools" && b.steps.some((s) => s.id === step.id),
    );
    if (!inBlocks) appendTool(step);
  }
  return blocks;
}

function combinedReasoningFromAssistantRun(
  run: { msg: HermesSessionMessage; index: number }[],
): string {
  const parts: string[] = [];
  for (const entry of run) {
    const text = reasoningTextFromHermesMessage(entry.msg);
    if (text) parts.push(text);
  }
  return parts.join("\n\n").trim();
}

function blocksForAssistantMessage(
  msg: HermesSessionMessage,
  rawIndex: number,
  sessionToolCalls?: unknown,
  options?: { skipReasoning?: boolean },
): MessageBlock[] {
  const rawContent = extractMessageContent(msg.content);
  const content = rawContent;
  const finalizedTools = mapToolCallsToSteps(msg.tool_calls);
  const partialTools = finalizedTools?.length
    ? undefined
    : mapToolCallsToSteps(msg._partial_tool_calls, {
        markIncompleteAsCancelled: Boolean(msg._partial),
      });

  const msgTools = mergeToolSteps(
    finalizedTools,
    partialTools,
    sessionToolsForAssistantIndex(sessionToolCalls, rawIndex),
  );

  const thinking = options?.skipReasoning
    ? []
    : thinkingStepsFromHermesReasoning(msg, content, rawIndex);

  const interleaved = blocksFromInterleavedContent(msg.content, msgTools);
  if (interleaved) {
    if (
      thinking.length > 0 &&
      !interleaved.some((b) => b.type === "thinking")
    ) {
      return [{ type: "thinking", steps: thinking }, ...interleaved];
    }
    return interleaved;
  }

  return buildAssistantBlocksFromTextAndTools(content, msgTools, thinking);
}

function mergeAssistantTurn(
  run: { msg: HermesSessionMessage; index: number }[],
  sessionToolCalls?: unknown,
): ReturnType<typeof mapHermesMessageToMessage> {
  if (run.length === 0) return null;
  const last = run[run.length - 1];
  const base = mapHermesMessageToMessage(last.msg, last.index);
  if (!base) return null;

  let blocks: MessageBlock[] = [];
  for (const entry of run) {
    blocks.push(
      ...blocksForAssistantMessage(entry.msg, entry.index, sessionToolCalls, {
        skipReasoning: true,
      }),
    );
  }

  const content = blocks
    .filter((b): b is Extract<MessageBlock, { type: "text" }> => b.type === "text")
    .map((b) => b.content)
    .join("\n\n")
    .trim();

  const first = run[0];
  const turnReasoning = combinedReasoningFromAssistantRun(run);
  const turnThinking =
    turnReasoning && isDistinctThinking(turnReasoning, content)
      ? reasoningTextToProcessStep(turnReasoning, {
          id: `reasoning-turn-${first.index}`,
          status: "completed",
        })
      : null;
  if (turnThinking) {
    blocks.unshift({ type: "thinking", steps: [turnThinking] });
  }

  let steps: ProcessStep[] = [];
  for (const block of blocks) {
    if (block.type === "thinking") steps.push(...block.steps);
    if (block.type === "tools") steps.push(...block.steps);
  }
  if (assistantRunHasCancelMarker(run)) {
    blocks = finalizeRunningStepsInBlocks(blocks) ?? blocks;
    steps = finalizeRunningProcessSteps(steps) ?? steps;
  }
  const rawFirst = extractMessageContent(first.msg.content);
  const attachments = mergeAttachmentsWithContentMarker(
    mapAttachments(first.msg.attachments),
    rawFirst,
  );

  return {
    ...base,
    id: messageId(first.msg, first.index),
    content: content || base.content,
    steps: steps.length > 0 ? steps : base.steps,
    blocks,
    attachments,
    versions: [
      {
        content: content || base.content,
        attachments,
        steps: steps.length > 0 ? steps : base.steps,
        blocks,
        timestamp: base.timestamp,
      },
    ],
  };
}

/** Map Hermes session messages (+ optional session-level tool_calls) to Message[]. */
export function mapHermesMessagesToMessages(
  messages: HermesSessionMessage[] | undefined,
  sessionToolCalls?: unknown,
): Message[] {
  const list = Array.isArray(messages) ? messages : [];
  const mapped: Message[] = [];
  let i = 0;

  while (i < list.length) {
    const msg = list[i];
    const role = asString(msg.role);

    if (role === "user") {
      const row = mapHermesMessageToMessage(msg, i);
      if (row) mapped.push(row);
      i += 1;
      continue;
    }

    if (role === "tool") {
      const clarifyUser = mapClarifyToolMessageToUserMessage(msg, i);
      if (clarifyUser) mapped.push(clarifyUser);
      i += 1;
      continue;
    }

    if (role === "system") {
      i += 1;
      continue;
    }

    if (role !== "assistant" || !isDisplayableHermesMessage(msg)) {
      i += 1;
      continue;
    }

    const run: { msg: HermesSessionMessage; index: number }[] = [];
    while (i < list.length) {
      const candidate = list[i];
      const candidateRole = asString(candidate.role);

      if (candidateRole === "tool") {
        const clarifyUser = mapClarifyToolMessageToUserMessage(candidate, i);
        if (clarifyUser) {
          if (run.length > 0) {
            const merged = mergeAssistantTurn(run, sessionToolCalls);
            if (merged) mapped.push(merged);
            run.length = 0;
          }
          mapped.push(clarifyUser);
        }
        i += 1;
        continue;
      }

      if (candidateRole === "user") break;

      if (!isDisplayableHermesMessage(candidate)) {
        i += 1;
        continue;
      }

      if (candidateRole !== "assistant") break;

      run.push({ msg: candidate, index: i });
      i += 1;
    }

    if (run.length > 0) {
      const merged = mergeAssistantTurn(run, sessionToolCalls);
      if (merged) mapped.push(merged);
    }
  }

  return mapped;
}

function sessionUpdatedAt(summary: HermesSessionSummary): number {
  return asNumber(
    summary.last_message_at ?? summary.updated_at ?? summary.created_at,
    Date.now(),
  );
}

function summaryMessageCount(summary: HermesSessionSummary): number | undefined {
  if (typeof summary.message_count === "number" && summary.message_count >= 0) {
    return summary.message_count;
  }
  return undefined;
}

/** Whether a sidebar row should appear before full message history is loaded. */
export function shouldShowChatSessionInSidebar(
  session: ChatSession,
  activeChatId?: string | null,
): boolean {
  if ((session.messages?.length ?? 0) > 0) return true;
  if ((session.messageCount ?? 0) > 0) return true;
  if (activeChatId && session.id === activeChatId) return true;
  return false;
}

function readSummaryActiveStreamId(summary: HermesSessionSummary): string | undefined {
  const raw = summary.active_stream_id;
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

/** Match server live-stream semantics: both is_streaming and active_stream_id required. */
function streamFlagsFromSummary(
  summary: HermesSessionSummary,
): Pick<ChatSession, "activeStreamId" | "isStreaming"> {
  const activeStreamId = readSummaryActiveStreamId(summary);
  if (summary.is_streaming === true && activeStreamId) {
    return { activeStreamId, isStreaming: true };
  }
  return { activeStreamId: undefined, isStreaming: false };
}

/** Sidebar stub: metadata only, empty messages (full history loaded on select). */
export function mapSessionSummaryToChatSession(summary: HermesSessionSummary): ChatSession {
  const model = asString(summary.model);
  const matchPreview =
    typeof summary.match_preview === "string" ? summary.match_preview : undefined;
  const messageCount = summaryMessageCount(summary);
  const streamFlags = streamFlagsFromSummary(summary);
  return {
    id: summary.session_id,
    title: summary.title || "Untitled",
    messages: [],
    updatedAt: sessionUpdatedAt(summary),
    ...(messageCount !== undefined ? { messageCount } : {}),
    ...(summary.pinned ? { pinned: true } : {}),
    ...(matchPreview ? { matchPreview } : {}),
    ...(model ? { flowId: model, flowName: model } : {}),
    ...(summary.project_id ? { projectId: summary.project_id } : {}),
    ...streamFlags,
  };
}

export function mapSessionSummariesToChatSessions(
  summaries: HermesSessionSummary[],
): ChatSession[] {
  return summaries
    .map((s) => mapSessionSummaryToChatSession(s))
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Full session detail including message history. */
export function mapSessionDetailToChatSession(detail: HermesSessionDetail): ChatSession {
  const model = asString(detail.model);
  const messages = mapHermesMessagesToMessages(detail.messages, detail.tool_calls);
  const fromServer = summaryMessageCount(detail);
  const messageCount = fromServer ?? messages.length;
  const streamFlags = streamFlagsFromSummary(detail);
  const contextUsage = contextUsageFromHermesSession(detail);
  const compressionAnchor = compressionAnchorFromHermesDetail(detail);
  return {
    id: detail.session_id,
    title: detail.title || "Untitled",
    messages,
    updatedAt: sessionUpdatedAt(detail),
    messageCount,
    ...(model ? { flowId: model, flowName: model } : {}),
    ...(detail.project_id ? { projectId: detail.project_id } : {}),
    ...(contextUsage ? { contextUsage } : {}),
    ...(compressionAnchor ? { compressionAnchor } : {}),
    ...streamFlags,
  };
}
