export type ExtendUploadValidationResult =
  | { ok: true }
  | { ok: false; reason: "size" | "type" }

export type ExtendUploadValidationOptions = {
  maxBytes: number
  accept: string[]
}

function fileExtension(fileName: string): string {
  const dot = fileName.lastIndexOf(".")
  if (dot < 0) return ""
  return fileName.slice(dot).toLowerCase()
}

export function buildAcceptAttribute(accept: string[]): string {
  return accept.join(",")
}

export function validateExtendUploadFile(
  file: File,
  options: ExtendUploadValidationOptions,
): ExtendUploadValidationResult {
  if (file.size > options.maxBytes) {
    return { ok: false, reason: "size" }
  }

  const ext = fileExtension(file.name)
  const normalized = options.accept.map((token) => token.toLowerCase())
  if (!normalized.includes(ext)) {
    return { ok: false, reason: "type" }
  }

  return { ok: true }
}
