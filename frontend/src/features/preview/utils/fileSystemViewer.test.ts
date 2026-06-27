import { describe, expect, it } from "vitest"

import {
  isPreviewableExtension,
  shouldSkipTextContentLoad,
  viewerKindForFile,
  viewerKindForFileName,
} from "./fileSystemViewer"

describe("viewerKindForFile", () => {
  it("detects PDF files by extension", () => {
    expect(viewerKindForFile({ path: "reports/q1.pdf" })).toBe("pdf")
  })

  it("detects DOCX and spreadsheet viewers", () => {
    expect(viewerKindForFile({ path: "notes/meeting.docx" })).toBe("docx")
    expect(viewerKindForFile({ path: "data/sheet.xlsx" })).toBe("xlsx")
    expect(viewerKindForFile({ path: "legacy/sheet.xls" })).toBe("xlsx")
    expect(viewerKindForFile({ path: "export/data.csv" })).toBe("csv")
  })

  it("detects images by mime type or extension", () => {
    expect(
      viewerKindForFile({
        path: "assets/photo",
        contentType: "image/png",
      })
    ).toBe("image")
    expect(viewerKindForFile({ path: "assets/photo.webp" })).toBe("image")
  })

  it("returns null for unsupported file types", () => {
    expect(viewerKindForFile({ path: "readme.txt" })).toBeNull()
    expect(viewerKindForFile({ path: "archive.zip" })).toBeNull()
  })
})

describe("viewerKindForFileName", () => {
  it("routes preview panel document types to Extend viewers", () => {
    expect(viewerKindForFileName("report.pdf")).toBe("pdf")
    expect(viewerKindForFileName("notes.docx")).toBe("docx")
    expect(viewerKindForFileName("budget.xlsx")).toBe("xlsx")
    expect(viewerKindForFileName("budget.xls")).toBe("xlsx")
    expect(viewerKindForFileName("rows.csv")).toBe("csv")
  })
})

describe("isPreviewableExtension", () => {
  it("enables preview mode for supported extensions", () => {
    expect(isPreviewableExtension("pdf")).toBe(true)
    expect(isPreviewableExtension("docx")).toBe(true)
    expect(isPreviewableExtension("csv")).toBe(true)
    expect(isPreviewableExtension("md")).toBe(true)
  })

  it("disables preview mode for plain text code files", () => {
    expect(isPreviewableExtension("txt")).toBe(false)
    expect(isPreviewableExtension("py")).toBe(false)
  })
})

describe("shouldSkipTextContentLoad", () => {
  it("skips UTF-8 read for binary office documents", () => {
    expect(shouldSkipTextContentLoad("docx")).toBe(true)
    expect(shouldSkipTextContentLoad("pdf")).toBe(true)
    expect(shouldSkipTextContentLoad("pptx")).toBe(true)
    expect(shouldSkipTextContentLoad("ppt")).toBe(true)
    expect(shouldSkipTextContentLoad("xlsx")).toBe(true)
  })

  it("loads text content for editable source files", () => {
    expect(shouldSkipTextContentLoad("md")).toBe(false)
    expect(shouldSkipTextContentLoad("py")).toBe(false)
  })
})
