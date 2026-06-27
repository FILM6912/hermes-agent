"""Deleting one file in a document set must not wipe sibling storage objects."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.document_api.services import document_catalog as catalog


def test_delete_document_only_removes_paths_for_scoped_file():
    folder = "pi-2026-knowledge-management"
    file_a = "doc-a.pdf"
    img_a = f"{catalog._safe_storage_name(folder)}/files/img_a.png"
    img_b = f"{catalog._safe_storage_name(folder)}/files/img_b.png"
    source_a = catalog._source_storage_path(folder, file_a)

    deleted_paths: list[str] = []

    def capture_delete(paths):
        deleted_paths.extend(paths)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.rowcount = 3

    with (
        patch.object(catalog, "get_document", return_value={"image_paths": {img_a}, "source_file_storage_paths": set(), "folders": [folder]}),
        patch.object(catalog, "_storage_paths_referenced_elsewhere", return_value=set()),
        patch.object(catalog, "_pg_conn", return_value=mock_conn),
        patch.object(catalog, "_delete_storage_objects", side_effect=capture_delete),
        patch.object(catalog, "_sb_client") as mock_sb,
    ):
        out = catalog.delete_document(file_a, document_name=folder)

    mock_sb.assert_not_called()
    assert out["deleted_images"] == 1
    assert img_b not in deleted_paths
    assert img_a in deleted_paths
    assert source_a in deleted_paths


def test_delete_document_skips_images_still_referenced_by_siblings():
    folder = "shared-set"
    file_a = "first.pdf"
    shared_img = f"{catalog._safe_storage_name(folder)}/files/img_shared.png"

    deleted_paths: list[str] = []

    with (
        patch.object(catalog, "get_document", return_value={"image_paths": {shared_img}, "source_file_storage_paths": set(), "folders": [folder]}),
        patch.object(catalog, "_storage_paths_referenced_elsewhere", return_value={shared_img}),
        patch.object(catalog, "_pg_conn") as mock_pg,
        patch.object(catalog, "_delete_storage_objects", side_effect=lambda p: deleted_paths.extend(p)),
    ):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pg.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.rowcount = 1

        out = catalog.delete_document(file_a, document_name=folder)

    assert out["deleted_images"] == 0
    assert shared_img not in deleted_paths
