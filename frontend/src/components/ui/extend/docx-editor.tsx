"use client"

import type * as React from "react"

import { DocxViewerPreview } from "@/components/ui/docx-viewer"

export type DocxEditorPreviewProps = React.ComponentProps<typeof DocxViewerPreview>

/** Experimental DOCX editor — enables @extend-ai/react-docx edit mode. */
export function DocxEditorPreview(props: DocxEditorPreviewProps) {
  return <DocxViewerPreview {...props} editorMode="edit" />
}
