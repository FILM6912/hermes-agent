import type { DocumentProps } from "react-pdf"

/** Same-origin worker URL (Vite emits this asset under /static/dist/). */
import pdfWorkerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url"

export const PDFJS_WORKER_SRC = pdfWorkerSrc

export function configurePdfjsWorker(pdfjs: {
  GlobalWorkerOptions: { workerSrc: string }
}) {
  pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_SRC
}

/** CDN base allowed by Hermes CSP `connect-src` (not unpkg). */
export function getPdfAssetBaseUrl(pdfjsVersion: string) {
  return `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjsVersion}`
}

export function getDefaultPdfDocumentOptions(
  pdfjsVersion: string,
): NonNullable<DocumentProps["options"]> {
  const assetBaseUrl = getPdfAssetBaseUrl(pdfjsVersion)

  return {
    cMapPacked: true,
    cMapUrl: `${assetBaseUrl}/cmaps/`,
    standardFontDataUrl: `${assetBaseUrl}/standard_fonts/`,
    withCredentials: true,
  }
}
