"""Workspace upload directories must be writable by the runtime user."""
from __future__ import annotations

import os
import pathlib

import pytest

from app.domain import workspace as workspace_mod
from app.domain.upload import WORKSPACE_UPLOADS_SUBDIR, process_upload


def test_ensure_directory_writable_creates_uploads_dir(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "workspace" / "pathom_u" / WORKSPACE_UPLOADS_SUBDIR
    resolved = workspace_mod.ensure_directory_writable(target)
    assert resolved == target.resolve()
    assert target.is_dir()
    probe = target / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_best_effort_align_path_ownership_repairs_foreign_owned_workspace(
    tmp_path: pathlib.Path,
) -> None:
    workspace = tmp_path / "workspace" / "pathom_u"
    workspace.mkdir(parents=True)
    other_uid = os.getuid() + 1 if os.getuid() < 65534 else max(os.getuid() - 1, 1)
    try:
        os.chown(workspace, other_uid, os.getgid())
    except PermissionError:
        pytest.skip("test user cannot chown directories for permission simulation")

    assert workspace.stat().st_uid != os.getuid()
    aligned = workspace_mod.best_effort_align_path_ownership(workspace)
    assert aligned >= 1
    assert workspace.stat().st_uid == os.getuid()


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_process_upload_writes_after_workspace_ownership_repair(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import Session

    workspace = tmp_path / "workspace" / "pathom_u"
    workspace.mkdir(parents=True)
    other_uid = os.getuid() + 1 if os.getuid() < 65534 else max(os.getuid() - 1, 1)
    try:
        os.chown(workspace, other_uid, os.getgid())
    except PermissionError:
        pytest.skip("test user cannot chown directories for permission simulation")

    uploads = workspace / WORKSPACE_UPLOADS_SUBDIR
    uploads.mkdir()
    os.chown(uploads, other_uid, os.getgid())

    session_id = "sess-upload-perms"
    session = Session(session_id=session_id, workspace=str(workspace))
    monkeypatch.setattr(
        "app.domain.upload.get_session",
        lambda sid: session if sid == session_id else (_ for _ in ()).throw(KeyError(sid)),
    )

    def _resolve(path):
        return pathlib.Path(path).expanduser().resolve()

    monkeypatch.setattr("app.domain.workspace.resolve_trusted_workspace", _resolve)
    monkeypatch.setattr(
        "app.domain.workspace.resolve_main_user_workspace_root",
        lambda workspace=None, **kwargs: _resolve(workspace),
    )
    monkeypatch.setattr(
        "app.domain.upload.resolve_trusted_workspace",
        _resolve,
    )

    payload, status = process_upload(
        {"session_id": session_id, "workspace": str(workspace)},
        {"file": ("2026-05-21.jpg", b"jpg-bytes")},
    )

    assert status == 200
    uploaded = pathlib.Path(payload["path"])
    assert uploaded.exists()
    assert uploaded.read_bytes() == b"jpg-bytes"
    assert uploaded.parent.name == WORKSPACE_UPLOADS_SUBDIR
