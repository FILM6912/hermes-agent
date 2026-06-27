import { useState, useEffect } from "react";
import { clampPreviewWidth } from "../previewLayout";

export { clampPreviewWidth } from "../previewLayout";

export const useWindowResize = (
  initialWidth: number,
  isSidebarOpen: boolean,
) => {
  const [width, setWidth] = useState(() =>
    clampPreviewWidth(
      initialWidth,
      isSidebarOpen,
      typeof window !== "undefined" ? window.innerWidth : 1280,
    ),
  );
  const [isResizing, setIsResizing] = useState(false);

  const startResizing = (e: React.MouseEvent) => {
    setIsResizing(true);
    e.preventDefault();
  };

  const stopResizing = () => {
    setIsResizing(false);
  };

  useEffect(() => {
    const handleViewportResize = () => {
      setWidth((current) =>
        clampPreviewWidth(current, isSidebarOpen, window.innerWidth),
      );
    };
    window.addEventListener("resize", handleViewportResize);
    handleViewportResize();
    return () => window.removeEventListener("resize", handleViewportResize);
  }, [isSidebarOpen]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const rawWidth = window.innerWidth - e.clientX;
      setWidth(clampPreviewWidth(rawWidth, isSidebarOpen, window.innerWidth));
    };

    if (isResizing) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", stopResizing);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
    } else {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    }

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", stopResizing);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
  }, [isResizing, isSidebarOpen]);

  return { width, isResizing, startResizing };
};
