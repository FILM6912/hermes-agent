import { useState, useEffect, useCallback, RefObject } from "react";

interface Size {
  width: number | undefined;
  height: number | undefined;
}

export function useResizeObserver<T extends HTMLElement>(
  ref: RefObject<T | null>
): Size {
  const [size, setSize] = useState<Size>({
    width: undefined,
    height: undefined,
  });

  const handleResize = useCallback((entries: ResizeObserverEntry[]) => {
    for (const entry of entries) {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    }
  }, []);

  useEffect(() => {
    if (!ref.current) return;

    const observer = new ResizeObserver(handleResize);
    observer.observe(ref.current);

    return () => {
      observer.disconnect();
    };
  }, [ref, handleResize]);

  return size;
}
