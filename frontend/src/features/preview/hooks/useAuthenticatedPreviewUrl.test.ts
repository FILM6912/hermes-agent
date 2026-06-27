import { describe, expect, it } from "vitest";

import { parseHermesApiUrl } from "@/features/preview/hooks/useAuthenticatedPreviewUrl";

describe("parseHermesApiUrl", () => {
  it("parses Hermes file raw preview URLs", () => {
    expect(
      parseHermesApiUrl(
        "/api/v1/file/raw?path=random_data.csv&session_id=s1&inline=1",
      ),
    ).toEqual({
      path: "/api/v1/file/raw",
      query: {
        path: "random_data.csv",
        session_id: "s1",
        inline: "1",
      },
    });
  });

  it("returns null for non-API URLs", () => {
    expect(parseHermesApiUrl("https://example.com/file.csv")).toBeNull();
    expect(parseHermesApiUrl("blob:https://example.com/uuid")).toBeNull();
  });
});
