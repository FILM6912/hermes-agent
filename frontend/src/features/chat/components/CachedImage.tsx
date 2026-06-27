import React, { useState, useEffect } from "react";
import { Image as ImageIcon } from "lucide-react";
import { fetchBlob, normalizeApiPath } from "@/lib/api";

interface CachedImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string;
  fallbackSrcs?: string[];
}

function parseHermesApiSrc(src: string): { path: string; query: Record<string, string> } | null {
  const trimmed = src.trim();
  if (!trimmed.startsWith("/api")) return null;
  const qIndex = trimmed.indexOf("?");
  const pathPart = qIndex >= 0 ? trimmed.slice(0, qIndex) : trimmed;
  const queryPart = qIndex >= 0 ? trimmed.slice(qIndex + 1) : "";
  const query: Record<string, string> = {};
  if (queryPart) {
    for (const [key, value] of new URLSearchParams(queryPart)) {
      query[key] = value;
    }
  }
  return { path: normalizeApiPath(pathPart), query };
}

async function loadImageBlob(src: string): Promise<Blob> {
  const apiRequest = parseHermesApiSrc(src);
  if (apiRequest) {
    return fetchBlob(apiRequest.path, { query: apiRequest.query });
  }
  const response = await fetch(src, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.blob();
}

export const CachedImage: React.FC<CachedImageProps> = ({
  src,
  fallbackSrcs = [],
  alt,
  className,
  ...props
}) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    const candidates = [src, ...fallbackSrcs].filter(Boolean);

    const load = async () => {
      if (!candidates.length) return;
      setIsLoading(true);
      setHasError(false);

      for (const candidate of candidates) {
        try {
          const cacheName = "chat-media-v1";
          const cache = await caches.open(cacheName);
          const match = await cache.match(candidate);

          let blob: Blob;
          if (match) {
            blob = await match.blob();
          } else {
            blob = await loadImageBlob(candidate);
            await cache.put(candidate, new Response(blob.slice()));
          }

          objectUrl = URL.createObjectURL(blob);
          if (active) {
            setBlobUrl(objectUrl);
            setIsLoading(false);
            setHasError(false);
          }
          return;
        } catch (err) {
          console.warn("Failed to load chat image candidate:", candidate, err);
        }
      }

      if (active) {
        setHasError(true);
        setBlobUrl(null);
        setIsLoading(false);
      }
    };

    void load();

    return () => {
      active = false;
      if (objectUrl?.startsWith("blob:")) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [src, fallbackSrcs.join("|")]);

  if (isLoading) {
    return (
      <div
        className={`flex items-center justify-center bg-gray-100 dark:bg-zinc-800 animate-pulse ${className}`}
        style={{ minHeight: "100px", minWidth: "100px" }}
      >
        <ImageIcon className="w-6 h-6 text-gray-400" />
      </div>
    );
  }

  if (hasError || !blobUrl) {
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
      src={blobUrl}
      alt={alt}
      className={className}
      {...props}
      onError={() => setHasError(true)}
    />
  );
};
