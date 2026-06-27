import type { HermesSessionDetail } from "@/types/hermes/sessions";

/** Token / context-window usage for the active session (composer indicator). */
export type SessionContextUsage = {
  input_tokens?: number;
  output_tokens?: number;
  last_prompt_tokens?: number;
  context_length?: number;
  threshold_tokens?: number;
  estimated_cost?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cache_hit_percent?: number | null;
};

export type ContextUsageLevel = "normal" | "mid" | "high";

export type ContextUsageDisplay = {
  visible: boolean;
  pct: number;
  rawPct: number;
  overflowed: boolean;
  hasPromptTok: boolean;
  hasExplicitCtx: boolean;
  label: string;
  usageText: string;
  tokensText: string;
  thresholdText: string;
  costText: string;
  compressHint: "" | "hint" | "action";
  level: ContextUsageLevel;
  promptTok: number;
  ctxWindow: number;
};

const DEFAULT_CTX = 128 * 1024;

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function hasAnyUsage(usage: SessionContextUsage): boolean {
  return !!(
    usage.last_prompt_tokens ||
    (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0) ||
    usage.estimated_cost ||
    usage.cache_read_tokens ||
    usage.cache_write_tokens
  );
}

/** Parse a Hermes usage/session payload into normalized context usage fields. */
export function parseContextUsage(
  raw: Record<string, unknown> | undefined,
): SessionContextUsage | undefined {
  if (!raw) return undefined;
  const usage: SessionContextUsage = {
    input_tokens: finiteNumber(raw.input_tokens),
    output_tokens: finiteNumber(raw.output_tokens),
    last_prompt_tokens: finiteNumber(raw.last_prompt_tokens),
    context_length: finiteNumber(raw.context_length),
    threshold_tokens: finiteNumber(raw.threshold_tokens),
    estimated_cost: finiteNumber(raw.estimated_cost),
    cache_read_tokens: finiteNumber(raw.cache_read_tokens),
    cache_write_tokens: finiteNumber(raw.cache_write_tokens),
    cache_hit_percent:
      raw.cache_hit_percent == null
        ? undefined
        : (finiteNumber(raw.cache_hit_percent) ?? null),
  };
  return hasAnyUsage(usage) ? usage : undefined;
}

/** Build context usage from GET /session detail (compact token fields). */
export function contextUsageFromHermesSession(
  detail: HermesSessionDetail | Record<string, unknown>,
): SessionContextUsage | undefined {
  return parseContextUsage(detail as Record<string, unknown>);
}

/**
 * Merge live SSE usage into stored session usage.
 * Mirrors legacy sessions.js load + metering merge semantics (#1436).
 */
export function mergeContextUsage(
  stored: SessionContextUsage | undefined,
  live: SessionContextUsage,
): SessionContextUsage {
  const pick = (latest?: number, previous?: number) =>
    latest != null && latest !== 0 ? latest : previous;

  return {
    input_tokens: pick(live.input_tokens, stored?.input_tokens),
    output_tokens: pick(live.output_tokens, stored?.output_tokens),
    estimated_cost: live.estimated_cost ?? stored?.estimated_cost,
    cache_read_tokens: pick(live.cache_read_tokens, stored?.cache_read_tokens),
    cache_write_tokens: pick(live.cache_write_tokens, stored?.cache_write_tokens),
    cache_hit_percent: live.cache_hit_percent ?? stored?.cache_hit_percent,
    context_length: stored?.context_length || live.context_length,
    threshold_tokens: stored?.threshold_tokens || live.threshold_tokens,
    last_prompt_tokens: pick(live.last_prompt_tokens, stored?.last_prompt_tokens),
  };
}

export function formatTokenCount(value: number): string {
  const n = Math.max(0, value || 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

type Translate = (key: string) => string;

/** Compute ring percentage + tooltip copy from usage (#1436: last_prompt_tokens only). */
export function computeContextUsageDisplay(
  usage: SessionContextUsage | undefined,
  t: Translate,
): ContextUsageDisplay {
  const empty: ContextUsageDisplay = {
    visible: false,
    pct: 0,
    rawPct: 0,
    overflowed: false,
    hasPromptTok: false,
    hasExplicitCtx: false,
    label: "",
    usageText: "",
    tokensText: "",
    thresholdText: "",
    costText: "",
    compressHint: "",
    level: "normal",
    promptTok: 0,
    ctxWindow: DEFAULT_CTX,
  };
  if (!usage || !hasAnyUsage(usage)) return empty;

  const promptTok = usage.last_prompt_tokens || 0;
  const totalTok = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  const cacheReadTok = usage.cache_read_tokens || 0;
  const cacheWriteTok = usage.cache_write_tokens || 0;
  const ctxWindow = usage.context_length || DEFAULT_CTX;
  const cost = usage.estimated_cost;
  const hasPromptTok = !!promptTok;
  const rawPct = hasPromptTok ? Math.round((promptTok / ctxWindow) * 100) : 0;
  const pct = Math.min(100, rawPct);
  const overflowed = rawPct > 100;
  const hasExplicitCtx = !!usage.context_length;
  const level: ContextUsageLevel =
    pct > 75 ? "high" : pct > 50 ? "mid" : "normal";
  const compressHint: ContextUsageDisplay["compressHint"] =
    pct >= 75 ? "action" : pct >= 50 ? "hint" : "";

  const cacheHitPct = usage.cache_hit_percent;
  const cacheText =
    cacheHitPct != null
      ? t("chat.contextUsageCacheHit")
          .replace("{pct}", String(cacheHitPct))
          .replace("{read}", formatTokenCount(cacheReadTok))
          .replace("{write}", formatTokenCount(cacheWriteTok))
      : "";

  let label = hasPromptTok
    ? t("chat.contextUsageLabel").replace("{pct}", String(pct))
    : t("chat.contextUsageTokensUsed").replace(
        "{count}",
        formatTokenCount(totalTok),
      );
  if (!hasExplicitCtx && hasPromptTok) {
    label += ` ${t("chat.contextUsageEst128k")}`;
  }
  if (cost) {
    label += ` · $${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}`;
  }
  if (cacheText) label += ` · ${cacheText}`;

  const usageText = hasPromptTok
    ? overflowed
      ? t("chat.contextUsageExceeded").replace("{pct}", String(rawPct))
      : t("chat.contextUsagePercentLeft")
          .replace("{pct}", String(pct))
          .replace("{left}", String(100 - pct))
    : t("chat.contextUsageTokensUsed").replace(
        "{count}",
        formatTokenCount(totalTok),
      );

  const tokensText = hasPromptTok
    ? t("chat.contextUsagePromptTokens")
        .replace("{used}", formatTokenCount(promptTok))
        .replace("{window}", formatTokenCount(ctxWindow))
    : t("chat.contextUsageInOut")
        .replace("{input}", formatTokenCount(usage.input_tokens || 0))
        .replace("{output}", formatTokenCount(usage.output_tokens || 0));

  const threshold = usage.threshold_tokens || 0;
  let thresholdText = "";
  if (threshold && ctxWindow) {
    thresholdText = t("chat.contextUsageThreshold")
      .replace("{tokens}", formatTokenCount(threshold))
      .replace("{pct}", String(Math.round((threshold / ctxWindow) * 100)));
  }

  let costText = "";
  if (cost) {
    costText = t("chat.contextUsageCost")
      .replace(
        "{cost}",
        cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2),
      );
    if (cacheText) costText += ` · ${cacheText}`;
  } else if (cacheText) {
    costText = cacheText;
  }

  return {
    visible: true,
    pct,
    rawPct,
    overflowed,
    hasPromptTok,
    hasExplicitCtx,
    label,
    usageText,
    tokensText,
    thresholdText,
    costText,
    compressHint,
    level,
    promptTok,
    ctxWindow,
  };
}

/** SVG ring circumference for the 24px composer indicator (legacy parity). */
export const CONTEXT_RING_CIRCUMFERENCE = 61.261056745;
