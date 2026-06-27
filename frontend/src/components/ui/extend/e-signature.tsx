"use client"

import { cn } from "@/lib/utils"
import type { PDFViewerPageOverlayProps } from "@/components/ui/pdf-viewer"

export type SignatureField = {
  id: string
  label: string
  page: number
  signed?: boolean
  box: { top: number; left: number; width: number; height: number }
}

export type ESignatureOverlayProps = {
  fields: SignatureField[]
  activeFieldId?: string | null
  onFieldClick?: (id: string) => void
}

export function renderESignatureOverlay({
  fields,
  activeFieldId,
  onFieldClick,
}: ESignatureOverlayProps) {
  return function ESignaturePageOverlay({
    pageNumber,
    pageWidth,
    pageHeight,
  }: PDFViewerPageOverlayProps) {
    const pageFields = fields.filter((field) => field.page === pageNumber)

    return (
      <>
        {pageFields.map((field) => (
          <button
            key={field.id}
            type="button"
            className={cn(
              "absolute rounded border-2 border-dashed text-xs",
              field.signed
                ? "border-emerald-500 bg-emerald-500/10"
                : "border-sky-500 bg-sky-500/10",
              activeFieldId === field.id && "ring-2 ring-primary",
            )}
            style={{
              top: field.box.top * pageHeight,
              left: field.box.left * pageWidth,
              width: field.box.width * pageWidth,
              height: field.box.height * pageHeight,
            }}
            onClick={() => onFieldClick?.(field.id)}
          >
            {field.signed ? "Signed" : field.label}
          </button>
        ))}
      </>
    )
  }
}

export type ESignaturePanelProps = ESignatureOverlayProps & {
  className?: string
  onSign?: (id: string) => void
}

/** Stub panel for placing and completing signature fields on PDFs. */
export function ESignaturePanel({
  className,
  fields,
  activeFieldId,
  onFieldClick,
  onSign,
}: ESignaturePanelProps) {
  return (
    <div
      data-testid="extend-e-signature"
      className={cn("flex min-h-0 flex-col gap-2", className)}
    >
      <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Experimental — place and complete signature fields on PDF documents.
      </div>
      <ul className="space-y-2 text-sm">
        {fields.map((field) => (
          <li
            key={field.id}
            className={cn(
              "flex items-center justify-between rounded-md border px-3 py-2",
              activeFieldId === field.id && "border-primary",
            )}
          >
            <button type="button" onClick={() => onFieldClick?.(field.id)}>
              {field.label} (p.{field.page})
            </button>
            <button
              type="button"
              className="text-xs text-primary"
              disabled={field.signed}
              onClick={() => onSign?.(field.id)}
            >
              {field.signed ? "Done" : "Sign"}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
