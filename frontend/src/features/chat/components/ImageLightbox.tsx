import React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { AttachmentImage } from "./AttachmentImage";

export type ImagePreviewSource = string | string[];

function normalizePreviewUrls(source: ImagePreviewSource | null): string[] {
  if (!source) return [];
  return (Array.isArray(source) ? source : [source]).filter(Boolean);
}

interface ImageLightboxProps {
  imageUrl: ImagePreviewSource | null;
  onClose: () => void;
}

export const ImageLightbox: React.FC<ImageLightboxProps> = ({
  imageUrl,
  onClose,
}) => {
  const urls = normalizePreviewUrls(imageUrl);
  if (!urls.length) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-100 bg-black/90 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 p-2 text-zinc-400 hover:text-white bg-zinc-800/50 hover:bg-zinc-800 rounded-full transition-colors"
        onClick={onClose}
      >
        <X className="w-6 h-6" />
      </button>
      <div onClick={(e) => e.stopPropagation()}>
        <AttachmentImage
          urls={urls}
          alt="Full size preview"
          className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl animate-in zoom-in-95 duration-300"
        />
      </div>
    </div>,
    document.body,
  );
};
