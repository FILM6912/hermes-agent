"use client"

import * as React from "react"
import { Upload01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { cn } from "@/lib/utils"
import type { HermesUploadResponse } from "@/services/hermes/upload"
import { uploadFile } from "@/services/hermes/upload"

import {
  buildAcceptAttribute,
  validateExtendUploadFile,
  type ExtendUploadValidationOptions,
} from "./file-upload-validation"

export type ExtendFileUploadItem = {
  id: string
  file: File
  status: "queued" | "uploading" | "done" | "error"
  error?: string
  result?: HermesUploadResponse
}

export type ExtendFileUploadProps = {
  className?: string
  sessionId: string
  workspace?: string
  validation?: ExtendUploadValidationOptions
  onUploadComplete?: (item: ExtendFileUploadItem) => void
  onUploadError?: (item: ExtendFileUploadItem) => void
}

const DEFAULT_VALIDATION: ExtendUploadValidationOptions = {
  maxBytes: 20 * 1024 * 1024,
  accept: [".pdf", ".docx", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg"],
}

export function ExtendFileUpload({
  className,
  sessionId,
  workspace,
  validation = DEFAULT_VALIDATION,
  onUploadComplete,
  onUploadError,
}: ExtendFileUploadProps) {
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [items, setItems] = React.useState<ExtendFileUploadItem[]>([])
  const [isDragging, setIsDragging] = React.useState(false)

  const enqueueFiles = React.useCallback(
    (files: FileList | File[]) => {
      const nextItems: ExtendFileUploadItem[] = []

      for (const file of Array.from(files)) {
        const validationResult = validateExtendUploadFile(file, validation)
        if (!validationResult.ok) {
          const reason =
            validationResult.reason === "size"
              ? "File exceeds size limit"
              : "Unsupported file type"
          const rejected: ExtendFileUploadItem = {
            id: `${file.name}-${file.size}-${file.lastModified}`,
            file,
            status: "error",
            error: reason,
          }
          nextItems.push(rejected)
          onUploadError?.(rejected)
          continue
        }

        nextItems.push({
          id: `${file.name}-${file.size}-${file.lastModified}`,
          file,
          status: "queued",
        })
      }

      if (nextItems.length === 0) return
      setItems((current) => [...current, ...nextItems])
    },
    [onUploadError, validation],
  )

  React.useEffect(() => {
    const queued = items.filter((item) => item.status === "queued")
    if (queued.length === 0) return

    let cancelled = false

    async function runUploads() {
      for (const item of queued) {
        setItems((current) =>
          current.map((entry) =>
            entry.id === item.id ? { ...entry, status: "uploading" } : entry,
          ),
        )

        try {
          const result = await uploadFile(sessionId, item.file, { workspace })
          if (cancelled) return

          const completed: ExtendFileUploadItem = {
            ...item,
            status: "done",
            result,
          }
          setItems((current) =>
            current.map((entry) => (entry.id === item.id ? completed : entry)),
          )
          onUploadComplete?.(completed)
        } catch (error) {
          if (cancelled) return
          const failed: ExtendFileUploadItem = {
            ...item,
            status: "error",
            error:
              error instanceof Error ? error.message : "Upload failed",
          }
          setItems((current) =>
            current.map((entry) => (entry.id === item.id ? failed : entry)),
          )
          onUploadError?.(failed)
        }
      }
    }

    void runUploads()
    return () => {
      cancelled = true
    }
  }, [items, onUploadComplete, onUploadError, sessionId, workspace])

  return (
    <div
      data-testid="extend-file-upload"
      className={cn(
        "rounded-lg border border-dashed bg-muted/20 p-4",
        isDragging && "border-primary bg-primary/5",
        className,
      )}
      onDragEnter={(event) => {
        event.preventDefault()
        setIsDragging(true)
      }}
      onDragOver={(event) => {
        event.preventDefault()
        setIsDragging(true)
      }}
      onDragLeave={(event) => {
        event.preventDefault()
        setIsDragging(false)
      }}
      onDrop={(event) => {
        event.preventDefault()
        setIsDragging(false)
        if (event.dataTransfer.files.length > 0) {
          enqueueFiles(event.dataTransfer.files)
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        accept={buildAcceptAttribute(validation.accept)}
        onChange={(event) => {
          if (event.target.files) {
            enqueueFiles(event.target.files)
          }
          event.target.value = ""
        }}
      />
      <div className="flex flex-col items-center gap-3 text-center">
        <HugeiconsIcon icon={Upload01Icon} className="size-8 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">Drop files to upload</p>
          <p className="text-xs text-muted-foreground">
            PDF, DOCX, XLSX, CSV, and images
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </Button>
      </div>
      {items.length > 0 ? (
        <ul className="mt-4 space-y-2 text-left text-sm">
          {items.map((item) => (
            <li
              key={item.id}
              className="flex items-center justify-between rounded-md border bg-background px-3 py-2"
            >
              <span className="truncate">{item.file.name}</span>
              <span className="ml-3 shrink-0 text-muted-foreground">
                {item.status === "uploading" ? (
                  <Spinner className="size-4" />
                ) : item.status === "done" ? (
                  "Uploaded"
                ) : item.status === "error" ? (
                  item.error ?? "Failed"
                ) : (
                  "Queued"
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
