"""Chat attachments land in workspace/.uploads for agent sandbox access."""
from __future__ import annotations

import pathlib

import pytest

from app.domain.upload import (
    WORKSPACE_UPLOADS_SUBDIR,
    build_attachment_agent_context,
    process_upload,
    stage_chat_attachments_to_workspace,
)


def _trust_any_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    def _resolve(path):
        return pathlib.Path(path).expanduser().resolve()

    monkeypatch.setattr(
        "app.domain.upload.resolve_trusted_workspace",
        _resolve,
    )
    monkeypatch.setattr(
        "app.domain.workspace.resolve_trusted_workspace",
        _resolve,
    )
    monkeypatch.setattr(
        "app.domain.workspace.resolve_main_user_workspace_root",
        lambda workspace=None, **kwargs: _resolve(workspace),
    )


def _stub_session(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, workspace: pathlib.Path) -> str:
    from app.domain.models import Session

    session_id = "sess-uploads-test"
    session = Session(session_id=session_id, workspace=str(workspace))
    monkeypatch.setattr(
        "app.domain.upload.get_session",
        lambda sid: session if sid == session_id else (_ for _ in ()).throw(KeyError(sid)),
    )
    _trust_any_workspace(monkeypatch)
    return session_id


def test_process_upload_stores_file_under_workspace_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace" / "admin"
    workspace.mkdir(parents=True)
    sid = _stub_session(tmp_path, monkeypatch, workspace)

    payload, status = process_upload(
        {"session_id": sid, "workspace": str(workspace)},
        {"file": ("report.xlsx", b"excel-bytes")},
    )

    assert status == 200
    uploaded = pathlib.Path(payload["path"])
    assert uploaded.exists()
    assert uploaded.read_bytes() == b"excel-bytes"
    assert payload["workspace_rel"] == f"{WORKSPACE_UPLOADS_SUBDIR}/report.xlsx"
    assert uploaded.parent.name == WORKSPACE_UPLOADS_SUBDIR
    assert uploaded.is_relative_to(workspace.resolve())


def test_stage_copies_legacy_inbox_attachment_into_workspace_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.upload import _session_attachment_dir

    workspace = tmp_path / "workspace" / "admin"
    workspace.mkdir(parents=True)
    inbox = tmp_path / "inbox"
    monkeypatch.setenv("HERMES_WEBUI_ATTACHMENT_DIR", str(inbox))
    _trust_any_workspace(monkeypatch)

    session_id = "sess-stage-1"
    inbox_file = _session_attachment_dir(session_id)
    inbox_file.mkdir(parents=True)
    src = inbox_file / "legacy.xlsx"
    src.write_bytes(b"legacy")

    attachments = [{"name": "legacy.xlsx", "path": str(src), "mime": "application/vnd.ms-excel"}]
    message = "analyze this\n\n@" + str(src)
    staged, rewritten = stage_chat_attachments_to_workspace(
        attachments,
        workspace,
        message=message,
    )

    assert len(staged) == 1
    dest = pathlib.Path(staged[0]["path"])
    assert dest.exists()
    assert dest.read_bytes() == b"legacy"
    assert staged[0]["workspace_rel"] == f"{WORKSPACE_UPLOADS_SUBDIR}/legacy.xlsx"
    assert rewritten.endswith(f"@{WORKSPACE_UPLOADS_SUBDIR}/legacy.xlsx")


def test_stage_leaves_workspace_uploads_paths_unchanged(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace" / "admin"
    _trust_any_workspace(monkeypatch)
    uploads = workspace / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    existing = uploads / "already.xlsx"
    existing.write_bytes(b"ok")
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/already.xlsx"

    attachments = [{"name": "already.xlsx", "path": str(existing), "workspace_rel": rel}]
    staged, rewritten = stage_chat_attachments_to_workspace(
        attachments,
        workspace,
        message=f"hi\n\n@{rel}",
    )

    assert staged[0]["path"] == str(existing)
    assert rewritten.endswith(f"@{rel}")


def test_process_upload_foreign_session_workspace_stores_in_account_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale/foreign session workspace must not block uploads for the signed-in account."""
    from app.domain.models import Session
    from app.domain.users import UserAccess
    from app.domain.workspace import clear_request_user_access, set_request_user_access

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_ws.mkdir(parents=True)
    pathom_ws.mkdir(parents=True)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr(
        "app.domain.workspace._default_hermes_home",
        lambda: hermes_home,
    )
    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: hermes_home / "profiles" / name,
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    session_id = "sess-foreign-workspace"
    session = Session(session_id=session_id, workspace=str(admin_ws))
    monkeypatch.setattr(
        "app.domain.upload.get_session",
        lambda sid: session if sid == session_id else (_ for _ in ()).throw(KeyError(sid)),
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="pathom_u",
        profile_names=("pathom_u",),
    )
    token = set_request_user_access(access)
    try:
        payload, status = process_upload(
            {"session_id": session_id, "workspace": str(admin_ws)},
            {"file": ("notes.txt", b"owned-by-pathom")},
        )
    finally:
        clear_request_user_access(token)

    assert status == 200
    uploaded = pathlib.Path(payload["path"])
    assert uploaded.exists()
    assert uploaded.is_relative_to(pathom_ws / WORKSPACE_UPLOADS_SUBDIR)
    assert not uploaded.is_relative_to(admin_ws)
    assert payload["workspace_rel"] == f"{WORKSPACE_UPLOADS_SUBDIR}/notes.txt"


def test_process_upload_nested_workspace_stores_in_main_user_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace" / "admin"
    nested = workspace / "ttt"
    nested.mkdir(parents=True)
    sid = _stub_session(tmp_path, monkeypatch, nested)

    def _resolve(path):
        token = str(path).strip()
        if token in ("/workspace/ttt", str(nested)):
            return nested.resolve()
        if token in ("/workspace", str(workspace)):
            return workspace.resolve()
        return pathlib.Path(path).expanduser().resolve()

    monkeypatch.setattr(
        "app.domain.upload.resolve_trusted_workspace",
        _resolve,
    )
    monkeypatch.setattr(
        "app.domain.workspace.resolve_trusted_workspace",
        _resolve,
    )
    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.workspace.account_workspace_containment_root",
        lambda **kwargs: workspace.resolve(),
    )
    main_root = workspace.resolve()
    monkeypatch.setattr(
        "app.domain.workspace.resolve_main_user_workspace_root",
        lambda token=None, **kwargs: main_root,
    )

    payload, status = process_upload(
        {"session_id": sid, "workspace": str(nested)},
        {"file": ("photo.png", b"png-bytes")},
    )

    assert status == 200
    uploaded = pathlib.Path(payload["path"])
    assert uploaded.exists()
    assert uploaded.is_relative_to(workspace / WORKSPACE_UPLOADS_SUBDIR)
    assert not uploaded.is_relative_to(nested)
    assert payload["workspace_rel"] == f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png"


def test_build_attachment_agent_context_uses_main_virtual_path_for_nested_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.domain.workspace.nested_workspaces_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.domain.workspace.resolve_main_user_workspace_root",
        lambda _token: pathlib.Path("/data/workspace/admin"),
    )
    monkeypatch.setattr(
        "app.domain.workspace.resolve_trusted_workspace",
        lambda _token: pathlib.Path("/data/workspace/admin/ttt"),
    )

    hint = build_attachment_agent_context(
        [{
            "workspace_rel": f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png",
            "mime": "image/png",
            "is_image": True,
        }],
        active_workspace="/workspace/ttt",
    )
    assert hint == "@/workspace/.uploads/photo.png"


def test_build_attachment_agent_context_lists_uploads_paths() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/report.xlsx"
    hint = build_attachment_agent_context(
        [{"name": "report.xlsx", "path": "/tmp/ws/.uploads/report.xlsx", "workspace_rel": rel}],
    )
    assert hint == f"@{rel}"


def test_build_attachment_agent_context_omits_images_for_native_vision() -> None:
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png"
    hint = build_attachment_agent_context(
        [{
            "name": "photo.png",
            "path": "/tmp/ws/.uploads/photo.png",
            "workspace_rel": rel,
            "mime": "image/png",
            "is_image": True,
        }],
        omit_images=True,
    )
    assert hint == ""


def test_file_raw_resolves_workspace_uploads_by_basename(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import Session
    from app.domain.routes import _file_raw_target

    workspace = tmp_path / "workspace" / "admin"
    uploads = workspace / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "image.png"
    image.write_bytes(b"png-bytes")
    session = Session(session_id="478e109c14de", workspace=str(workspace))

    target = _file_raw_target(session, session.session_id, "image.png")
    assert target == image.resolve()

    renamed = uploads / "image-1.png"
    renamed.write_bytes(b"png-2")
    assert _file_raw_target(session, session.session_id, "image-1.png") == renamed.resolve()


def test_file_raw_finds_profile_subfolder_uploads_for_virtual_workspace(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import Session
    from app.domain.routes import _file_raw_target

    hermes_home = tmp_path / "hermes"
    shared_root = hermes_home / "workspace"
    admin_uploads = shared_root / "admin" / WORKSPACE_UPLOADS_SUBDIR
    admin_uploads.mkdir(parents=True)
    image = admin_uploads / "image.png"
    image.write_bytes(b"png-bytes")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    admin_root = (shared_root / "admin").resolve()

    def _resolve(path):
        token = str(path or "").strip()
        if token == "/workspace":
            return admin_root
        return pathlib.Path(path).expanduser().resolve()

    monkeypatch.setattr("app.domain.workspace.resolve_trusted_workspace", _resolve)
    monkeypatch.setattr(
        "app.domain.workspace.resolve_main_user_workspace_root",
        lambda workspace=None, **kwargs: _resolve(workspace),
    )
    monkeypatch.setattr(
        "app.domain.profiles.get_active_hermes_home",
        lambda: hermes_home,
    )

    session = Session(session_id="478e109c14de", workspace="/workspace")
    assert _file_raw_target(session, session.session_id, "image.png") == image.resolve()
    assert _file_raw_target(
        session,
        session.session_id,
        str(image),
    ) == image.resolve()
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/image.png"
    assert _file_raw_target(session, session.session_id, rel) == image.resolve()
    from app.domain.routes import _workspace_file_target

    assert _workspace_file_target("/workspace", rel) == image.resolve()


def test_file_raw_resolves_foreign_session_workspace_uploads_rel(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale session workspace must not break `.uploads/` preview for the signed-in account."""
    from app.domain.models import Session
    from app.domain.routes import _file_raw_target, _workspace_file_target
    from app.domain.users import UserAccess
    from app.domain.workspace import clear_request_user_access, set_request_user_access

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    uploads = pathom_ws / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "shot.png"
    image.write_bytes(b"png")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    session = Session(session_id="sess-foreign", workspace=str(admin_ws))
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/shot.png"
    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="pathom_u",
        profile_names=("pathom_u",),
    )
    token = set_request_user_access(access)
    try:
        assert _file_raw_target(session, session.session_id, rel) == image.resolve()
        assert _workspace_file_target("/workspace", rel) == image.resolve()
    finally:
        clear_request_user_access(token)


def test_normalize_chat_attachment_records_resolves_workspace_rel(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.upload import normalize_chat_attachment_records

    workspace = tmp_path / "workspace" / "admin"
    uploads = workspace / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "photo.png"
    image.write_bytes(b"png")
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png"

    _trust_any_workspace(monkeypatch)

    resolved = normalize_chat_attachment_records(
        [{"name": "photo.png", "workspace_rel": rel, "mime": "image/png", "is_image": True}],
        session_workspace=str(workspace),
    )
    assert resolved[0]["path"] == str(image.resolve())
    assert resolved[0]["workspace_rel"] == rel


def test_native_multimodal_accepts_workspace_rel_only_upload(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.streaming import _build_native_multimodal_message

    workspace = tmp_path / "workspace" / "admin"
    uploads = workspace / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "photo.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/photo.png"
    _trust_any_workspace(monkeypatch)
    monkeypatch.setattr(
        "app.domain.streaming._should_embed_native_images_for_turn",
        lambda *args, **kwargs: True,
    )

    result = _build_native_multimodal_message(
        "",
        "what is this?",
        [{"name": "photo.png", "workspace_rel": rel, "mime": "image/png", "is_image": True}],
        str(workspace),
        cfg={},
        provider="openai",
        model="gpt-4o",
    )

    assert isinstance(result, list)
    assert result[1]["type"] == "image_url"


def test_native_vision_resolves_uploads_with_pinned_account_workspace(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming thread env must resolve ``.uploads/`` for non-default accounts."""
    from app.domain.streaming import _build_native_multimodal_message
    from app.domain.upload import resolve_agent_attachment_path

    hermes_home = tmp_path / ".hermes"
    shared_root = hermes_home / "workspace"
    admin_root = shared_root / "admin"
    uploads = admin_root / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "2026-05-21-2.jpg"
    image.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/2026-05-21-2.jpg"

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_root))
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domain.streaming._should_embed_native_images_for_turn",
        lambda *args, **kwargs: True,
    )

    resolved = resolve_agent_attachment_path(rel, session_workspace="/workspace")
    assert resolved == str(image.resolve())

    result = _build_native_multimodal_message(
        "[1 image] [Workspace::v1: /workspace] ",
        "เห็นอะไรในรูป",
        [{"name": "2026-05-21-2.jpg", "workspace_rel": rel, "mime": "image/jpeg", "is_image": True}],
        "/workspace",
        cfg={},
        provider="custom",
        model="unsloth/Qwen3.6-35B-A3B-MTP-GGUF:BF16",
    )

    assert isinstance(result, list), "expected native image_url parts, got plain text fallback"
    assert any(part.get("type") == "image_url" for part in result)


def test_chat_start_native_vision_payload_for_pinned_admin_uploads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat streaming must embed base64 image_url for admin ``.uploads/`` files."""
    from app.domain.streaming import (
        _build_native_multimodal_message,
        _resolve_image_input_mode,
    )
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        normalize_chat_attachment_records,
        stage_chat_attachments_to_workspace,
    )

    hermes_home = tmp_path / ".hermes"
    shared_root = hermes_home / "workspace"
    admin_root = shared_root / "admin"
    uploads = admin_root / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "2026-05-21.jpg"
    image.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/2026-05-21.jpg"

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_root))
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)

    attachments = normalize_chat_attachment_records(
        [{"name": "2026-05-21.jpg", "workspace_rel": rel, "mime": "image/jpeg", "is_image": True}],
        session_workspace="/workspace",
    )
    staged, msg_text = stage_chat_attachments_to_workspace(
        attachments,
        "/workspace",
        message="เห็นอะไรในรูป",
    )
    cfg = {
        "agent": {"image_input_mode": "auto"},
        "model": {
            "provider": "custom",
            "model": "unsloth/Qwen3.6-35B-A3B-MTP-GGUF:bf16",
        },
    }
    assert _resolve_image_input_mode(
        cfg,
        provider="custom",
        model="unsloth/Qwen3.6-35B-A3B-MTP-GGUF:bf16",
    ) == "native"

    result = _build_native_multimodal_message(
        "[1 image] [Workspace::v1: /workspace] ",
        msg_text,
        staged,
        "/workspace",
        cfg=cfg,
        provider="custom",
        model="unsloth/Qwen3.6-35B-A3B-MTP-GGUF:bf16",
    )

    assert isinstance(result, list), "expected native image_url parts, got plain text fallback"
    image_parts = [part for part in result if part.get("type") == "image_url"]
    assert image_parts, "chat start payload must include image_url content"
    url = image_parts[0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,"), (
        "custom OpenAI endpoints need embedded base64 data URLs, not file:// paths"
    )


def test_streaming_prepends_attachment_hint():
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app/domain/streaming.py"
    ).read_text(encoding="utf-8")
    assert "build_attachment_agent_context" in src
    assert "stage_chat_attachments_to_workspace" in src
    assert "_attach_hint" in src


def test_pathom_u_upload_resolves_despite_stale_admin_env_pin(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pathom_u ``.uploads/`` must resolve even when admin env pin is stale."""
    from app.domain.streaming import _build_native_multimodal_message
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        build_attachment_agent_context,
        normalize_chat_attachment_records,
        strip_image_paths_from_attached_files_marker,
    )
    from app.domain.workspace import account_workspace_containment_root

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    pathom_profile = hermes_home / "profiles" / "pathom_u"
    uploads = pathom_ws / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "foo.jpg"
    image.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/foo.jpg"

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_ws))
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )
    monkeypatch.setattr(
        "app.domain.streaming._should_embed_native_images_for_turn",
        lambda *args, **kwargs: True,
    )

    root = account_workspace_containment_root(
        workspace_disk="/workspace",
        active_workspace_virtual="/workspace",
        profile_home=pathom_profile,
    )
    assert root == pathom_ws.resolve()

    att = normalize_chat_attachment_records(
        [{"name": "foo.jpg", "workspace_rel": rel, "mime": "image/jpeg", "is_image": True}],
        session_workspace="/workspace",
        profile_home=pathom_profile,
    )
    assert pathlib.Path(att[0]["path"]).is_file()

    msg = f"เห็นอะไรในรูป\n\n@{rel}"
    msg_stripped = strip_image_paths_from_attached_files_marker(msg, att)
    hint = build_attachment_agent_context(att, active_workspace="/workspace", omit_images=True)
    assert hint == ""
    agent_msg = msg_stripped

    result = _build_native_multimodal_message(
        "[1 image] [Workspace::v1: /workspace] ",
        agent_msg,
        att,
        "/workspace",
        cfg={"agent": {"image_input_mode": "auto"}},
        provider="openai",
        model="gpt-4o",
        profile_home=pathom_profile,
    )
    assert isinstance(result, list), "expected native image_url parts, got plain text fallback"
    assert any(part.get("type") == "image_url" for part in result)


def test_pathom_u_native_vision_remaps_stale_admin_attachment_path(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attachments with stale admin ``path`` must still embed for pathom_u."""
    from app.domain.streaming import _build_native_multimodal_message
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        normalize_chat_attachment_records,
    )

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    pathom_profile = hermes_home / "profiles" / "pathom_u"
    uploads = pathom_ws / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "fp4_compare-2.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/fp4_compare-2.png"
    stale_admin_path = str(admin_ws / rel)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_ws))
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )
    monkeypatch.setattr(
        "app.domain.streaming._should_embed_native_images_for_turn",
        lambda *args, **kwargs: True,
    )

    payload = {
        "name": "fp4_compare-2.png",
        "path": stale_admin_path,
        "workspace_rel": rel,
        "mime": "image/png",
        "is_image": True,
    }
    att = normalize_chat_attachment_records(
        [payload],
        session_workspace="/workspace",
        profile_home=pathom_profile,
    )
    assert pathlib.Path(att[0]["path"]).resolve() == image.resolve()

    result = _build_native_multimodal_message(
        "[1 image] [Workspace::v1: /workspace] ",
        "เห็นอะไร",
        att,
        "/workspace",
        cfg={"agent": {"image_input_mode": "auto"}},
        provider="custom",
        model="unsloth/Qwen3.6-35B-A3B-MTP-GGUF:BF16",
        profile_home=pathom_profile,
    )
    assert isinstance(result, list), "expected native image_url parts, got plain text fallback"
    assert any(part.get("type") == "image_url" for part in result)


def test_normalize_prefers_signed_in_profile_over_stale_admin_session(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat/start must resolve ``.uploads/`` for the signed-in account, not session profile."""
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        normalize_chat_attachment_records,
    )
    from app.domain.users import UserAccess
    from app.domain.workspace import clear_request_user_access, set_request_user_access

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    pathom_ws = hermes_home / "workspace" / "pathom_u"
    admin_profile = hermes_home / "profiles" / "admin"
    uploads = pathom_ws / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir(parents=True)
    image = uploads / "fp4_compare-2.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/fp4_compare-2.png"
    stale_admin_path = str(admin_ws / rel)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_ws))
    monkeypatch.setenv("TERMINAL_CWD", "/workspace")
    monkeypatch.setenv("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL", "/workspace")
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)
    monkeypatch.setattr(
        "app.domain.profiles.get_hermes_home_for_profile",
        lambda name: admin_profile if name == "admin" else hermes_home / "profiles" / "pathom_u",
    )
    monkeypatch.setattr(
        "app.domain.workspace.profile_workspace_dir",
        lambda _home, access=None: pathom_ws,
    )

    access = UserAccess(
        multi_user_enabled=True,
        user_id="pathom_u@example.com",
        username="pathom_u@example.com",
        role="user",
        profile_name="pathom_u",
        profile_names=("pathom_u",),
    )
    token = set_request_user_access(access)
    try:
        att = normalize_chat_attachment_records(
            [{
                "name": "fp4_compare-2.png",
                "path": stale_admin_path,
                "workspace_rel": rel,
                "mime": "image/png",
                "is_image": True,
            }],
            session_workspace="/workspace",
            profile_home=admin_profile,
        )
    finally:
        clear_request_user_access(token)

    assert pathlib.Path(att[0]["path"]).resolve() == image.resolve()


def test_normalize_drops_missing_stale_admin_path_for_workspace_rel(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When disk resolution fails, do not keep a stale foreign absolute ``path``."""
    from app.domain.upload import WORKSPACE_UPLOADS_SUBDIR, normalize_chat_attachment_records

    hermes_home = tmp_path / ".hermes"
    admin_ws = hermes_home / "workspace" / "admin"
    admin_profile = hermes_home / "profiles" / "admin"
    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/missing.png"
    stale_admin_path = str(admin_ws / rel)

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_WEBUI_MULTI_USER", "1")
    monkeypatch.setenv("HERMES_WEBUI_ACCOUNT_WORKSPACE_ROOT", str(admin_ws))
    monkeypatch.setattr("app.domain.workspace._default_hermes_home", lambda: hermes_home)
    monkeypatch.setattr("app.domain.workspace.nested_workspaces_enabled", lambda: True)

    att = normalize_chat_attachment_records(
        [{
            "name": "missing.png",
            "path": stale_admin_path,
            "workspace_rel": rel,
            "mime": "image/png",
            "is_image": True,
        }],
        session_workspace="/workspace",
        profile_home=admin_profile,
    )

    assert att[0]["path"] == rel


def test_custom_provider_composer_upload_preserves_upload_path_tokens() -> None:
    """Composer uploads must keep ``@.uploads/`` hints for custom ``vision_analyze``."""
    from app.domain.streaming import _preserve_upload_path_hints_for_native_turn
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        build_attachment_agent_context,
        strip_image_paths_from_attached_files_marker,
    )

    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/fp4_compare.png"
    attachments = [{
        "name": "fp4_compare.png",
        "path": rel,
        "workspace_rel": rel,
        "mime": "image/png",
        "is_image": True,
    }]
    message = f"เห็นอะไร\n\n@{rel}"
    native_vision_turn = True
    preserve_hints = _preserve_upload_path_hints_for_native_turn("custom")
    omit_image_path_hints = native_vision_turn and not preserve_hints

    assert preserve_hints is True
    agent_message = message
    if omit_image_path_hints:
        agent_message = strip_image_paths_from_attached_files_marker(
            agent_message,
            attachments,
        )
    hint = build_attachment_agent_context(
        attachments,
        active_workspace="/workspace",
        omit_images=omit_image_path_hints,
    )
    if hint:
        agent_message = f"{hint}\n\n{agent_message}".strip()

    assert f"@{rel}" in agent_message
    assert "เห็นอะไร" in agent_message


def test_native_vision_fallback_restores_upload_paths(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When native embed fails, agent message must still include ``@.uploads/`` paths."""
    from app.domain.upload import (
        WORKSPACE_UPLOADS_SUBDIR,
        build_attachment_agent_context,
        strip_image_paths_from_attached_files_marker,
    )

    rel = f"{WORKSPACE_UPLOADS_SUBDIR}/missing.jpg"
    att = [{
        "name": "missing.jpg",
        "path": rel,
        "workspace_rel": rel,
        "mime": "image/jpeg",
        "is_image": True,
    }]
    msg = f"เห็นอะไรในรูป\n\n@{rel}"
    msg_stripped = strip_image_paths_from_attached_files_marker(msg, att)
    hint = build_attachment_agent_context(att, omit_images=False)
    fallback_body = f"{hint}\n\n{msg}".strip() if hint else msg
    assert rel in fallback_body
    assert msg_stripped == "เห็นอะไรในรูป"
    assert rel not in msg_stripped
