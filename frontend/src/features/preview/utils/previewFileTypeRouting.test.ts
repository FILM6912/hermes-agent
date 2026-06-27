import { describe, expect, it } from "vitest"

import {
  isPreviewableExtension,
  viewerKindForFileName,
} from "./fileSystemViewer"

/**
 * Public routing contract for the preview panel Extend document viewers.
 * Tests behavior (which viewer handles which extension), not component internals.
 */
describe("preview panel file type routing", () => {
  it("maps document extensions to Extend viewer kinds", () => {
    expect(viewerKindForFileName("report.pdf")).toBe("pdf")
    expect(viewerKindForFileName("memo.docx")).toBe("docx")
    expect(viewerKindForFileName("budget.xlsx")).toBe("xlsx")
    expect(viewerKindForFileName("legacy.xls")).toBe("xlsx")
    expect(viewerKindForFileName("export.csv")).toBe("csv")
  })

  it("maps image extensions to image preview", () => {
    expect(viewerKindForFileName("photo.png")).toBe("image")
    expect(viewerKindForFileName("icon.svg")).toBe("image")
  })

  it("returns null for unsupported preview document types", () => {
    expect(viewerKindForFileName("script.py")).toBeNull()
    expect(viewerKindForFileName("archive.zip")).toBeNull()
  })

  it("enables preview mode toggle for markdown and documents", () => {
    expect(isPreviewableExtension("md")).toBe(true)
    expect(isPreviewableExtension("docx")).toBe(true)
    expect(isPreviewableExtension("csv")).toBe(true)
    expect(isPreviewableExtension("json")).toBe(false)
  })
})
