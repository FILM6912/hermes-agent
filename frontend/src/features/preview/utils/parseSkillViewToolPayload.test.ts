import { describe, expect, it } from "vitest";
import type { ProcessStep } from "@/types";
import {
  isSkillViewToolResult,
  parseSkillViewFromStep,
  stepUsesSkillViewPanel,
} from "@/features/preview/utils/parseSkillViewToolPayload";

describe("parseSkillViewToolPayload", () => {
  it("does not treat session_search output as skill_view", () => {
    const output = JSON.stringify({
      success: true,
      mode: "discover",
      query: "psalm",
      results: [
        {
          session_id: "abc",
          title: "Earlier chat",
          messages: [
            {
              role: "assistant",
              tool_calls: [{ function: { name: "skill_view", arguments: '{"name":"skill_view"}' } }],
            },
          ],
        },
      ],
      count: 1,
    });

    const step: ProcessStep = {
      id: "tool-session_search-0",
      type: "command",
      title: "session_search",
      toolName: "session_search",
      content: `Input:\n\`\`\`json\n{"query":"psalm"}\n\`\`\`\n\nOutput:\n${output}`,
      status: "completed",
      isExpanded: false,
    };

    expect(isSkillViewToolResult(JSON.parse(output))).toBe(false);
    expect(parseSkillViewFromStep(step)).toEqual({ input: null, output: null });
    expect(stepUsesSkillViewPanel(step)).toBe(false);
  });

  it("still routes real skill_view payloads", () => {
    const output = JSON.stringify({
      success: true,
      name: "commit-helper",
      description: "Help write commit messages",
      tags: ["git"],
      relatedSkills: [],
    });

    const step: ProcessStep = {
      id: "tool-skill_view-0",
      type: "command",
      title: "skill_view",
      toolName: "skill_view",
      content: `Input:\n\`\`\`json\n{"name":"commit-helper"}\n\`\`\`\n\nOutput:\n${output}`,
      status: "completed",
      isExpanded: false,
    };

    expect(stepUsesSkillViewPanel(step)).toBe(true);
    expect(parseSkillViewFromStep(step).output?.name).toBe("commit-helper");
  });

  it("does not classify success+name-only JSON as skill results", () => {
    expect(
      isSkillViewToolResult({
        success: true,
        name: "skill_view",
        mode: "discover",
        results: [],
      }),
    ).toBe(false);
  });
});
