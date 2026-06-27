import { describe, expect, it } from "vitest"

import {
  extendViewerModuleIdForFileName,
  isExtendDocumentPreviewType,
} from "./extendDocumentRouting"

describe("extendViewerModuleIdForFileName", () => {
  it("routes document extensions to Extend preview modules", () => {
    expect(extendViewerModuleIdForFileName("report.pdf")).toBe("pdf")
    expect(extendViewerModuleIdForFileName("memo.docx")).toBe("docx")
    expect(extendViewerModuleIdForFileName("budget.xlsx")).toBe("xlsx")
    expect(extendViewerModuleIdForFileName("legacy.xls")).toBe("xlsx")
    expect(extendViewerModuleIdForFileName("export.csv")).toBe("csv")
  })

  it("returns null for non-Extend preview types", () => {
    expect(extendViewerModuleIdForFileName("photo.png")).toBeNull()
    expect(extendViewerModuleIdForFileName("readme.txt")).toBeNull()
  })
})

describe("isExtendDocumentPreviewType", () => {
  it("identifies files handled by ExtendDocumentPreview", () => {
    expect(isExtendDocumentPreviewType("a.pdf")).toBe(true)
    expect(isExtendDocumentPreviewType("b.docx")).toBe(true)
    expect(isExtendDocumentPreviewType("c.csv")).toBe(true)
    expect(isExtendDocumentPreviewType("d.html")).toBe(false)
  })
})
