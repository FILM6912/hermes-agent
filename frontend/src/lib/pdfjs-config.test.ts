import { describe, expect, it } from "vitest"

import {
  PDFJS_WORKER_SRC,
  configurePdfjsWorker,
  getDefaultPdfDocumentOptions,
  getPdfAssetBaseUrl,
} from "./pdfjs-config"

describe("pdfjs-config", () => {
  it("uses a bundled same-origin worker, not an external CDN", () => {
    expect(PDFJS_WORKER_SRC).toBeTruthy()
    expect(PDFJS_WORKER_SRC).not.toContain("unpkg.com")
    expect(PDFJS_WORKER_SRC).not.toContain("cdn.jsdelivr.net")
  })

  it("configures pdfjs GlobalWorkerOptions from the bundled worker", () => {
    const pdfjs = { GlobalWorkerOptions: { workerSrc: "" } }
    configurePdfjsWorker(pdfjs)
    expect(pdfjs.GlobalWorkerOptions.workerSrc).toBe(PDFJS_WORKER_SRC)
  })

  it("loads cmap and font assets from jsdelivr (CSP connect-src allowlist)", () => {
    const version = "5.4.296"
    expect(getPdfAssetBaseUrl(version)).toBe(
      `https://cdn.jsdelivr.net/npm/pdfjs-dist@${version}`,
    )

    const options = getDefaultPdfDocumentOptions(version)
    expect(options.cMapUrl).toBe(
      `https://cdn.jsdelivr.net/npm/pdfjs-dist@${version}/cmaps/`,
    )
    expect(options.standardFontDataUrl).toBe(
      `https://cdn.jsdelivr.net/npm/pdfjs-dist@${version}/standard_fonts/`,
    )
    expect(options.cMapUrl).not.toContain("unpkg.com")
    expect(options.withCredentials).toBe(true)
  })
})
