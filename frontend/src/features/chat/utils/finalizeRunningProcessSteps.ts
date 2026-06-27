import type { Message, MessageBlock, ProcessStep } from "@/types";

/** Mark in-flight tool/thinking steps as cancelled (not running). */
export function finalizeRunningProcessSteps(
  steps: ProcessStep[] | undefined,
): ProcessStep[] | undefined {
  if (!steps?.length) return steps;
  let changed = false;
  const next = steps.map((step) => {
    if (step.status !== "running") return step;
    changed = true;
    return { ...step, status: "cancelled" as const };
  });
  return changed ? next : steps;
}

export function finalizeRunningStepsInBlocks(
  blocks: MessageBlock[] | undefined,
): MessageBlock[] | undefined {
  if (!blocks?.length) return blocks;
  let changed = false;
  const next = blocks.map((block) => {
    if (block.type !== "tools" && block.type !== "thinking") return block;
    const steps = finalizeRunningProcessSteps(block.steps);
    if (steps === block.steps) return block;
    changed = true;
    return { ...block, steps: steps ?? block.steps };
  });
  return changed ? next : blocks;
}

/** Clear running tool/thinking UI on the active assistant bubble after stop/cancel. */
export function finalizeRunningStepsInMessage(message: Message): Message {
  const steps = finalizeRunningProcessSteps(message.steps);
  const blocks = finalizeRunningStepsInBlocks(message.blocks);
  const versions = message.versions?.map((version) => {
    const versionSteps = finalizeRunningProcessSteps(version.steps);
    const versionBlocks = finalizeRunningStepsInBlocks(version.blocks);
    if (versionSteps === version.steps && versionBlocks === version.blocks) {
      return version;
    }
    return {
      ...version,
      ...(versionSteps !== version.steps ? { steps: versionSteps } : {}),
      ...(versionBlocks !== version.blocks ? { blocks: versionBlocks } : {}),
    };
  });

  if (
    steps === message.steps &&
    blocks === message.blocks &&
    versions === message.versions
  ) {
    return message;
  }

  return {
    ...message,
    ...(steps !== message.steps ? { steps } : {}),
    ...(blocks !== message.blocks ? { blocks } : {}),
    ...(versions !== message.versions ? { versions } : {}),
  };
}
