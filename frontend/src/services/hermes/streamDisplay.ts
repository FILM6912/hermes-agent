/** Concatenate reasoning SSE token chunks (legacy messages.js uses `+=`, not newlines). */
export function combinedReasoningText(parts: string[]): string {
  return parts.filter(Boolean).join("");
}

export function normalizeThinkingCompare(text: string): string {
  return text.trim().toLowerCase();
}

export function isDistinctThinking(content: string, answerText: string): boolean {
  return normalizeThinkingCompare(content) !== normalizeThinkingCompare(answerText);
}

export function stripThinkingFromAssistantStream(text: string): string {
  return text;
}
