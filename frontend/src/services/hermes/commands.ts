/**
 * Hermes slash-command API (M23).
 * GET /commands — agent/plugin command metadata for composer autocomplete.
 * POST /commands/exec — execute plugin-registered slash commands.
 * GET /skills — skill slugs merged into `/` autocomplete (legacy parity).
 */
import { listSkills } from "@/features/skills/api/skillsApi";
import type { HermesSkill } from "@/features/skills/types";
import { fetchJson } from "@/lib/api";

export type HermesCommand = {
  name: string;
  description: string;
  category: string;
  aliases: string[];
  args_hint: string;
  subcommands: string[];
  cli_only: boolean;
  gateway_only: boolean;
};

export type HermesCommandsResponse = {
  commands: HermesCommand[];
};

export type HermesCommandExecResponse = {
  output?: string;
  error?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/** Narrow unknown JSON to typed command entries. */
export function narrowCommand(value: unknown): HermesCommand | null {
  if (!isRecord(value)) return null;
  const name = asString(value.name).trim();
  if (!name) return null;
  return {
    name,
    description: asString(value.description),
    category: asString(value.category),
    aliases: asStringArray(value.aliases),
    args_hint: asString(value.args_hint),
    subcommands: asStringArray(value.subcommands),
    cli_only: value.cli_only === true,
    gateway_only: value.gateway_only === true,
  };
}

export function narrowCommandsResponse(value: unknown): HermesCommandsResponse {
  if (!isRecord(value) || !Array.isArray(value.commands)) {
    return { commands: [] };
  }
  const commands = value.commands
    .map(narrowCommand)
    .filter((cmd): cmd is HermesCommand => cmd !== null);
  return { commands };
}

/** GET /api/v1/commands — slash-command metadata for autocomplete. */
export async function listCommands(): Promise<HermesCommand[]> {
  const raw = await fetchJson<unknown>("/commands");
  return narrowCommandsResponse(raw).commands;
}

/** POST /api/v1/commands/exec — run a plugin slash command. */
export async function execCommand(command: string): Promise<HermesCommandExecResponse> {
  const raw = await fetchJson<unknown>("/commands/exec", {
    method: "POST",
    body: { command: command.trim() },
  });
  if (!isRecord(raw)) return {};
  return {
    output: asString(raw.output) || undefined,
    error: asString(raw.error) || undefined,
  };
}

export type SlashCommandMatch = {
  name: string;
  description: string;
  category: string;
  argsHint?: string;
  /** Sub-arg row when completing `/cmd arg` */
  subArg?: string;
  parent?: string;
  /** Skill-backed `/slug` entry from GET /skills */
  source?: "command" | "skill";
};

/** Slug for skill slash autocomplete (matches static-legacy/commands.js). */
export function skillCommandSlug(name: string): string {
  const raw = String(name || "")
    .trim()
    .toLowerCase();
  if (!raw) return "";
  return raw
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

let skillsCache: HermesSkill[] | null = null;
let skillsLoadPromise: Promise<HermesSkill[]> | null = null;

/** Lazy-load skills for composer `/` autocomplete. */
export async function loadSkillsForSlashCached(): Promise<HermesSkill[]> {
  if (skillsCache) return skillsCache;
  if (skillsLoadPromise) return skillsLoadPromise;
  skillsLoadPromise = listSkills()
    .then((data) => {
      skillsCache = data.skills ?? [];
      return skillsCache;
    })
    .catch(() => {
      skillsCache = [];
      return [];
    })
    .finally(() => {
      skillsLoadPromise = null;
    });
  return skillsLoadPromise;
}

export function invalidateSkillsForSlashCache(): void {
  skillsCache = null;
  skillsLoadPromise = null;
}

function buildSkillSlashMatch(
  skill: HermesSkill,
  reservedNames: Set<string>,
  defaultDescription: string,
): SlashCommandMatch | null {
  const slug = skillCommandSlug(skill.name);
  if (!slug || reservedNames.has(slug)) return null;
  return {
    name: slug,
    description: String(skill.description || "").trim() || defaultDescription,
    category: "Skill",
    source: "skill",
  };
}

export type SlashTokenRange = {
  start: number;
  end: number;
  token: string;
};

/** Active `/command` token at the cursor (after whitespace or start of line). */
export function extractSlashToken(text: string, cursor: number): SlashTokenRange | null {
  if (text.includes("\n")) return null;
  const pos = Math.max(0, Math.min(cursor, text.length));

  let slashIdx = -1;
  for (let i = pos - 1; i >= 0; i--) {
    if (text[i] === "\n") return null;
    if (text[i] === "/") {
      if (i === 0 || /\s/.test(text[i - 1] ?? "")) {
        slashIdx = i;
        break;
      }
    }
  }
  if (slashIdx < 0 || pos <= slashIdx) return null;

  return {
    start: slashIdx,
    end: pos,
    token: text.slice(slashIdx, pos),
  };
}

export function buildSlashReplacement(match: SlashCommandMatch): string {
  if (match.subArg && match.parent) {
    return `/${match.parent} ${match.subArg} `;
  }
  if (match.source === "skill") {
    return `/${match.name}`;
  }
  if (match.argsHint) {
    return `/${match.name} `;
  }
  return `/${match.name}`;
}

export function applySlashMatchToInput(
  input: string,
  range: SlashTokenRange,
  match: SlashCommandMatch,
): { value: string; cursor: number } {
  const replacement = buildSlashReplacement(match);
  const before = input.slice(0, range.start);
  const after = input.slice(range.end);
  const value = before + replacement + after;
  return { value, cursor: before.length + replacement.length };
}

/** Filter Hermes commands (+ optional skills) for composer autocomplete after `/`. */
export function matchSlashCommands(
  text: string,
  commands: HermesCommand[],
  options?: { skills?: HermesSkill[]; skillDefaultDescription?: string },
): SlashCommandMatch[] {
  const skills = options?.skills ?? [];
  const skillDefaultDescription =
    options?.skillDefaultDescription ?? "Invoke this skill";
  if (!text.startsWith("/") || text.includes("\n")) return [];

  const body = text.slice(1);
  const hasSpace = /\s/.test(body);
  const parts = body.split(/\s+/);
  const cmdName = (parts[0] || "").toLowerCase();
  const argQuery = body.slice(cmdName.length).replace(/^\s+/, "").toLowerCase();

  const findCmd = (name: string) =>
    commands.find(
      (c) =>
        c.name.toLowerCase() === name ||
        c.aliases.some((a) => a.toLowerCase() === name),
    );

  if (hasSpace && cmdName) {
    const cmd = findCmd(cmdName);
    if (cmd && cmd.subcommands.length > 0) {
      return cmd.subcommands
        .filter((sub) => sub.toLowerCase().startsWith(argQuery))
        .map((sub) => ({
          name: cmd.name,
          description: cmd.description,
          category: cmd.category,
          subArg: sub,
          parent: cmd.name,
        }));
    }
    if (cmd?.args_hint && argQuery === "") {
      return [
        {
          name: cmd.name,
          description: cmd.description,
          category: cmd.category,
          argsHint: cmd.args_hint,
        },
      ];
    }
    return [];
  }

  const query = body.toLowerCase();
  const seen = new Set<string>();
  const matches: SlashCommandMatch[] = [];

  for (const cmd of commands) {
    if (cmd.cli_only || cmd.gateway_only) continue;
    const name = cmd.name.toLowerCase();
    if (!name.startsWith(query) || seen.has(name)) continue;
    seen.add(name);
    matches.push({
      name: cmd.name,
      description: cmd.description,
      category: cmd.category,
      argsHint: cmd.args_hint || undefined,
      source: "command",
    });
  }

  const skillDedup = new Map<string, SlashCommandMatch>();
  for (const skill of skills) {
    const entry = buildSkillSlashMatch(skill, seen, skillDefaultDescription);
    if (entry && !skillDedup.has(entry.name)) skillDedup.set(entry.name, entry);
  }
  for (const entry of skillDedup.values()) {
    if (!entry.name.toLowerCase().startsWith(query)) continue;
    seen.add(entry.name);
    matches.push(entry);
  }

  return matches.sort((a, b) => a.name.localeCompare(b.name));
}
