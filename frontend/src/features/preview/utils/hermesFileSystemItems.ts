import type { FileSystemItem } from "@/components/ui/file-system"
import {
  isDirectoryEntry,
  type HermesDirEntry,
} from "@/services/hermes/workspace"

function folderPath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/^\.\//, "")
  return normalized.endsWith("/") ? normalized : `${normalized}/`
}

export function mapHermesEntryToFileSystemItem(
  entry: HermesDirEntry,
): FileSystemItem {
  if (isDirectoryEntry(entry)) {
    return {
      kind: "folder",
      path: folderPath(entry.path),
      name: entry.name,
      hasChildren: true,
      updatedAt:
        entry.mtime_ns != null
          ? new Date(entry.mtime_ns / 1_000_000).toISOString()
          : undefined,
    }
  }

  return {
    kind: "file",
    path: entry.path,
    name: entry.name,
    size: entry.size ?? undefined,
    updatedAt:
      entry.mtime_ns != null
        ? new Date(entry.mtime_ns / 1_000_000).toISOString()
        : undefined,
  }
}

export function mapHermesEntriesToFileSystemItems(
  entries: HermesDirEntry[],
): FileSystemItem[] {
  return [...entries]
    .sort((a, b) => {
      const aDir = isDirectoryEntry(a)
      const bDir = isDirectoryEntry(b)
      if (aDir !== bDir) return aDir ? -1 : 1
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    })
    .map(mapHermesEntryToFileSystemItem)
}
