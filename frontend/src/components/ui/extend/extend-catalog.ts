export type ExtendComponentStatus = "implemented" | "stub"

export type ExtendComponentEntry = {
  id: ExtendComponentId
  label: string
  status: ExtendComponentStatus
  description: string
}

export const EXTEND_UI_COMPONENT_IDS = [
  "pdf-viewer",
  "docx-viewer",
  "docx-editor",
  "xlsx-viewer",
  "xlsx-editor",
  "csv-viewer",
  "file-upload",
  "file-system",
  "bounding-box-citations",
  "schema-builder",
  "file-thumbnail",
  "layout-blocks",
  "e-signature",
  "document-splits",
  "document-viewer-sidebar",
] as const

export type ExtendComponentId = (typeof EXTEND_UI_COMPONENT_IDS)[number]

export const extendComponentCatalog: readonly ExtendComponentEntry[] = [
  {
    id: "pdf-viewer",
    label: "PDF Viewer",
    status: "implemented",
    description: "Page controls, zoom, search, thumbnails, and overlays.",
  },
  {
    id: "docx-viewer",
    label: "DOCX Viewer",
    status: "implemented",
    description: "Read-only Word document preview with thumbnails and themes.",
  },
  {
    id: "docx-editor",
    label: "DOCX Editor",
    status: "implemented",
    description: "Experimental Word-style editing via @extend-ai/react-docx.",
  },
  {
    id: "xlsx-viewer",
    label: "Excel Viewer",
    status: "implemented",
    description: "Read-only XLSX workbook preview with sheet tabs.",
  },
  {
    id: "xlsx-editor",
    label: "Excel Editor",
    status: "implemented",
    description: "Experimental editable workbook surface via @extend-ai/react-xlsx.",
  },
  {
    id: "csv-viewer",
    label: "CSV Viewer",
    status: "implemented",
    description: "Spreadsheet-like CSV preview via XLSX adapter.",
  },
  {
    id: "file-upload",
    label: "File Upload",
    status: "implemented",
    description: "Drag-and-drop upload wired to Hermes /api/v1/upload.",
  },
  {
    id: "file-system",
    label: "File System",
    status: "implemented",
    description: "Finder-style browser for workspace object manifests.",
  },
  {
    id: "bounding-box-citations",
    label: "Bounding Box Citations",
    status: "stub",
    description: "Review extracted values against source bounding boxes.",
  },
  {
    id: "schema-builder",
    label: "Schema Builder",
    status: "stub",
    description: "Table editor with synchronized JSON schema view.",
  },
  {
    id: "file-thumbnail",
    label: "File Thumbnail",
    status: "implemented",
    description: "Compact preview image with skeleton and fallback.",
  },
  {
    id: "layout-blocks",
    label: "Layout Blocks",
    status: "stub",
    description: "Inspect OCR layout blocks overlaid on PDF pages.",
  },
  {
    id: "e-signature",
    label: "E-Signature",
    status: "stub",
    description: "Place and review signature fields on PDF documents.",
  },
  {
    id: "document-splits",
    label: "Document Splits",
    status: "stub",
    description: "Group PDF pages into smaller documents.",
  },
  {
    id: "document-viewer-sidebar",
    label: "Document Viewer Sidebar",
    status: "implemented",
    description: "Shared thumbnail sidebar for document viewers.",
  },
]

export function getExtendComponentEntry(
  id: ExtendComponentId,
): ExtendComponentEntry | undefined {
  return extendComponentCatalog.find((entry) => entry.id === id)
}
