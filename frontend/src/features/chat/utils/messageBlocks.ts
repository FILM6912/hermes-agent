import type { Message, MessageBlock, ProcessStep } from "@/types";
import {
  thinkingStepsOnly,
  toolStepsOnly,
} from "./activityTimeline";
import { isDistinctThinking } from "./thinkingDisplay";

export function deriveContentFromBlocks(blocks: MessageBlock[]): string {
  return blocks
    .filter((b): b is Extract<MessageBlock, { type: "text" }> => b.type === "text")
    .map((b) => b.content)
    .join("\n\n")
    .trim();
}

export function deriveStepsFromBlocks(
  blocks: MessageBlock[],
): ProcessStep[] | undefined {
  const steps: ProcessStep[] = [];
  for (const block of blocks) {
    if (block.type === "thinking" || block.type === "tools") {
      steps.push(...block.steps);
    }
  }
  return steps.length > 0 ? steps : undefined;
}

/** Text before tools; split on first blank line when tools exist (intro → tools → summary). */
export function buildAssistantBlocksFromTextAndTools(
  content: string,
  tools: ProcessStep[],
  thinking?: ProcessStep[],
): MessageBlock[] {
  const blocks: MessageBlock[] = [];
  if (thinking && thinking.length > 0) {
    blocks.push({ type: "thinking", steps: thinking });
  }
  const trimmed = content.trim();
  if (tools.length === 0) {
    if (trimmed) blocks.push({ type: "text", content: trimmed });
    return blocks;
  }
  if (!trimmed) {
    blocks.push({ type: "tools", steps: tools });
    return blocks;
  }
  const splitIdx = trimmed.indexOf("\n\n");
  if (splitIdx === -1) {
    blocks.push({ type: "text", content: trimmed });
    blocks.push({ type: "tools", steps: tools });
    return blocks;
  }
  const before = trimmed.slice(0, splitIdx).trim();
  const after = trimmed.slice(splitIdx + 2).trim();
  if (before) blocks.push({ type: "text", content: before });
  blocks.push({ type: "tools", steps: tools });
  if (after) blocks.push({ type: "text", content: after });
  return blocks;
}

/** Fallback when only legacy content + steps are stored. */
export function messageBlocksFromLegacy(
  content: string,
  steps?: ProcessStep[],
): MessageBlock[] {
  const thinking = thinkingStepsOnly(steps ?? []);
  const tools = toolStepsOnly(steps ?? []);
  return buildAssistantBlocksFromTextAndTools(content, tools, thinking);
}

/** Merge back-to-back tool blocks into one list (legacy session interleaving). */
export function mergeConsecutiveToolBlocks(
  blocks: MessageBlock[],
): MessageBlock[] {
  const out: MessageBlock[] = [];
  for (const block of blocks) {
    if (block.type !== "tools" || block.steps.length === 0) {
      out.push(block);
      continue;
    }
    const last = out[out.length - 1];
    if (last?.type === "tools") {
      out[out.length - 1] = {
        type: "tools",
        steps: [...last.steps, ...block.steps],
      };
    } else {
      out.push({ type: "tools", steps: [...block.steps] });
    }
  }
  return out;
}

/** Preserve interleaved block order; merge tools and drop duplicate adjacent text. */
export function normalizeAssistantTurnBlocks(
  blocks: MessageBlock[],
): MessageBlock[] {
  const merged = mergeConsecutiveToolBlocks(blocks);
  const out: MessageBlock[] = [];
  for (const block of merged) {
    if (block.type === "text" && block.content.trim()) {
      const trimmed = block.content.trim();
      const last = out[out.length - 1];
      if (
        last?.type === "text" &&
        last.content.trim() === trimmed
      ) {
        continue;
      }
      out.push({ type: "text", content: block.content });
      continue;
    }
    out.push(block);
  }
  return out;
}

function groupToolsByTextAnchor(
  tools: ProcessStep[],
): Array<{ afterTextLength: number; steps: ProcessStep[] }> {
  const groups = new Map<number, ProcessStep[]>();
  for (const tool of tools) {
    const anchor =
      typeof tool.afterTextLength === "number" ? tool.afterTextLength : -1;
    const bucket = groups.get(anchor) ?? [];
    bucket.push(tool);
    groups.set(anchor, bucket);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left - right)
    .map(([afterTextLength, groupedSteps]) => ({
      afterTextLength,
      steps: groupedSteps,
    }));
}

/** Interleave streamed text and tools using live SSE anchors (history uses content[]). */
function buildInterleavedStreamBlocks(
  content: string,
  tools: ProcessStep[],
): MessageBlock[] {
  const groups = groupToolsByTextAnchor(tools).filter(
    (group) => group.afterTextLength >= 0,
  );
  const blocks: MessageBlock[] = [];
  let cursor = 0;

  for (const group of groups) {
    let anchor = group.afterTextLength;

    if (anchor === 0 && cursor === 0 && content.trim()) {
      const splitIdx = content.indexOf("\n\n");
      if (splitIdx !== -1) {
        const intro = content.slice(0, splitIdx);
        if (intro.trim()) blocks.push({ type: "text", content: intro });
        blocks.push({ type: "tools", steps: group.steps });
        cursor = splitIdx + 2;
        continue;
      }
      // Intro still streaming as one paragraph — keep text before tools for now.
      blocks.push({ type: "text", content });
      blocks.push({ type: "tools", steps: group.steps });
      return blocks;
    }

    const segment = content.slice(cursor, anchor);
    if (segment.trim()) blocks.push({ type: "text", content: segment });
    blocks.push({ type: "tools", steps: group.steps });
    cursor = Math.max(cursor, anchor);
  }

  const tail = content.slice(cursor);
  if (tail.trim()) blocks.push({ type: "text", content: tail });
  return blocks;
}

/** Build assistant blocks during SSE (intro → tools → follow-up text). */
export function buildBlocksForStreamingAssistant(
  content: string,
  steps?: ProcessStep[],
): MessageBlock[] {
  const answerText = content.trim();
  const thinking = thinkingStepsOnly(steps ?? []).filter((step) =>
    isDistinctThinking(step.content, answerText),
  );
  const tools = toolStepsOnly(steps ?? []);
  const blocks: MessageBlock[] = [];
  if (thinking.length > 0) {
    blocks.push({ type: "thinking", steps: thinking });
  }

  const hasAnchoredTools = tools.some(
    (step) => typeof step.afterTextLength === "number",
  );

  if (tools.length > 0 && hasAnchoredTools) {
    if (!answerText) {
      blocks.push({ type: "tools", steps: tools });
      return blocks;
    }
    blocks.push(...buildInterleavedStreamBlocks(content, tools));
    return blocks;
  }

  if (tools.length > 0 && !answerText) {
    blocks.push({ type: "tools", steps: tools });
    return blocks;
  }

  if (tools.length > 0) {
    blocks.push(
      ...buildAssistantBlocksFromTextAndTools(content, tools, []).filter(
        (block) => block.type !== "thinking",
      ),
    );
    return blocks;
  }

  if (content.trim()) {
    blocks.push({ type: "text", content });
  }
  return blocks;
}

export function resolveMessageBlocks(msg: Message): MessageBlock[] {
  const raw =
    msg.blocks && msg.blocks.length > 0
      ? msg.blocks
      : messageBlocksFromLegacy(msg.content, msg.steps);
  const merged = mergeConsecutiveToolBlocks(raw);
  const normalized =
    msg.role === "assistant"
      ? normalizeAssistantTurnBlocks(merged)
      : merged;

  const allSteps = msg.steps ?? deriveStepsFromBlocks(normalized) ?? [];
  const toolsFromSteps = toolStepsOnly(allSteps);
  if (toolsFromSteps.length === 0) return normalized;

  const toolIdsInBlocks = new Set<string>();
  for (const block of normalized) {
    if (block.type !== "tools") continue;
    for (const step of block.steps) toolIdsInBlocks.add(step.id);
  }
  const missingTools = toolsFromSteps.filter((step) => !toolIdsInBlocks.has(step.id));
  if (missingTools.length === 0) return normalized;

  return mergeConsecutiveToolBlocks([
    ...normalized,
    { type: "tools", steps: missingTools },
  ]);
}

export function applyTextChunkToBlocks(
  blocks: MessageBlock[],
  accumulatedText: string,
): MessageBlock[] {
  const text = accumulatedText.trim();
  if (!text) return blocks;
  const next = [...blocks];
  const last = next[next.length - 1];
  if (last?.type === "text") {
    next[next.length - 1] = { type: "text", content: accumulatedText };
  } else {
    next.push({ type: "text", content: accumulatedText });
  }
  return next;
}

export function applyStreamChunkToMessage(
  msg: Message,
  chunk: { type: "text" | "steps"; steps?: ProcessStep[] },
  accumulatedContent: string,
): Message {
  const steps =
    chunk.type === "steps"
      ? chunk.steps
      : msg.steps ?? deriveStepsFromBlocks(msg.blocks ?? []);
  const blocks = buildBlocksForStreamingAssistant(accumulatedContent, steps);
  const content = accumulatedContent.trim()
    ? accumulatedContent
    : deriveContentFromBlocks(blocks) || msg.content;

  return { ...msg, blocks, content, steps };
}

export function withVersionBlocks<T extends { content: string; steps?: ProcessStep[]; blocks?: MessageBlock[] }>(
  version: T,
): T {
  if (version.blocks?.length) return version;
  return {
    ...version,
    blocks: messageBlocksFromLegacy(version.content, version.steps),
  };
}
