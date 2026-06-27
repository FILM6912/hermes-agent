import { describe, expect, it } from "vitest";
import { normalizePublicStorageUrl } from "./storageUrls";

describe("normalizePublicStorageUrl", () => {
  it("fixes LLM component/public typo", () => {
    const broken =
      "https://corp-brain.aitech.co.th/storage/v1/component/public/document-files/spec/files/img_002.jpeg";
    expect(normalizePublicStorageUrl(broken)).toBe(
      "https://corp-brain.aitech.co.th/storage/v1/object/public/document-files/spec/files/img_002.jpeg",
    );
  });

  it("leaves correct object/public URLs unchanged", () => {
    const ok =
      "https://corp-brain.aitech.co.th/storage/v1/object/public/document-files/spec/files/img_001.png";
    expect(normalizePublicStorageUrl(ok)).toBe(ok);
  });
});
