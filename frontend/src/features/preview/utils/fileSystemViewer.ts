export type FileSystemViewerKind = "csv" | "docx" | "image" | "pdf" | "xlsx"

export type FileSystemViewerFile = {
  path: string
  name?: string
  contentType?: string
}

const IMAGE_EXTENSION_PATTERN = /\.(avif|gif|jpe?g|png|svg|webp)$/

export function viewerKindForFile(
  file: FileSystemViewerFile
): FileSystemViewerKind | null {
  if (file.contentType?.startsWith("image/")) return "image"
  if (file.contentType === "application/pdf") return "pdf"
  if (file.contentType === "text/csv") return "csv"

  const name = (file.name ?? file.path).toLowerCase()

  if (name.endsWith(".pdf")) return "pdf"
  if (name.endsWith(".docx")) return "docx"
  if (name.endsWith(".xlsx") || name.endsWith(".xls")) return "xlsx"
  if (name.endsWith(".csv")) return "csv"
  if (IMAGE_EXTENSION_PATTERN.test(name)) return "image"

  return null
}

/** File name or path only — for preview panel routing without a full path object. */
export function viewerKindForFileName(fileName: string): FileSystemViewerKind | null {
  return viewerKindForFile({ path: fileName, name: fileName })
}

/** Extensions that support rendered preview mode (not code-only). */
export const PREVIEWABLE_EXTENSIONS = new Set([
  "csv",
  "docx",
  "gif",
  "htm",
  "html",
  "jpeg",
  "jpg",
  "md",
  "markdown",
  "pdf",
  "png",
  "svg",
  "webp",
  "xls",
  "xlsx",
])

export function isPreviewableExtension(ext: string | undefined): boolean {
  if (!ext) return false
  return PREVIEWABLE_EXTENSIONS.has(ext.toLowerCase())
}

/** Office/binary documents served via /api/file/raw — skip UTF-8 text read. */
export const BINARY_RAW_PREVIEW_EXTENSIONS = new Set([
  "docx",
  "pdf",
  "ppt",
  "pptx",
  "xls",
  "xlsx",
])

export function shouldSkipTextContentLoad(ext: string | undefined): boolean {
  if (!ext) return false
  return BINARY_RAW_PREVIEW_EXTENSIONS.has(ext.toLowerCase())
}
