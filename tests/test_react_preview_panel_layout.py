"""Layout contract: Generated Files (PreviewWindow) must stay in flex flow and not overlay chat or nav rail."""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_chat_and_preview_share_flex_row_inside_main_column():
    """Preview must not be a root flex sibling of the whole chat column (causes overlap + z-stacking)."""
    src = read("frontend/src/App.tsx")
    assert re.search(
        r'className="flex min-h-0 min-w-0 flex-1 flex-row overflow-hidden"',
        src,
    ), "chat view should wrap chat + preview in a horizontal flex row with min-w-0"
    chat_row = src.index('className="flex min-h-0 min-w-0 flex-1 flex-row overflow-hidden"')
    preview_marker = src.index("<PreviewWindow", chat_row)
    assert src.index('key="chat"', chat_row) < preview_marker < chat_row + 4000, (
        "PreviewWindow should sit beside the chat column inside the same flex row"
    )
    delete_dialog = src.index("{/* Delete Confirmation Dialog */}")
    assert preview_marker < delete_dialog, (
        "PreviewWindow must stay inside the main column, not as a root sibling after flex-1"
    )


def test_preview_shell_wrapper_does_not_stack_over_sidebar():
    src = read("frontend/src/App.tsx")
    wrapper = re.search(
        r'<div className="([^"]*)"[^>]*>\s*\n\s*<PreviewWindow',
        src,
    )
    assert wrapper, "PreviewWindow wrapper div not found"
    classes = wrapper.group(1)
    assert "z-40" not in classes and "z-50" not in classes, (
        "preview shell wrapper must not use high z-index that paints over the left nav rail"
    )
    assert "min-w-0" in classes and "overflow-hidden" in classes


def test_preview_desktop_panel_uses_flex_flow_not_viewport_overlay():
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    match = re.search(r"const desktopClasses = `([^`]+)`", src)
    assert match, "desktopClasses template missing"
    desktop = match.group(1)
    assert "fixed" not in desktop and "absolute inset" not in desktop, (
        "desktop preview panel must stay in document flex flow (no fixed/inset overlay)"
    )
    assert "min-w-0" in desktop and "overflow-hidden" in desktop
    assert "shrink" in desktop or "flex-shrink" in desktop


def test_preview_drawer_mounts_on_document_body_like_left_sidebar():
    """Narrow viewports slide in a right drawer (w-72), not a full-screen inset-0 sheet."""
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    assert "createPortal(panel, document.body)" in src, (
        "overlay preview must portal to document.body so fixed drawer is viewport-relative"
    )
    match = re.search(r"const mobileClasses = `([^`]+)`", src)
    assert match, "mobileClasses template missing"
    mobile = match.group(1)
    assert "fixed inset-y-0 right-0" in mobile
    assert "w-72" in mobile
    assert "z-50" in mobile
    assert "inset-0" not in mobile


def test_preview_drawer_has_matching_backdrop_in_app_layout():
    src = read("frontend/src/App.tsx")
    assert "Narrow-viewport files panel backdrop" in src
    assert "(isMobile || isPreviewOverlay) && isPreviewOpen" in src
    assert "setIsPreviewOpen(false)" in src


def test_responsive_preview_state_initializes_from_viewport():
    """First paint must not assume desktop docked preview on narrow windows."""
    src = read("frontend/src/App.tsx")
    assert re.search(
        r"const \[isPreviewOverlay, setIsPreviewOverlay\] = useState\(\(\) =>",
        src,
    ), "isPreviewOverlay should lazy-init from window.innerWidth"
    assert re.search(
        r"const \[isMobile, setIsMobile\] = useState\(\(\) =>",
        src,
    ), "isMobile should lazy-init from window.innerWidth"


def test_preview_layout_module_exports_overlay_breakpoint():
    src = read("frontend/src/features/preview/previewLayout.ts")
    assert "PREVIEW_OVERLAY_BREAKPOINT = 1280" in src
    assert "shouldUsePreviewOverlay" in src
    assert "shouldDockPreviewPanel" in src


def test_preview_width_clamp_fits_chat_column_when_viewport_is_tight():
    """Mirror previewLayout.ts clamp — shrink below MIN_PREVIEW_W rather than forcing overlap."""
    layout = read("frontend/src/features/preview/previewLayout.ts")
    assert "MIN_PREVIEW_W = 300" in layout
    assert "MIN_CHAT_W = 380" in layout
    assert "MIN_PREVIEW_USABLE_W = 200" in layout

    MIN_PREVIEW_W = 300
    MIN_CHAT_W = 380
    MIN_PREVIEW_USABLE_W = 200

    def clamp(desired: int, sidebar_open: bool, viewport: int) -> int:
        sidebar_w = 256 if sidebar_open else 50
        max_allowed = viewport - sidebar_w - MIN_CHAT_W
        if max_allowed <= 0 or max_allowed < MIN_PREVIEW_USABLE_W:
            return 0
        if max_allowed < MIN_PREVIEW_W:
            return max_allowed
        return min(max(desired, MIN_PREVIEW_W), max_allowed)

    assert clamp(450, sidebar_open=False, viewport=700) == 270
    assert clamp(450, sidebar_open=True, viewport=700) == 0


def test_preview_mobile_drawer_uses_opaque_shell_background():
    src = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    match = re.search(r"const mobileClasses = `([^`]+)`", src)
    assert match, "mobileClasses template missing"
    mobile = match.group(1)
    assert "bg-background" not in mobile, (
        "drawer preview must not use bg-background (renders transparent over chat)"
    )
    assert "bg-white" in mobile and "dark:bg-black" in mobile


def test_preview_drawer_stays_mounted_for_slide_animation():
    """Overlay drawer must stay mounted when closed so translate-x can animate like the left sidebar."""
    preview = read("frontend/src/features/preview/components/PreviewWindow.tsx")
    sidebar = read("frontend/src/features/sidebar/components/Sidebar.tsx")
    assert "if (!isOpen) {" not in preview or "return null" not in preview.split("const panel = (")[0], (
        "PreviewWindow must not early-return null before render — that skips the close slide"
    )
    preview_mobile = re.search(r"const mobileClasses = `([^`]+)`", preview)
    sidebar_mobile = re.search(r"const mobileClasses = `([^`]+)`", sidebar)
    assert preview_mobile and sidebar_mobile
    assert "transition-transform duration-300" in preview_mobile.group(1)
    assert "ease-[cubic-bezier(0.32,0.72,0,1)]" in preview_mobile.group(1)
    assert "translate-x-full" in preview_mobile.group(1)
    assert "transition-transform duration-300" in sidebar_mobile.group(1)


def test_preview_overlay_below_1280_not_docked():
    """Below 1280px the files panel must not stay docked beside chat."""
    layout = read("frontend/src/features/preview/previewLayout.ts")

    def should_use_preview_overlay(viewport: int) -> bool:
        return viewport < 1280

    def should_dock(viewport: int, sidebar_open: bool, desired: int = 450) -> bool:
        if should_use_preview_overlay(viewport):
            return False
        sidebar_w = 256 if sidebar_open else 50
        max_allowed = viewport - sidebar_w - 380
        if max_allowed <= 0 or max_allowed < 200:
            return False
        return True

    assert should_use_preview_overlay(1279) is True
    assert should_use_preview_overlay(1280) is False
    assert should_dock(1279, sidebar_open=True) is False
    assert should_dock(1280, sidebar_open=True) is True
