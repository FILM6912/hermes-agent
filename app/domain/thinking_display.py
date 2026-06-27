"""Parity with frontend thinkingDisplay.ts — when to show reasoning vs answer."""

from __future__ import annotations

import re

_PLACEHOLDER_THINKING = frozenset(
    {
        "thinking",
        "thinking…",
        "thinking...",
        "กำลังคิด",
        "กำลังคิด...",
    }
)


def _normalize_thinking_compare(text: str) -> str:
    s = str(text or "").replace("\r\n", "\n")
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"[#*_`>]", "", s)
    return " ".join(s.split()).strip().lower()


def reasoning_is_distinct_from_content(reasoning: object, content: object) -> bool:
    """True when *reasoning* is non-empty and not a duplicate of visible *content*."""
    t = _normalize_thinking_compare(str(reasoning or ""))
    if not t or t in _PLACEHOLDER_THINKING:
        return False
    a = _normalize_thinking_compare(str(content or ""))
    if not a:
        return True
    if t == a:
        return False
    # Answer continues reasoning verbatim (leaked into the visible bubble).
    if a.startswith(t):
        return False
    # Reasoning may open with the same intro as the answer but continue with
    # a longer plan — keep that trace visible (#852 follow-up).
    if t.startswith(a):
        remainder = t[len(a) :].strip()
        if len(remainder) >= 80:
            return True
        return False
    shorter = min(len(t), len(a))
    longer = max(len(t), len(a))
    if shorter == 0:
        return False
    if t in a or a in t:
        if shorter / longer >= 0.82:
            return False
    return True
