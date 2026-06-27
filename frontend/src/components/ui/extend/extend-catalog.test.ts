import { describe, expect, it } from "vitest"

import {
  EXTEND_UI_COMPONENT_IDS,
  extendComponentCatalog,
  getExtendComponentEntry,
} from "./extend-catalog"

describe("extendComponentCatalog", () => {
  it("lists all 15 Extend UI document components", () => {
    expect(EXTEND_UI_COMPONENT_IDS).toHaveLength(15)
    expect(extendComponentCatalog.map((entry) => entry.id)).toEqual(
      EXTEND_UI_COMPONENT_IDS,
    )
  })

  it("marks core viewers as implemented", () => {
    const implemented = extendComponentCatalog
      .filter((entry) => entry.status === "implemented")
      .map((entry) => entry.id)

    expect(implemented).toEqual(
      expect.arrayContaining([
        "pdf-viewer",
        "docx-viewer",
        "docx-editor",
        "xlsx-viewer",
        "xlsx-editor",
        "csv-viewer",
        "file-upload",
        "file-system",
        "file-thumbnail",
        "document-viewer-sidebar",
      ]),
    )
  })

  it("exposes experimental stubs for extraction workflow components", () => {
    const stubIds = [
      "bounding-box-citations",
      "schema-builder",
      "layout-blocks",
      "e-signature",
      "document-splits",
    ] as const

    for (const id of stubIds) {
      expect(getExtendComponentEntry(id)?.status).toBe("stub")
    }
  })
})
