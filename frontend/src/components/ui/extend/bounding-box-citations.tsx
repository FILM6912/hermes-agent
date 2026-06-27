"use client"

import { cn } from "@/lib/utils"

export type BoundingBoxCitation = {
  id: string
  label: string
  value: string
  page: number
  /** Normalized 0–1 coordinates relative to page width/height. */
  box: { top: number; left: number; width: number; height: number }
}

export type BoundingBoxCitationsProps = {
  className?: string
  citations: BoundingBoxCitation[]
  selectedId?: string | null
  onSelect?: (id: string) => void
  onValueChange?: (id: string, value: string) => void
}

/**
 * Stub shell for Extend Bounding Box Citations.
 * Wire OCR/extraction payloads when the backend contract is available.
 */
export function BoundingBoxCitations({
  className,
  citations,
  selectedId,
  onSelect,
  onValueChange,
}: BoundingBoxCitationsProps) {
  return (
    <div
      data-testid="extend-bounding-box-citations"
      className={cn("flex min-h-0 flex-col gap-3", className)}
    >
      <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Experimental — review extracted values against source bounding boxes.
      </div>
      <ul className="space-y-2 overflow-auto">
        {citations.map((citation) => (
          <li key={citation.id}>
            <button
              type="button"
              className={cn(
                "w-full rounded-md border px-3 py-2 text-left text-sm",
                selectedId === citation.id && "border-primary bg-primary/5",
              )}
              onClick={() => onSelect?.(citation.id)}
            >
              <div className="font-medium">{citation.label}</div>
              <input
                className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
                value={citation.value}
                onChange={(event) =>
                  onValueChange?.(citation.id, event.target.value)
                }
              />
              <div className="mt-1 text-xs text-muted-foreground">
                Page {citation.page}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
