"""Unit tests for FastAPI phase 4 files service cutover."""

from __future__ import annotations

import json
import pathlib

from app.services.files import FileService

REPO_ROOT = pathlib.Path(__file__).parent.parent


def test_files_endpoint_module_avoids_legacy_dispatch():
    source = (REPO_ROOT / "app" / "api" / "v1" / "endpoints" / "files.py").read_text(
        encoding="utf-8"
    )
    assert "dispatch_legacy_route" not in source
    assert "FileService" in source
    assert "_service.read_file(" in source
    assert "_service.save_file(" in source
    assert "_service.folder_download(" in source
    assert "_service.media(" in source
    assert "_service.open_vscode(" in source


def test_files_service_read_requires_session_id():
    service = FileService()
    response = service.read_file(query_params={"path": "README.md"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_save_requires_session_id():
    service = FileService()
    response = service.save_file(
        body={"path": "test.txt", "content": "hello"},
        headers={},
    )
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_delete_requires_session_id():
    service = FileService()
    response = service.delete_file(body={"path": "test.txt"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_create_requires_session_id():
    service = FileService()
    response = service.create_file(
        body={"path": "test.txt", "content": "hello"},
        headers={},
    )
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_rename_requires_session_id():
    service = FileService()
    response = service.rename_file(
        body={"path": "a.txt", "new_name": "b.txt"},
        headers={},
    )
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_create_dir_requires_session_id():
    service = FileService()
    response = service.create_dir(body={"path": "new_folder"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_path_requires_session_id():
    service = FileService()
    response = service.file_path(body={"path": "test.txt"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_raw_requires_session_id():
    service = FileService()
    response = service.read_file_raw(query_params={"path": "test.txt"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_view_requires_session_id():
    service = FileService()
    response = service.view_file(query_params={"path": "test.html"}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_folder_download_requires_session_id():
    service = FileService()
    response = service.folder_download(query_params={"path": "."}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "session_id" in body.get("error", "").lower()


def test_files_service_media_requires_path():
    service = FileService()
    response = service.media(query_params={}, headers={})
    assert response.status_code == 400
    body = json.loads(response.body)
    assert "path" in body.get("error", "").lower()
