import type { Message } from "@/types";
import type { ClarifyPending } from "../services/clarifyApi";

export function clarifyQuestionFromPending(
  pending: ClarifyPending | null | undefined,
): string {
  if (!pending) return "";
  return String(pending.question ?? pending.description ?? "").trim();
}

/** Visible transcript line after the user answers a clarify prompt. */
export function formatClarifyEchoMessage(question: string, answer: string): string {
  const q = question.trim();
  const a = answer.trim();
  if (!q) return a;
  if (!a) return `Q: ${q}`;
  return `Q: ${q}\nA: ${a}`;
}

/** Insert clarify Q/A before the trailing assistant bubble (live stream order). */
export function insertClarifyEchoIntoMessages(
  messages: Message[],
  echo: Message,
): Message[] {
  const content = echo.content.trim();
  if (
    content &&
    messages.some((m) => m.role === "user" && m.content.trim() === content)
  ) {
    return messages;
  }

  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "assistant") {
      const next = [...messages];
      next.splice(i, 0, echo);
      return next;
    }
  }

  return [...messages, echo];
}
