export type ChatErrorPresentation = {
  title: string;
  message: string;
  type: "error" | "warning";
};

function isProviderConnectionError(raw: string): boolean {
  return /connection error|connection lost|apiconnectionerror|econnrefused|failed to connect|unable to reach|network error/i.test(
    raw,
  );
}

/** Map backend/SSE chat failures to user-facing modal copy. */
export function formatChatError(error: unknown): ChatErrorPresentation {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : JSON.stringify(error);

  if (
    raw.includes("model is required") ||
    raw.includes("No model selected")
  ) {
    return {
      title: "กรุณาเลือก Model",
      message: "คุณยังไม่ได้เลือก model กรุณาเลือก model ก่อนส่งข้อความ",
      type: "warning",
    };
  }

  if (
    raw.includes("429") ||
    raw.includes("quota") ||
    raw.includes("RESOURCE_EXHAUSTED")
  ) {
    return {
      title: "API Quota Exceeded",
      message:
        "You have exceeded your request quota. Please check your billing details or try again later.",
      type: "error",
    };
  }

  if (isProviderConnectionError(raw)) {
    return {
      title: "Model provider unreachable",
      message:
        "Hermes could not reach the selected model provider. Chat transport (POST /chat/start and SSE /chat/stream) succeeded, but the server failed to call the model API. If you use a local server (LM Studio, Ollama, etc.), ensure it is running and reachable from the Hermes host — inside Docker, 127.0.0.1 is the container, not your machine.",
      type: "error",
    };
  }

  return {
    title: "Error Generating Response",
    message: raw,
    type: "error",
  };
}
