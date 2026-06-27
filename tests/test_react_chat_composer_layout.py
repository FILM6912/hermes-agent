"""Regression: single-line composer text aligns with footer icons."""

from pathlib import Path


def test_chat_input_single_line_composer_vertically_centers_controls():
    src = Path("frontend/src/features/chat/components/ChatInput.tsx").read_text(
        encoding="utf-8"
    )
    assert 'flex-wrap items-center gap-x-1 gap-y-1' in src
    assert "flex flex-1 items-center" in src
    assert "min-h-[56px] py-3.5 leading-relaxed px-4 box-border" in src
    assert "bottom-[calc(1rem+env(safe-area-inset-bottom,0px))]" in src
