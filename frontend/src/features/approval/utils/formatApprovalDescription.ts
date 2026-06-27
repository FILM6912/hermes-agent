export function formatApprovalDescription(pending: {
  description?: string;
  pattern_key?: string;
  pattern_keys?: string[];
}): string {
  const keys =
    pending.pattern_keys ??
    (pending.pattern_key ? [pending.pattern_key] : []);
  const desc = pending.description ?? "";
  if (keys.length === 0) return desc;
  return `${desc}${desc ? " " : ""}[${keys.join(", ")}]`.trim();
}
