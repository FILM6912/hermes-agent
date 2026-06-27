"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

export type DocumentSplitGroup = {
  id: string
  title: string
  pageNumbers: number[]
}

export type DocumentSplitsProps = {
  className?: string
  totalPages: number
  groups: DocumentSplitGroup[]
  onGroupsChange?: (groups: DocumentSplitGroup[]) => void
}

/**
 * Stub shell for organizing long PDFs into smaller documents.
 */
export function DocumentSplits({
  className,
  totalPages,
  groups,
  onGroupsChange,
}: DocumentSplitsProps) {
  const assigned = React.useMemo(
    () => new Set(groups.flatMap((group) => group.pageNumbers)),
    [groups],
  )

  const unassigned = React.useMemo(
    () =>
      Array.from({ length: totalPages }, (_, index) => index + 1).filter(
        (page) => !assigned.has(page),
      ),
    [assigned, totalPages],
  )

  return (
    <div
      data-testid="extend-document-splits"
      className={cn("flex min-h-0 flex-col gap-3", className)}
    >
      <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Experimental — drag pages into split groups (API pending).
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {groups.map((group) => (
          <section key={group.id} className="rounded-md border p-3">
            <h3 className="text-sm font-medium">{group.title}</h3>
            <div className="mt-2 flex flex-wrap gap-1">
              {group.pageNumbers.map((page) => (
                <span
                  key={page}
                  className="rounded bg-muted px-2 py-0.5 text-xs"
                >
                  p.{page}
                </span>
              ))}
            </div>
          </section>
        ))}
      </div>
      {unassigned.length > 0 ? (
        <div className="rounded-md border border-dashed p-3 text-sm">
          <div className="mb-2 text-xs text-muted-foreground">Unassigned</div>
          <div className="flex flex-wrap gap-1">
            {unassigned.map((page) => (
              <button
                key={page}
                type="button"
                className="rounded bg-muted px-2 py-0.5 text-xs hover:bg-muted/80"
                onClick={() => {
                  if (groups.length === 0) return
                  onGroupsChange?.(
                    groups.map((group, index) =>
                      index === 0
                        ? {
                            ...group,
                            pageNumbers: [...group.pageNumbers, page].sort(
                              (a, b) => a - b,
                            ),
                          }
                        : group,
                    ),
                  )
                }}
              >
                p.{page}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
