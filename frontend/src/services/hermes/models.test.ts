import { describe, expect, it } from "vitest";
import { modelsToPickerOptions } from "./models";

describe("modelsToPickerOptions", () => {
  it("skips provider groups that failed endpoint probes", () => {
    const options = modelsToPickerOptions({
      groups: [
        {
          provider: "Broken Proxy",
          provider_id: "custom:broken-proxy",
          models: [{ id: "@custom:broken-proxy:broken/manual", label: "broken/manual" }],
          models_endpoint_error: {
            kind: "network",
            code: null,
            message: "Models endpoint unreachable",
          },
        },
        {
          provider: "OpenRouter",
          provider_id: "openrouter",
          models: [{ id: "anthropic/claude-sonnet-4", label: "Claude Sonnet 4" }],
        },
      ],
    });

    expect(options.map((row) => row.id)).toEqual(["anthropic/claude-sonnet-4"]);
  });
});
