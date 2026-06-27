import {
  viewerKindForFileName,
  type FileSystemViewerKind,
} from "@/features/preview/utils/fileSystemViewer"

/** Lazy-loaded module id used by ExtendDocumentPreview. */
export type ExtendViewerModuleId = Extract<
  FileSystemViewerKind,
  "csv" | "docx" | "pdf" | "xlsx"
>

export function extendViewerModuleIdForFileName(
  fileName: string,
): ExtendViewerModuleId | null {
  const kind = viewerKindForFileName(fileName)
  if (kind === "pdf" || kind === "docx" || kind === "xlsx" || kind === "csv") {
    return kind
  }
  return null
}

export function isExtendDocumentPreviewType(fileName: string): boolean {
  return extendViewerModuleIdForFileName(fileName) !== null
}
