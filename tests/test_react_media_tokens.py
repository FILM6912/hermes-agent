"""React assistant markdown should not leak raw MEDIA: tokens."""

from pathlib import Path


def test_media_tokens_utility_strips_prefix_and_paths():
    src = Path("frontend/src/features/chat/utils/mediaTokens.ts").read_text(
        encoding="utf-8",
    )
    assert "MEDIA_ONLY_LINE_RE" in src
    assert "stripMediaTokens" in src
    assert "📎" in src

    message_item = Path(
        "frontend/src/features/chat/components/MessageItem.tsx",
    ).read_text(encoding="utf-8")
    assert "stripMediaTokens" in message_item
    assert "prepareAssistantMarkdown" in message_item
