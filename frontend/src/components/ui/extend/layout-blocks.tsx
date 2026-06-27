"use client"

import { cn } from "@/lib/utils"
import type { PDFViewerPageOverlayProps } from "@/components/ui/pdf-viewer"

export type LayoutBlock = {
  id: string
  kind: "text" | "line" | "word"
  text: string
  confidence?: number
  box: { top: number; left: number; width: number; height: number }
}

export type LayoutBlocksOverlayProps = {
  blocks: LayoutBlock[]
  selectedId?: string | null
  onSelect?: (id: string) => void
}

/**
 * Renders OCR/layout blocks as PDF page overlays (normalized 0–1 coordinates).
 */
export function renderLayoutBlocksOverlay({
  blocks,
  selectedId,
  onSelect,
}: LayoutBlocksOverlayProps) {
  return function LayoutBlocksPageOverlay({
    pageNumber,
    pageWidth,
    pageHeight,
  }: PDFViewerPageOverlayProps) {
    void pageNumber
    const pageBlocks = blocks

    return (
      <>
        {pageBlocks.map((block) => (
          <button
            key={block.id}
            type="button"
            title={`${block.text} (${Math.round((block.confidence ?? 1) * 100)}%)`}
            className={cn(
              "absolute border text-left text-[10px] leading-none",
              selectedId === block.id
                ? "border-primary bg-primary/20"
                : "border-amber-500/70 bg-amber-400/20",
            )}
            style={{
              top: block.box.top * pageHeight,
              left: block.box.left * pageWidth,
              width: block.box.width * pageWidth,
              height: block.box.height * pageHeight,
            }}
            onClick={() => onSelect?.(block.id)}
          />
        ))}
      </>
    )
  }
}

export type LayoutBlocksPanelProps = LayoutBlocksOverlayProps & {
  className?: string
}

/** Stub list panel paired with PDF overlay renderers. */
export function LayoutBlocksPanel({
  className,
  blocks,
  selectedId,
  onSelect,
}: LayoutBlocksPanelProps) {
  return (
    <div
      data-testid="extend-layout-blocks"
      className={cn("flex min-h-0 flex-col gap-2 overflow-auto", className)}
    >
      <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Experimental — inspect layout blocks overlaid on PDF pages.
      </div>
      <ul className="space-y-1 text-sm">
        {blocks.map((block) => (
          <li key={block.id}>
            <button
              type="button"
              className={cn(
                "w-full rounded-md border px-2 py-1 text-left",
                selectedId === block.id && "border-primary bg-primary/5",
              )}
              onClick={() => onSelect?.(block.id)}
            >
              <span className="text-xs uppercase text-muted-foreground">
                {block.kind}
              </span>
              <div className="truncate">{block.text}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
