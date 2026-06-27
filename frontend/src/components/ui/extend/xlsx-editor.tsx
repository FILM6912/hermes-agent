"use client"

import type * as React from "react"

import { XlsxViewerPreview } from "@/components/ui/xlsx-viewer"

export type XlsxEditorPreviewProps = React.ComponentProps<typeof XlsxViewerPreview>

/** Experimental Excel editor — enables @extend-ai/react-xlsx mutations. */
export function XlsxEditorPreview(props: XlsxEditorPreviewProps) {
  return <XlsxViewerPreview {...props} readOnly={false} />
}
