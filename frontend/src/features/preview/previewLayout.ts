export const PREVIEW_OVERLAY_BREAKPOINT = 1280;
export const MOBILE_BREAKPOINT = 1024;

export const MIN_PREVIEW_W = 300;
export const MIN_PREVIEW_USABLE_W = 200;
export const MIN_CHAT_W = 380;
export const SIDEBAR_EXPANDED_W = 256;
export const SIDEBAR_COLLAPSED_W = 50;

/** Full-screen files panel below this width (see CHANGELOG responsive layout). */
export const shouldUsePreviewOverlay = (viewportWidth: number): boolean =>
  viewportWidth < PREVIEW_OVERLAY_BREAKPOINT;

export const isMobileViewport = (viewportWidth: number): boolean =>
  viewportWidth < MOBILE_BREAKPOINT;

export const clampPreviewWidth = (
  desiredWidth: number,
  isSidebarOpen: boolean,
  viewportWidth: number,
): number => {
  const sidebarW = isSidebarOpen ? SIDEBAR_EXPANDED_W : SIDEBAR_COLLAPSED_W;
  const maxAllowedWidth = viewportWidth - sidebarW - MIN_CHAT_W;
  if (maxAllowedWidth <= 0 || maxAllowedWidth < MIN_PREVIEW_USABLE_W) {
    return 0;
  }
  if (maxAllowedWidth < MIN_PREVIEW_W) {
    return maxAllowedWidth;
  }
  return Math.min(Math.max(desiredWidth, MIN_PREVIEW_W), maxAllowedWidth);
};

/** Dock beside chat only when viewport is wide enough and clamp leaves usable width. */
export const shouldDockPreviewPanel = (
  viewportWidth: number,
  isSidebarOpen: boolean,
  desiredWidth: number,
): boolean => {
  if (shouldUsePreviewOverlay(viewportWidth)) {
    return false;
  }
  return clampPreviewWidth(desiredWidth, isSidebarOpen, viewportWidth) > 0;
};
