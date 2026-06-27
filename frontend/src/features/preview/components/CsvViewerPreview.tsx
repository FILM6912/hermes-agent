"use client"

import * as React from "react"
import * as XLSX from "xlsx"

import { Spinner } from "@/components/ui/spinner"
import { XlsxViewerPreview } from "@/components/ui/xlsx-viewer"

type CsvViewerPreviewProps = {
  className?: string
  fileName?: string
  isDark?: boolean
  showToolbar?: boolean
  src: string
}

/**
 * Converts CSV fetched from a URL into an in-memory XLSX buffer so the Extend
 * workbook viewer can render tabular data with the same chrome as XLSX files.
 */
export function CsvViewerPreview({
  className,
  fileName,
  isDark,
  showToolbar = true,
  src,
}: CsvViewerPreviewProps) {
  const [workbookBuffer, setWorkbookBuffer] = React.useState<ArrayBuffer | null>(
    null,
  )
  const [loadError, setLoadError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false

    async function loadCsv() {
      setWorkbookBuffer(null)
      setLoadError(null)

      try {
        const response = await fetch(src, { credentials: "include" })
        if (!response.ok) {
          throw new Error(`Failed to fetch CSV (${response.status})`)
        }

        const text = await response.text()
        const workbook = XLSX.read(text, { type: "string" })
        const buffer = XLSX.write(workbook, { bookType: "xlsx", type: "array" })

        if (!cancelled) {
          setWorkbookBuffer(buffer)
        }
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error ? error.message : "Unable to load CSV preview",
          )
        }
      }
    }

    void loadCsv()

    return () => {
      cancelled = true
    }
  }, [src])

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-destructive">
        {loadError}
      </div>
    )
  }

  if (!workbookBuffer) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" />
      </div>
    )
  }

  const displayName = fileName?.replace(/\.csv$/i, ".xlsx") ?? "workbook.xlsx"

  return (
    <XlsxViewerPreview
      className={className}
      fileName={displayName}
      isDark={isDark}
      showToolbar={showToolbar}
      showUpload={false}
      workbookBuffer={workbookBuffer}
    />
  )
}
