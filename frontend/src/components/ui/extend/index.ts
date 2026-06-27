/**
 * Extend UI document components — barrel aligned with
 * https://ui.extend.ai/ui/docs/components
 */

export { PDFViewer } from "@/components/ui/pdf-viewer"
export type {
  PDFViewerHandle,
  PDFViewerPageOverlayProps,
  PDFViewerProps,
} from "@/components/ui/pdf-viewer"

export { DocxViewerPreview } from "@/components/ui/docx-viewer"
export { DocxEditorPreview } from "./docx-editor"
export type { DocxEditorPreviewProps } from "./docx-editor"

export { XlsxViewerPreview } from "@/components/ui/xlsx-viewer"
export { XlsxEditorPreview } from "./xlsx-editor"
export type { XlsxEditorPreviewProps } from "./xlsx-editor"

export { CsvViewerPreview } from "./csv-viewer"

export { ExtendFileUpload } from "./file-upload"
export type {
  ExtendFileUploadItem,
  ExtendFileUploadProps,
} from "./file-upload"
export {
  buildAcceptAttribute,
  validateExtendUploadFile,
} from "./file-upload-validation"
export type {
  ExtendUploadValidationOptions,
  ExtendUploadValidationResult,
} from "./file-upload-validation"

export {
  FileSystem,
  type FileSystemFileItem,
  type FileSystemFolderItem,
  type FileSystemItem,
  type FileSystemLoadChildrenArgs,
  type FileSystemView,
} from "@/components/ui/file-system"

export {
  BoundingBoxCitations,
  type BoundingBoxCitation,
  type BoundingBoxCitationsProps,
} from "./bounding-box-citations"

export {
  SchemaBuilder,
  type SchemaBuilderField,
  type SchemaBuilderProps,
} from "./schema-builder"

export {
  FileThumbnail,
  FileThumbnailLoadingOverlay,
  type FileThumbnailProps,
  type ThumbnailFile,
} from "@/components/ui/file-thumbnail"

export {
  LayoutBlocksPanel,
  renderLayoutBlocksOverlay,
  type LayoutBlock,
  type LayoutBlocksOverlayProps,
  type LayoutBlocksPanelProps,
} from "./layout-blocks"

export {
  ESignaturePanel,
  renderESignatureOverlay,
  type ESignatureOverlayProps,
  type ESignaturePanelProps,
  type SignatureField,
} from "./e-signature"

export {
  DocumentSplits,
  type DocumentSplitGroup,
  type DocumentSplitsProps,
} from "./document-splits"

export {
  DocumentViewerSidebarSkeleton,
  DocumentViewerThumbnailSidebar,
  useElementWidth,
  useInlineThumbnailSidebar,
} from "@/components/ui/document-viewer-sidebar"

export {
  EXTEND_UI_COMPONENT_IDS,
  extendComponentCatalog,
  getExtendComponentEntry,
  type ExtendComponentEntry,
  type ExtendComponentId,
  type ExtendComponentStatus,
} from "./extend-catalog"

export {
  extendViewerModuleIdForFileName,
  isExtendDocumentPreviewType,
  type ExtendViewerModuleId,
} from "./extendDocumentRouting"
