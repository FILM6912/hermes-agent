"use client"

import * as React from "react"
import {
  FileSystem,
  type FileSystemItem,
  type FileSystemLoadChildrenArgs,
} from "@/components/ui/file-system"
import { mapHermesEntriesToFileSystemItems } from "@/features/preview/utils/hermesFileSystemItems"
import { listDirectory, fileRawUrl } from "@/services/hermes/workspace"

interface ShellFilesPanelProps {
  onBack?: () => void
  workspacePath?: string
}

export function ShellFilesPanel({ onBack, workspacePath }: ShellFilesPanelProps) {
  const [items, setItems] = React.useState<FileSystemItem[]>([])
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    if (!workspacePath) {
      setLoading(false)
      return
    }

    let cancelled = false

    async function loadFiles() {
      setLoading(true)
      try {
        const data = await listDirectory({
          workspace: workspacePath,
          path: ".",
        })
        if (cancelled) return
        setItems(mapHermesEntriesToFileSystemItems(data.entries))
      } catch (err) {
        console.error("Failed to load files:", err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadFiles()
    return () => {
      cancelled = true
    }
  }, [workspacePath])

  const getFileUrl = React.useCallback(
    (file: { path: string }) => {
      if (!workspacePath) {
        throw new Error("No workspace selected")
      }
      return fileRawUrl(undefined, file.path, {
        workspace: workspacePath,
        inline: true,
      })
    },
    [workspacePath]
  )

  const loadChildren = React.useCallback(
    async ({ path }: FileSystemLoadChildrenArgs) => {
      if (!workspacePath) {
        return { items: [] as FileSystemItem[] }
      }
      const data = await listDirectory({
        workspace: workspacePath,
        path,
      })
      return { items: mapHermesEntriesToFileSystemItems(data.entries) }
    },
    [workspacePath]
  )

  if (!workspacePath) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Select a workspace to browse files.
        </p>
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Back to chat
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col p-4">
      {loading ? (
        <div className="flex h-full items-center justify-center">
          <div className="text-sm text-muted-foreground animate-pulse">
            Loading files...
          </div>
        </div>
      ) : (
        <FileSystem
          items={items}
          title="Workspace Files"
          defaultView="list"
          getFileUrl={getFileUrl}
          loadChildren={loadChildren}
          className="h-full min-h-0 flex-1"
        />
      )}
    </div>
  )
}
