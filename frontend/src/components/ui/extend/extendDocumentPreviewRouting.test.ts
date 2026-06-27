import { describe, expect, it } from "vitest"

import { extendViewerModuleIdForFileName } from "./extendDocumentRouting"

/**
 * Contract test for ExtendDocumentPreview lazy-module routing.
 * ExtendDocumentPreview switches on extendViewerModuleIdForFileName(fileName).
 */
describe("ExtendDocumentPreview routing contract", () => {
  it("selects the pdf lazy module for PDF files", () => {
    expect(extendViewerModuleIdForFileName("contracts/q1.pdf")).toBe("pdf")
  })

  it("selects docx, xlsx, and csv modules for office formats", () => {
    expect(extendViewerModuleIdForFileName("memo.docx")).toBe("docx")
    expect(extendViewerModuleIdForFileName("sheet.xlsx")).toBe("xlsx")
    expect(extendViewerModuleIdForFileName("rows.csv")).toBe("csv")
  })

  it("returns null so FileContentRenderer handles other preview types", () => {
    expect(extendViewerModuleIdForFileName("index.html")).toBeNull()
    expect(extendViewerModuleIdForFileName("logo.png")).toBeNull()
  })
})
