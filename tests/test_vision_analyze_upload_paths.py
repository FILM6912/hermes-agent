"""vision_analyze must resolve virtual /workspace/.uploads paths to on-disk files."""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

import app.domain.profiles as profiles_mod
import app.domain.upload as upload_mod
import app.domain.workspace as workspace_mod
from app.domain.upload import (
    WORKSPACE_UPLOADS_SUBDIR,
    resolve_agent_attachment_path,
    strip_image_paths_from_attached_files_marker,
)


def _bind_admin_workspace(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[pathlib.Path, pathlib.Path]:
    hermes_home = tmp_path / ".hermes"
    account_root = hermes_home / "workspace" / "admin"
    account_root.mkdir(parents=True)
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_BASE_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(account_root))
    monkeypatch.setenv("TERMINAL_CWD", str(account_root))
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    profiles_mod._DEFAULT_HERMES_HOME = hermes_home
    workspace_mod.clear_request_user_access(workspace_mod.set_request_user_access(None))
    return hermes_home, account_root


def test_resolve_agent_attachment_path_maps_virtual_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, account_root = _bind_admin_workspace(tmp_path, monkeypatch)
    uploads = account_root / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir()
    image = uploads / "2026-05-21-1.jpg"
    image.write_bytes(b"\xff\xd8\xff\xd8fake-jpeg")

    resolved = resolve_agent_attachment_path("/workspace/.uploads/2026-05-21-1.jpg")
    assert resolved == str(image.resolve())
    assert pathlib.Path(resolved).is_file()


def test_resolve_agent_attachment_path_maps_workspace_rel(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, account_root = _bind_admin_workspace(tmp_path, monkeypatch)
    uploads = account_root / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir()
    image = uploads / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    resolved = resolve_agent_attachment_path(f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png")
    assert resolved == str(image.resolve())


def test_strip_image_paths_from_attached_files_marker_keeps_documents() -> None:
    message = "analyze\n\n@report.xlsx @photo.png"
    attachments = [
        {
            "name": "photo.png",
            "path": "/tmp/ws/.uploads/photo.png",
            "workspace_rel": f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png",
            "mime": "image/png",
            "is_image": True,
        },
        {
            "name": "report.xlsx",
            "workspace_rel": f"{WORKSPACE_UPLOADS_SUBDIR}/report.xlsx",
        },
    ]
    rewritten = strip_image_paths_from_attached_files_marker(message, attachments)
    assert "photo.png" not in rewritten
    assert "report.xlsx" in rewritten


def test_strip_image_paths_from_attached_files_marker_removes_suffix_for_images_only() -> None:
    message = "look\n\n@photo.png"
    attachments = [{
        "name": "photo.png",
        "workspace_rel": f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png",
        "mime": "image/jpeg",
        "is_image": True,
    }]
    rewritten = strip_image_paths_from_attached_files_marker(message, attachments)
    assert rewritten == "look"


def test_patch_vision_virtual_path_rewrite_maps_image_url(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _hermes_home, account_root = _bind_admin_workspace(tmp_path, monkeypatch)
    uploads = account_root / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir()
    image = uploads / "2026-05-21-1.jpg"
    image.write_bytes(b"\xff\xd8\xff\xd8fake-jpeg")
    calls: list[str] = []

    class FakeVisionToolsModule:
        @staticmethod
        async def vision_analyze_tool(image_url: str, user_prompt: str, model: str | None = None) -> str:
            calls.append(image_url)
            return "ok"

    sys.modules["tools.vision_tools"] = FakeVisionToolsModule()
    profiles_mod.patch_vision_virtual_path_rewrite()

    from tools.vision_tools import vision_analyze_tool

    asyncio.run(
        vision_analyze_tool(
            "/workspace/.uploads/2026-05-21-1.jpg",
            "describe",
        )
    )
    assert calls == [str(image.resolve())]
