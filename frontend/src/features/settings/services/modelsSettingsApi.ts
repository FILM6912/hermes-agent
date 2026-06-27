/**
 * Default model settings API — persists Hermes config.yaml default (legacy POST /api/default-model).
 */
import { fetchJson } from "@/lib/api";

export type SaveDefaultModelResponse = {
  ok?: boolean;
  model?: string;
  error?: string;
};

/** POST /api/v1/default-model — write default model to Hermes config.yaml. */
export async function saveDefaultModel(model: string): Promise<SaveDefaultModelResponse> {
  const trimmed = model.trim();
  if (!trimmed) {
    throw new Error("model is required");
  }
  return fetchJson<SaveDefaultModelResponse>("/default-model", {
    method: "POST",
    body: { model: trimmed },
  });
}
