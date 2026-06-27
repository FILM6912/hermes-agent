"""Display-layer @path stripping keeps agent-facing message text intact in storage."""

from app.domain.helpers import redact_session_data
from app.domain.streaming import (
    _remap_message_for_display,
    _remap_messages_for_display,
    prepare_session_dict_for_api_display,
)
from app.domain.upload import (
    WORKSPACE_UPLOADS_SUBDIR,
    strip_attachment_path_suffix,
    strip_attachment_paths_for_display,
)


def test_strip_attachment_path_suffix_trailing_tokens() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/photo.jpg"
    message = f"เห็นอะไร\n\n@{rel}"
    assert strip_attachment_path_suffix(message) == "เห็นอะไร"


def test_strip_attachment_paths_for_display_upload_only_inline() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/fp4_compare.png"
    message = f"I've uploaded 1 file(s): @{rel}"
    assert strip_attachment_paths_for_display(message) == ""


def test_strip_attachment_paths_for_display_inline_mention() -> None:
    message = "ดูไฟล์ @src/foo.ts หน่อย"
    assert strip_attachment_paths_for_display(message) == "ดูไฟล์ หน่อย"


def test_strip_attachment_paths_for_display_preserves_non_path_at_tokens() -> None:
    message = "ping @alice about @src/foo.ts"
    assert strip_attachment_paths_for_display(message) == "ping @alice about"


def test_strip_attachment_paths_for_display_legacy_upload_comma_paths() -> None:
    message = "I've uploaded 2 file(s): a.png, b.jpg"
    assert strip_attachment_paths_for_display(message) == ""


def test_remap_message_for_display_strips_user_at_paths() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/shot.png"
    raw = {"role": "user", "content": f"analyze this\n\n@{rel}"}
    remapped = _remap_message_for_display(raw)
    assert remapped is not None
    assert remapped["content"] == "analyze this"
    assert raw["content"] == f"analyze this\n\n@{rel}"


def test_remap_message_for_display_leaves_assistant_content() -> None:
    raw = {"role": "assistant", "content": "See @.uploads/foo.png in workspace"}
    remapped = _remap_message_for_display(raw)
    assert remapped is not None
    assert remapped["content"] == raw["content"]


def test_remap_messages_for_display_strips_user_rows_only() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/a.png"
    rows = [
        {"role": "user", "content": f"check\n\n@{rel}"},
        {"role": "assistant", "content": f"opened @{rel}"},
    ]
    remapped = _remap_messages_for_display(rows)
    assert remapped[0]["content"] == "check"
    assert remapped[1]["content"] == f"opened @{rel}"


def test_prepare_session_dict_for_api_display_strips_messages_and_pending() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/doc.pdf"
    raw = {
        "session_id": "abc",
        "messages": [{"role": "user", "content": f"read\n\n@{rel}"}],
        "pending_user_message": f"summarize\n\n@{rel}",
    }
    display = prepare_session_dict_for_api_display(raw)
    assert display["messages"][0]["content"] == "read"
    assert display["pending_user_message"] == "summarize"
    assert raw["messages"][0]["content"] == f"read\n\n@{rel}"
    assert raw["pending_user_message"] == f"summarize\n\n@{rel}"


def test_redact_session_data_strips_user_at_paths_for_api(monkeypatch) -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/chart.png"
    stored = {
        "session_id": "sess1",
        "title": "ok",
        "messages": [
            {
                "role": "user",
                "content": f"analyze\n\n@{rel}",
                "attachments": [{"name": "chart.png", "path": rel}],
            }
        ],
        "tool_calls": [],
    }
    monkeypatch.setattr(
        "app.domain.config.load_settings",
        lambda: {"api_redact_enabled": False},
    )
    api = redact_session_data(stored)
    assert api["messages"][0]["content"] == "analyze"
    assert api["messages"][0]["attachments"] == stored["messages"][0]["attachments"]
    assert stored["messages"][0]["content"] == f"analyze\n\n@{rel}"


def test_strip_attachment_paths_for_display_is_idempotent() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/x.jpg"
    once = strip_attachment_paths_for_display(f"hello\n\n@{rel}")
    twice = strip_attachment_paths_for_display(once)
    assert once == twice == "hello"
