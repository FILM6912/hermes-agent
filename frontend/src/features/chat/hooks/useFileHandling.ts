import { useCallback, useMemo, useState } from "react";
import { Attachment } from "@/types";
import { uploadFile } from "@/services/hermes/upload";

type UseFileHandlingOptions = {
  sessionId?: string;
  /** Active composer workspace for `.uploads/` storage. */
  workspace?: string;
  /** Create or resolve a server session before upload (legacy: newSession on send). */
  ensureSessionId?: (options?: {
    navigate?: boolean;
    activate?: boolean;
  }) => Promise<string | undefined>;
};

type StagedFile = {
  file: File;
  previewUrl?: string;
};

function inferAttachmentType(file: File): Attachment["type"] {
  return file.type.startsWith("image/") ? "image" : "file";
}

function stagedAttachment(entry: StagedFile): Attachment {
  const type = inferAttachmentType(entry.file);
  return {
    name: entry.file.name,
    type,
    content: entry.previewUrl || "",
    previewUrl: entry.previewUrl,
    mimeType: entry.file.type || undefined,
    size: entry.file.size,
    pending: true,
  };
}

export const useFileHandling = (options: UseFileHandlingOptions = {}) => {
  const { sessionId, workspace, ensureSessionId } = options;
  const [uploadedAttachments, setUploadedAttachments] = useState<Attachment[]>([]);
  const [pendingFiles, setPendingFiles] = useState<StagedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const attachments = useMemo(
    () => [...uploadedAttachments, ...pendingFiles.map(stagedAttachment)],
    [uploadedAttachments, pendingFiles],
  );

  const uploadSingleFile = useCallback(
    async (file: File, sid: string): Promise<Attachment> => {
      const result = await uploadFile(sid, file, {
        workspace: workspace?.trim() || undefined,
      });
      const agentPath = result.workspace_rel?.trim() || result.path;
      const attachment: Attachment = {
        name: result.path.split(/[/\\]/).pop() || result.filename,
        type: result.is_image ? "image" : "file",
        content: agentPath,
        path: agentPath,
        mimeType: result.mime,
        size: result.size,
        ...(result.workspace_rel ? { workspace_rel: result.workspace_rel } : {}),
      };
      if (result.is_image) {
        attachment.previewUrl = URL.createObjectURL(file);
      }
      return attachment;
    },
    [workspace],
  );

  const resolveSessionForUpload = useCallback(async (): Promise<string | undefined> => {
    if (sessionId) return sessionId;
    if (!ensureSessionId) return undefined;
    return ensureSessionId({ navigate: false, activate: false });
  }, [ensureSessionId, sessionId]);

  const stagePendingFiles = useCallback((files: File[]) => {
    setPendingFiles((prev) => {
      const seen = new Set(
        prev.map((entry) => `${entry.file.name}:${entry.file.size}:${entry.file.lastModified}`),
      );
      const next = [...prev];
      for (const file of files) {
        const key = `${file.name}:${file.size}:${file.lastModified}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.push({
          file,
          previewUrl: file.type.startsWith("image/")
            ? URL.createObjectURL(file)
            : undefined,
        });
      }
      return next;
    });
  }, []);

  const processFiles = async (files: File[]) => {
    if (files.length === 0) return;
    setUploadError(null);

    const sid = await resolveSessionForUpload();
    if (!sid) {
      stagePendingFiles(files);
      return;
    }

    setIsUploading(true);
    const newAttachments: Attachment[] = [];
    try {
      for (const file of files) {
        newAttachments.push(await uploadSingleFile(file, sid));
      }
      setUploadedAttachments((prev) => [...prev, ...newAttachments]);
    } catch (err) {
      console.error("Failed to upload attachment", err);
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  /** Upload staged files and return all attachments with server paths (call before send). */
  const flushUploads = useCallback(
    async (sid: string): Promise<Attachment[]> => {
      if (!sid) return uploadedAttachments;

      setIsUploading(true);
      setUploadError(null);
      try {
        const uploaded: Attachment[] = [];
        for (const entry of pendingFiles) {
          uploaded.push(await uploadSingleFile(entry.file, sid));
        }

        let merged: Attachment[] = [];
        setUploadedAttachments((prev) => {
          merged = [...prev, ...uploaded];
          return merged;
        });
        setPendingFiles((prev) => {
          for (const entry of prev) {
            if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
          }
          return [];
        });
        return merged.length > 0 ? merged : uploadedAttachments;
      } catch (err) {
        console.error("Failed to upload pending attachments", err);
        setUploadError(err instanceof Error ? err.message : "Upload failed");
        throw err;
      } finally {
        setIsUploading(false);
      }
    },
    [pendingFiles, uploadSingleFile, uploadedAttachments],
  );

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      await processFiles(Array.from(e.target.files));
      e.target.value = "";
    }
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === "file") {
        const file = items[i].getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      await processFiles(files);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await processFiles(Array.from(e.dataTransfer.files));
    }
  };

  const removeAttachment = (index: number) => {
    const uploadedCount = uploadedAttachments.length;
    if (index < uploadedCount) {
      setUploadedAttachments((prev) => {
        const removed = prev[index];
        if (removed?.type === "image" && removed.content.startsWith("blob:")) {
          URL.revokeObjectURL(removed.content);
        }
        return prev.filter((_, i) => i !== index);
      });
      return;
    }

    const pendingIndex = index - uploadedCount;
    setPendingFiles((prev) => {
      const removed = prev[pendingIndex];
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((_, i) => i !== pendingIndex);
    });
  };

  const clearAttachments = () => {
    // Do not revoke uploaded blob previews — sent messages may still reference them.
    setUploadedAttachments([]);
    setPendingFiles((prev) => {
      for (const entry of prev) {
        if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
      }
      return [];
    });
  };

  return {
    attachments,
    isDragging,
    isUploading,
    uploadError,
    handleFileSelect,
    handlePaste,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    removeAttachment,
    clearAttachments,
    flushUploads,
  };
};
