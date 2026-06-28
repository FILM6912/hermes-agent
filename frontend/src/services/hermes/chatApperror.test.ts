import { describe, expect, it } from "vitest";
import { formatApperrorAssistantContent } from "@/services/hermes/chat";

describe("formatApperrorAssistantContent", () => {
  it("formats generic provider errors with optional hint", () => {
    const content = formatApperrorAssistantContent({
      type: "error",
      message:
        "Provider 'custom:local-localhost' is set in config.yaml but no API key was found.",
      hint: "Set the CUSTOM:LOCAL-LOCALHOST_API_KEY environment variable, or switch providers.",
    });
    expect(content).toContain("**Error:**");
    expect(content).toContain("no API key was found");
    expect(content).toContain("*Set the CUSTOM:LOCAL-LOCALHOST_API_KEY");
  });

  it("uses specialized labels for classified apperror types", () => {
    expect(formatApperrorAssistantContent({ type: "auth_mismatch", message: "401" })).toContain(
      "**Provider mismatch:**",
    );
    expect(formatApperrorAssistantContent({ type: "rate_limit", message: "slow down" })).toContain(
      "**Rate limit reached:**",
    );
  });
});
