"""Extract displayable text from LangChain chat messages and stream chunks."""

from __future__ import annotations

from typing import Any


def _coerce_content_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                text = getattr(block, "text", None) or getattr(block, "content", None)
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(value)


def extract_langchain_message_text(message: Any) -> str:
    """
    Return user-visible text from an AIMessage / AIMessageChunk.

    Never falls back to ``repr(message)`` — empty stream chunks must be skipped,
    not serialized as ``content='' additional_kwargs=…``.
    """
    text = _coerce_content_value(getattr(message, "content", None)).strip()
    if text:
        return text

    kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(kwargs, dict):
        for key in ("reasoning_content", "reasoning", "text"):
            alt = _coerce_content_value(kwargs.get(key)).strip()
            if alt:
                return alt
    return ""
