import React, { useEffect, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { normalizePublicStorageUrls } from "@/lib/storageUrls";

interface AttachmentImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  urls: string[];
  /** Called when an image URL loads successfully (for lightbox handoff). */
  onResolvedUrl?: (url: string) => void;
}

/** Inline chat image — native `<img src>` with URL fallbacks (legacy parity). */
export const AttachmentImage: React.FC<AttachmentImageProps> = ({
  urls,
  alt,
  className,
  onResolvedUrl,
  onLoad,
  ...props
}) => {
  const candidates = normalizePublicStorageUrls(urls.filter(Boolean));
  const [index, setIndex] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setIndex(0);
    setFailed(false);
  }, [candidates.join("|")]);

  const src = candidates[index];

  if (!src || failed) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-1 bg-gray-100 dark:bg-zinc-800 text-zinc-500 ${className}`}
        style={{ minHeight: "100px", minWidth: "100px" }}
      >
        <ImageIcon className="w-6 h-6 text-gray-400" />
        {alt ? <span className="text-[10px] px-2 truncate max-w-[140px]">{alt}</span> : null}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading="lazy"
      {...props}
      onLoad={(event) => {
        const loaded =
          event.currentTarget.currentSrc || event.currentTarget.src || src;
        if (loaded) onResolvedUrl?.(loaded);
        onLoad?.(event);
      }}
      onError={() => {
        if (index + 1 < candidates.length) {
          setIndex((prev) => prev + 1);
          return;
        }
        setFailed(true);
      }}
    />
  );
};
