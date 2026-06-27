"use client"

import * as React from "react"
import { Share2 } from "lucide-react"

import { Spinner } from "@/components/ui/spinner"
import { useLanguage } from "@/hooks/useLanguage"
import { extendViewerModuleIdForFileName } from "@/components/ui/extend/extendDocumentRouting"
import { useAuthenticatedPreviewUrl } from "@/features/preview/hooks/useAuthenticatedPreviewUrl"

const PDFViewer = React.lazy(() =>
  import("@/components/ui/pdf-viewer").then((module) => ({
    default: module.PDFViewer,
  })),
)

const DocxViewerPreview = React.lazy(() =>
  import("@/components/ui/docx-viewer").then((module) => ({
    default: module.DocxViewerPreview,
  })),
)

const XlsxViewerPreview = React.lazy(() =>
  import("@/components/ui/xlsx-viewer").then((module) => ({
    default: module.XlsxViewerPreview,
  })),
)

const CsvViewerPreview = React.lazy(() =>
  import("@/features/preview/components/CsvViewerPreview").then((module) => ({
    default: module.CsvViewerPreview,
  })),
)

function ViewerSuspense({ children }: { children: React.ReactNode }) {
  return (
    <React.Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      }
    >
      {children}
    </React.Suspense>
  )
}

export type ExtendDocumentPreviewProps = {
  fileName: string
  fileUrl: string | null
  isDark?: boolean
  showToolbar?: boolean
  openInBrowserUrl?: string | null
  /** When fileUrl is missing: loading session vs permanently unavailable. */
  urlState?: "ready" | "loading" | "unavailable"
}

export function ExtendDocumentPreview({
  fileName,
  fileUrl,
  isDark,
  showToolbar = true,
  openInBrowserUrl = null,
  urlState = fileUrl ? "ready" : "unavailable",
}: ExtendDocumentPreviewProps) {
  const { t } = useLanguage()
  const kind = extendViewerModuleIdForFileName(fileName)
  const { url: authenticatedUrl, state: authState } =
    useAuthenticatedPreviewUrl(fileUrl)

  if (!fileUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-muted-foreground">
        {urlState === "loading" ? (
          <>
            <Spinner className="size-5" />
            <span className="text-sm">{t("preview.htmlPreviewLoading")}</span>
          </>
        ) : (
          <span className="text-sm">{t("preview.htmlPreviewUnavailable")}</span>
        )}
      </div>
    )
  }

  if (urlState === "loading" || authState === "loading") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-muted-foreground">
        <Spinner className="size-5" />
        <span className="text-sm">{t("preview.htmlPreviewLoading")}</span>
      </div>
    )
  }

  if (authState === "error" || !authenticatedUrl) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-muted-foreground">
        <span className="text-sm">{t("preview.htmlPreviewUnavailable")}</span>
      </div>
    )
  }

  const viewerClassName = "h-full min-h-0 flex-1"

  switch (kind) {
    case "pdf":
      return (
        <ViewerSuspense>
          <PDFViewer
            file={authenticatedUrl}
            className={viewerClassName}
            downloadFileName={fileName}
            showUpload={false}
            toolbarActions={
              openInBrowserUrl ? (
                <a
                  href={openInBrowserUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Share2 className="size-3.5" />
                  {t("preview.openExternal")}
                </a>
              ) : undefined
            }
          />
        </ViewerSuspense>
      )
    case "docx":
      return (
        <ViewerSuspense>
          <DocxViewerPreview
            src={authenticatedUrl}
            fileName={fileName}
            className={viewerClassName}
            isDark={isDark}
            showToolbar={showToolbar}
            showUpload={false}
          />
        </ViewerSuspense>
      )
    case "xlsx":
      return (
        <ViewerSuspense>
          <XlsxViewerPreview
            src={authenticatedUrl}
            fileName={fileName}
            className={viewerClassName}
            isDark={isDark}
            showToolbar={showToolbar}
            showUpload={false}
          />
        </ViewerSuspense>
      )
    case "csv":
      return (
        <ViewerSuspense>
          <CsvViewerPreview
            src={authenticatedUrl}
            fileName={fileName}
            className={viewerClassName}
            isDark={isDark}
            showToolbar={showToolbar}
          />
        </ViewerSuspense>
      )
    default:
      return null
  }
}
