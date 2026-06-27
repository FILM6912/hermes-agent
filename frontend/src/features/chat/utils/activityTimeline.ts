import type { ProcessStep } from "@/types";
import { commandPreviewFromStep, tryParseJsonValue } from "@/features/preview/utils/toolStepContent";

export type ActivityRow =
  | {
      kind: "tool";
      id: string;
      toolName: string;
      label: string;
      detail?: string;
      fileName?: string;
      status: ProcessStep["status"];
      expandable?: boolean;
      expandContent?: string;
    }
  | {
      kind: "thinking";
      id: string;
      label: string;
      detail?: string;
      status: ProcessStep["status"];
      expandable?: boolean;
      expandContent?: string;
    }
  | { kind: "done"; id: string };

const TOOL_SUMMARY_VERBS: Record<string, string> = {
  write_file: "created a file",
  create_file: "created a file",
  read_file: "read a file",
  view_file: "read a file",
  search_files: "searched files",
  session_search: "searched sessions",
  grep: "searched files",
  glob: "searched files",
  terminal: "ran a command",
  execute_code: "ran code",
  web_search: "searched the web",
  web_extract: "fetched a page",
  patch: "updated a file",
  apply_patch: "updated a file",
  memory: "used memory",
  skill_manage: "managed skills",
  skill_view: "read a skill",
  skills_view: "read a skill",
  read_skill: "read a skill",
  present_files: "presented a file",
  present_file: "presented a file",
  delegate_task: "delegated a task",
  subagent_progress: "ran a subagent",
  todos: "updated tasks",
  todo: "updated tasks",
  todowrite: "updated tasks",
  todo_write: "updated tasks",
};

function normalizeToolKey(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

function titleCasePhrase(text: string): string {
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Short verb for group summary, e.g. "created a file". */
export function toolSummaryVerb(toolName: string): string {
  const key = normalizeToolKey(toolName);
  if (TOOL_SUMMARY_VERBS[key]) return TOOL_SUMMARY_VERBS[key];
  if (key.includes("skill") && !key.includes("manage")) return "read a skill";
  if (key.includes("write") || key.includes("create")) return "created a file";
  if (key.includes("read") || key.includes("view") || key.includes("open"))
    return "read a file";
  if (key.includes("search") || key.includes("grep") || key.includes("find"))
    return "searched";
  if (key.includes("present") || key.includes("deliver")) return "presented a file";
  if (key.includes("terminal") || key.includes("shell") || key.includes("bash"))
    return "ran a command";
  return key.replace(/_/g, " ") || "used a tool";
}

/** Row label while running, complete, or cancelled. */
export function toolActivityLabel(
  toolName: string,
  status: ProcessStep["status"],
): string {
  const verb = toolSummaryVerb(toolName);
  if (status === "cancelled") {
    if (verb.includes("command") || verb.includes("ran")) return "Command stopped";
    if (verb.includes("file") && verb.startsWith("created")) return "File creation stopped";
    if (verb.includes("read")) return "Read stopped";
    return "Stopped";
  }
  const done = status === "completed";
  if (verb === "read a skill" || (verb.includes("skill") && verb.includes("read"))) {
    if (done) return "Read skill";
    return "Reading skill…";
  }
  if (done) {
    if (verb.startsWith("created")) return "Created a file";
    if (verb.startsWith("read")) return "Read a file";
    if (verb.startsWith("presented")) return "Presented file";
    if (verb.startsWith("ran")) return "Ran command";
    if (verb.startsWith("searched")) return "Searched";
    return titleCasePhrase(verb);
  }
  if (verb.includes("file") && verb.startsWith("created")) return "Creating file…";
  if (verb === "read a skill" || (verb.includes("skill") && verb.includes("read")))
    return "Reading skill…";
  if (verb.includes("read")) return "Reading file…";
  if (verb.includes("present")) return "Presenting file…";
  if (verb.includes("command") || verb.includes("ran")) return "Running command…";
  return "Working…";
}

export type ActivityIconKind = "file" | "present" | "command" | "search" | "generic";

export function activityIconKind(toolName: string): ActivityIconKind {
  const key = normalizeToolKey(toolName);
  if (key.includes("present")) return "present";
  if (key.includes("terminal") || key.includes("shell") || key.includes("execute"))
    return "command";
  if (key.includes("search") || key.includes("grep") || key.includes("glob"))
    return "search";
  if (
    key.includes("write") ||
    key.includes("create") ||
    key.includes("read") ||
    key.includes("view") ||
    key.includes("patch")
  ) {
    return "file";
  }
  return "generic";
}

export function fileExtension(fileName?: string): string | undefined {
  if (!fileName) return undefined;
  const ext = fileName.split(".").pop()?.trim().toLowerCase();
  if (!ext || ext === fileName.toLowerCase()) return undefined;
  return ext.slice(0, 6);
}

function isPathLike(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (/^[@./\\]/.test(t)) return true;
  if (t.includes("/") || t.includes("\\")) return true;
  if (/^[a-z0-9._-]+\.[a-z0-9]{1,8}$/i.test(t)) return true;
  return false;
}

/** Primary title for a timeline row — prefer descriptive preview over generic verb. */
export function activityStepTitle(row: Extract<ActivityRow, { kind: "tool" }>): string {
  const detail = row.detail?.trim();
  const fileName = row.fileName?.trim();
  if (detail) {
    if (fileName && detail === fileName) return row.label;
    if (!isPathLike(detail)) return detail;
    if (fileName && detail.endsWith(fileName)) {
      const prefix = detail.slice(0, -fileName.length).replace(/[/\\]+$/, "").trim();
      if (prefix && !isPathLike(prefix)) return prefix;
    }
  }
  return row.label;
}

function extractPathToken(step: ProcessStep): string | undefined {
  const patterns = [
    /"path"\s*:\s*"([^"]+)"/,
    /"file(?:_path)?"\s*:\s*"([^"]+)"/,
    /"skill_dir"\s*:\s*"([^"]+)"/,
  ];
  for (const pattern of patterns) {
    const match = step.content.match(pattern);
    if (match?.[1]) return match[1];
  }
  return undefined;
}

function isSkillPathToken(token: string | undefined): boolean {
  if (!token) return false;
  const normalized = token.replace(/\\/g, "/").toLowerCase();
  return (
    normalized.includes("/skills/") ||
    normalized.endsWith("/skills") ||
    normalized.endsWith("skill.md") ||
    normalized.includes("/skill.md")
  );
}

function isSkillViewPayload(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (record.success !== true) return false;
  return typeof record.name === "string" && typeof record.description === "string";
}

/** True when a tool step loaded skill instructions (skill_view or SKILL.md read). */
export function stepReadsSkill(step: ProcessStep): boolean {
  const toolName = step.toolName || step.title || "";
  const key = normalizeToolKey(toolName);
  if (key.includes("skill") && !key.includes("manage")) return true;

  const pathToken = extractPathToken(step);
  if (isSkillPathToken(pathToken)) return true;

  const preview = step.preview?.trim();
  if (preview && isSkillViewPayload(tryParseJsonValue(preview))) return true;

  const { inputContent, outputContent } = parseStepIo(step.content);
  for (const chunk of [inputContent, outputContent, step.content]) {
    if (!chunk.trim()) continue;
    if (isSkillViewPayload(tryParseJsonValue(chunk))) return true;
    if (isSkillPathToken(chunk)) return true;
  }
  return false;
}

function parseStepIo(content: string): { inputContent: string; outputContent: string } {
  const lines = content.split("\n");
  const inputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "input:");
  const outputIndex = lines.findIndex((line) => line.trim().toLowerCase() === "output:");
  let inputContent = "";
  let outputContent = "";
  if (inputIndex !== -1) {
    const inputEnd = outputIndex !== -1 ? outputIndex : lines.length;
    inputContent = lines.slice(inputIndex + 1, inputEnd).join("\n").trim();
  }
  if (outputIndex !== -1) {
    outputContent = lines.slice(outputIndex + 1).join("\n").trim();
  }
  return { inputContent, outputContent };
}

function extractFileName(step: ProcessStep): string | undefined {
  const preview = step.preview?.trim();
  if (preview) {
    const base = preview.split(/[/\\]/).pop();
    if (base && base.includes(".")) return base;
  }
  const fromContent = step.content.match(/"path"\s*:\s*"([^"]+)"/);
  if (fromContent?.[1]) {
    const base = fromContent[1].split(/[/\\]/).pop();
    if (base) return base;
  }
  const fromContent2 = step.content.match(/"file(?:_path)?"\s*:\s*"([^"]+)"/);
  if (fromContent2?.[1]) {
    const base = fromContent2[1].split(/[/\\]/).pop();
    if (base) return base;
  }
  return undefined;
}

function detailLine(step: ProcessStep): string | undefined {
  const command = commandPreviewFromStep(step);
  if (command) return command;

  const preview = step.preview?.trim();
  if (preview && !preview.includes("/") && preview.length < 80) return preview;
  if (preview && preview.length <= 120) {
    const parts = preview.split(/[/\\]/);
    if (parts.length > 1) return parts[parts.length - 2]
      ? `${parts[parts.length - 2]}/${parts[parts.length - 1]}`
      : preview;
  }
  if (preview) return preview.length > 120 ? `${preview.slice(0, 117)}…` : preview;
  return undefined;
}

function expandContent(step: ProcessStep): string | undefined {
  const raw = step.content.trim();
  if (!raw || raw.length < 40) return undefined;
  return raw;
}

function thinkingPreviewLine(content: string): string | undefined {
  const line = content.replace(/\s+/g, " ").trim();
  if (!line) return undefined;
  return line;
}

export function buildActivitySummary(steps: ProcessStep[]): string {
  const tools = toolStepsOnly(steps);
  const thinking = thinkingStepsOnly(steps);
  if (thinking.length > 0 && tools.length === 0) return "";
  const verbs: string[] = [];
  for (const step of tools) {
    if (step.type !== "command" && step.type !== "edit") continue;
    const name = step.toolName || step.title || "tool";
    const v = toolSummaryVerb(name);
    if (!verbs.includes(v)) verbs.push(v);
  }
  if (verbs.length === 0) return "Activity";
  return verbs.map(titleCasePhrase).join(", ");
}

/** Tool/edit/error steps for the activity timeline (excludes reasoning). */
export function toolStepsOnly(steps: ProcessStep[]): ProcessStep[] {
  return steps.filter(
    (s) => s.type === "command" || s.type === "edit" || s.type === "error",
  );
}

export function thinkingStepsOnly(steps: ProcessStep[]): ProcessStep[] {
  return steps.filter((s) => s.type === "thinking");
}

export function thinkingStepsToActivityRows(steps: ProcessStep[]): ActivityRow[] {
  const rows: ActivityRow[] = [];
  for (const step of thinkingStepsOnly(steps)) {
    const running = step.status === "running";
    const cancelled = step.status === "cancelled";
    const title =
      step.title === "Reasoning" || step.title === "Deep Thinking"
        ? "Reasoning"
        : step.title;
    rows.push({
      kind: "thinking",
      id: step.id,
      label: running
        ? "Thinking…"
        : cancelled
          ? "Thinking stopped"
          : title || "Thought Process",
      detail: thinkingPreviewLine(step.content),
      status: step.status,
      expandable: Boolean(step.content.trim()),
      expandContent: step.content.trim() || undefined,
    });
  }
  return rows;
}

export function stepsToActivityRows(steps: ProcessStep[]): ActivityRow[] {
  return [...thinkingStepsToActivityRows(steps), ...toolStepsToActivityRows(steps)];
}

export function toolStepsToActivityRows(steps: ProcessStep[]): ActivityRow[] {
  const rows: ActivityRow[] = [];
  for (const step of toolStepsOnly(steps)) {
    if (step.type !== "command" && step.type !== "edit" && step.type !== "error") {
      continue;
    }
    const toolName = step.toolName || step.title || "tool";
    const label = stepReadsSkill(step)
      ? toolActivityLabel("skill_view", step.status)
      : toolActivityLabel(toolName, step.status);
    rows.push({
      kind: "tool",
      id: step.id,
      toolName,
      label,
      detail: detailLine(step),
      fileName: extractFileName(step),
      status: step.status,
      expandable: Boolean(expandContent(step)),
      expandContent: expandContent(step),
    });
  }
  return rows;
}

export function shouldUseActivityTimeline(steps: ProcessStep[]): boolean {
  return steps.some(
    (s) =>
      s.type === "thinking" ||
      s.type === "command" ||
      s.type === "edit" ||
      s.type === "error",
  );
}

/** Hide the terminal "Done" row when the timeline includes reasoning. */
export function activityTimelineShowsDone(steps: ProcessStep[]): boolean {
  return (
    thinkingStepsOnly(steps).length === 0 &&
    toolStepsOnly(steps).length > 0
  );
}
