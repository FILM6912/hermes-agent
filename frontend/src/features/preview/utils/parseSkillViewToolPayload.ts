import type { ProcessStep } from "@/types";
import { parseStepInputOutput, tryParseJsonValue } from "@/features/preview/utils/toolStepContent";

export type SkillViewInput = {
  name: string;
};

export type SkillViewOutput = {
  success: boolean;
  name: string;
  description?: string;
  tags: string[];
  relatedSkills: string[];
  content?: string;
  error?: string;
};

export function normalizeToolKey(toolName: string): string {
  return toolName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

export function isSkillViewToolName(toolName: string | undefined): boolean {
  if (!toolName?.trim()) return false;
  const key = normalizeToolKey(toolName);
  return key === "skill_view" || key === "skills_view" || key === "read_skill";
}

/** Tools whose JSON payloads must never be routed to the skill viewer. */
const NON_SKILL_META_TOOLS = new Set([
  "session_search",
  "search_files",
  "web_search",
  "web_extract",
  "grep",
  "glob",
  "terminal",
  "execute_code",
  "todos",
  "todo",
  "todo_write",
  "todowrite",
]);

export function isNonSkillMetaToolName(toolName: string | undefined): boolean {
  if (!toolName?.trim()) return false;
  return NON_SKILL_META_TOOLS.has(normalizeToolKey(toolName));
}

/** True when parsed JSON looks like a skill_view tool result, not a todo payload. */
export function isSkillViewToolResult(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const rec = value as Record<string, unknown>;
  if (typeof rec.name !== "string" || !rec.name.trim()) return false;
  if (Array.isArray(rec.tags)) return true;
  if ("related_skills" in rec || "relatedSkills" in rec) return true;
  if (typeof rec.description === "string") return true;
  if (typeof rec.content === "string") return true;
  if (rec.success === false && typeof rec.error === "string") return true;
  return false;
}

function rawLooksLikeSkillViewPayload(raw: string): boolean {
  return (
    /"tags"\s*:/.test(raw) ||
    /"related_skills"\s*:/.test(raw) ||
    /"relatedSkills"\s*:/.test(raw) ||
    /"description"\s*:/.test(raw) ||
    /"content"\s*:/.test(raw)
  );
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function parseJsonStringLiteral(value: string): string {
  try {
    return JSON.parse(`"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`);
  } catch {
    return value.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
}

export function parseSkillViewInput(raw: string): SkillViewInput | null {
  const parsed = tryParseJsonValue(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const name = (parsed as Record<string, unknown>).name;
  if (typeof name !== "string" || !name.trim()) return null;
  return { name: name.trim() };
}

function buildSkillViewOutput(record: Record<string, unknown>): SkillViewOutput | null {
  if (typeof record.name !== "string" || !record.name.trim()) return null;

  const success = record.success === true;
  const description =
    typeof record.description === "string" ? record.description.trim() : undefined;
  const content = typeof record.content === "string" ? record.content : undefined;
  const error = typeof record.error === "string" ? record.error.trim() : undefined;
  const tags = readStringList(record.tags);
  const relatedSkills = readStringList(record.related_skills ?? record.relatedSkills);

  if (!success && !description && !content && !error) return null;

  return {
    success,
    name: record.name.trim(),
    description: description || undefined,
    tags,
    relatedSkills,
    content: content || undefined,
    error: error || undefined,
  };
}

/** Best-effort parse when SSE truncated the JSON payload mid-string. */
function parseSkillViewOutputLenient(raw: string): SkillViewOutput | null {
  const nameMatch = raw.match(/"name"\s*:\s*"((?:\\.|[^"\\])*)"/);
  if (!nameMatch) return null;

  const descriptionMatch = raw.match(/"description"\s*:\s*"((?:\\.|[^"\\])*)"/);
  const success = /"success"\s*:\s*true/.test(raw);
  const errorMatch = raw.match(/"error"\s*:\s*"((?:\\.|[^"\\])*)"/);

  return {
    success,
    name: parseJsonStringLiteral(nameMatch[1]),
    description: descriptionMatch
      ? parseJsonStringLiteral(descriptionMatch[1])
      : undefined,
    tags: [],
    relatedSkills: [],
    error: errorMatch ? parseJsonStringLiteral(errorMatch[1]) : undefined,
  };
}

export function parseSkillViewOutput(
  raw: string,
  options?: { allowLenient?: boolean },
): SkillViewOutput | null {
  if (!raw.trim()) return null;

  const parsed = tryParseJsonValue(raw);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    if (!isSkillViewToolResult(parsed)) return null;
    return buildSkillViewOutput(parsed as Record<string, unknown>);
  }

  if (options?.allowLenient && rawLooksLikeSkillViewPayload(raw)) {
    return parseSkillViewOutputLenient(raw);
  }

  return null;
}

export function parseSkillViewFromStep(step: ProcessStep): {
  input: SkillViewInput | null;
  output: SkillViewOutput | null;
} {
  const toolName = step.toolName ?? step.title ?? "";
  if (isNonSkillMetaToolName(toolName)) {
    return { input: null, output: null };
  }

  const allowLenient = isSkillViewToolName(toolName);
  const { inputContent, outputContent } = parseStepInputOutput(step.content);
  const input = parseSkillViewInput(inputContent);

  const candidates = [outputContent, step.preview ?? ""].filter((value) => value.trim());
  let output: SkillViewOutput | null = null;
  for (const raw of candidates) {
    output = parseSkillViewOutput(raw, { allowLenient });
    if (output?.content || output?.description) break;
  }

  return { input, output };
}

export function stepUsesSkillViewPanel(step: {
  toolName?: string;
  title?: string;
  content: string;
  preview?: string;
}): boolean {
  const toolName = step.toolName ?? step.title ?? "";
  if (isNonSkillMetaToolName(toolName)) return false;
  if (isSkillViewToolName(toolName)) return true;
  const { input, output } = parseSkillViewFromStep(step as ProcessStep);
  return input !== null || output !== null;
}

export function skillViewNeedsContentFetch(
  input: SkillViewInput | null,
  output: SkillViewOutput | null,
): boolean {
  const name = output?.name ?? input?.name;
  if (!name) return false;
  if (output?.error) return false;
  return !output?.content?.trim();
}
