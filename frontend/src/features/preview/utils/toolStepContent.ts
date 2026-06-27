import type { ProcessStep } from "@/types";
import { displayVirtualPathsInText } from "@/services/hermes/displayVirtualPaths";

/** Strip optional ```json ... ``` fences from tool output / input text */
export function stripJsonFences(raw: string): string {
  let t = raw.trim();
  const fenced = t.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$/i);
  if (fenced) return fenced[1].trim();
  return t;
}

export function tryParseJsonValue(raw: string): unknown | null {
  const t = stripJsonFences(raw);
  if (!t || (!t.startsWith("{") && !t.startsWith("["))) return null;
  try {
    return JSON.parse(t);
  } catch {
    return null;
  }
}

export function formatToolStepContent(input: string, output?: string): string {
  const inText = input.trim();
  const outText = output?.trim() ?? "";
  const parts: string[] = [];
  if (inText) parts.push(`Input:\n\`\`\`json\n${inText}\n\`\`\``);
  if (outText) parts.push(`Output:\n${outText}`);
  return parts.join("\n\n");
}

export function parseStepInputOutput(content: string): {
  inputContent: string;
  outputContent: string;
} {
  const lines = content.split("\n");
  const inputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "input:");
  const outputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "output:");

  let inputContent = "";
  let outputContent = "";

  if (inputIndex !== -1) {
    const inputEnd = outputIndex !== -1 ? outputIndex : lines.length;
    inputContent = lines
      .slice(inputIndex + 1, inputEnd)
      .join("\n")
      .trim()
      .replace(/```json\n?/gi, "")
      .replace(/```\n?/g, "")
      .trim();
  }

  if (outputIndex !== -1) {
    outputContent = lines.slice(outputIndex + 1).join("\n").trim();
  }

  if (inputIndex === -1 && outputIndex === -1) {
    outputContent = content.trim();
  }

  return { inputContent, outputContent };
}

export function stepHasOutput(step: ProcessStep): boolean {
  const { outputContent } = parseStepInputOutput(step.content);
  return Boolean(outputContent.trim());
}

const COMMAND_ARG_KEYS = ["command", "cmd", "script", "code", "input", "shell"] as const;

function normalizeToolKey(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

function truncateCommandLine(text: string, max = 120): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  if (!oneLine) return oneLine;
  return oneLine.length > max ? `${oneLine.slice(0, max - 1)}…` : oneLine;
}

function isCommandLikeTool(toolName: string | undefined): boolean {
  const key = normalizeToolKey(toolName || "");
  return (
    key.includes("terminal") ||
    key.includes("shell") ||
    key.includes("execute") ||
    key.includes("bash") ||
    key === "run" ||
    key.includes("command")
  );
}

function commandFromParsedInput(parsed: unknown): string | undefined {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return undefined;
  const record = parsed as Record<string, unknown>;
  for (const key of COMMAND_ARG_KEYS) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return truncateCommandLine(value.trim());
    }
  }
  return undefined;
}

function withVirtualCommandDisplay(text: string | undefined): string | undefined {
  if (!text) return undefined;
  const mapped = displayVirtualPathsInText(text);
  return mapped.trim() ? mapped : undefined;
}

/** Short command/script line for terminal and execute_code timeline rows. */
export function commandPreviewFromStep(step: ProcessStep): string | undefined {
  if (!isCommandLikeTool(step.toolName || step.title)) return undefined;

  const { inputContent } = parseStepInputOutput(step.content);
  if (inputContent) {
    const fromJson = withVirtualCommandDisplay(
      commandFromParsedInput(tryParseJsonValue(inputContent)),
    );
    if (fromJson) return fromJson;
    if (!inputContent.startsWith("{") && !inputContent.startsWith("[")) {
      const firstLine = inputContent.split("\n").map((line) => line.trim()).find(Boolean);
      if (firstLine) {
        return withVirtualCommandDisplay(truncateCommandLine(firstLine));
      }
    }
  }

  const preview = step.preview?.trim();
  if (preview) {
    const firstLine = preview.split("\n").map((line) => line.trim()).find(Boolean);
    if (firstLine && preview.split("\n").length <= 2 && firstLine.length <= 160) {
      return withVirtualCommandDisplay(truncateCommandLine(firstLine));
    }
  }

  return undefined;
}

export const TOOL_OUTPUT_COLLAPSE_CHARS = 12_000;
