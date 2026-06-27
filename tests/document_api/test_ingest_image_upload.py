"""Document ingest must not write storage URLs before objects exist."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.document_api.services.document_pipeline import (
    ConversionResult,
    ImageAsset,
    _apply_image_url_map_to_markdown,
    _upload_conversion_images,
)


def test_apply_image_url_map_only_replaces_known_paths():
    md = "![a](images/img_001_abc.png)\n![b](images/img_002_def.png)"
    mapped = {"images/img_001_abc.png": "https://example.com/a.png"}
    out = _apply_image_url_map_to_markdown(md, mapped)
    assert "https://example.com/a.png" in out
    assert "images/img_002_def.png" in out


def test_upload_conversion_images_builds_map_only_for_successful_uploads(tmp_path: Path):
    ok_path = tmp_path / "images" / "img_001_abc.png"
    ok_path.parent.mkdir(parents=True)
    ok_path.write_bytes(b"png-bytes")
    missing = ImageAsset(
        name="img_002_def.png",
        path=tmp_path / "images" / "img_002_def.png",
        rel_path="images/img_002_def.png",
    )
    conv = ConversionResult(
        markdown="![a](images/img_001_abc.png)\n![b](images/img_002_def.png)",
        images=[
            ImageAsset(
                name="img_001_abc.png",
                path=ok_path,
                rel_path="images/img_001_abc.png",
            ),
            missing,
        ],
        source_filename="doc.pdf",
    )
    sb_client = MagicMock()
    storage = MagicMock()
    sb_client.storage.from_.return_value = storage
    conn = MagicMock()
    errors: list[str] = []

    urls, uploaded, url_map = _upload_conversion_images(
        conv=conv,
        storage_dir="doc/files",
        sb_client=sb_client,
        bucket="document-files",
        settings=MagicMock(),
        conn=conn,
        errors=errors,
        progress_callback=None,
    )

    assert len(urls) == 1
    assert len(uploaded) == 1
    assert "images/img_001_abc.png" in url_map
    assert "images/img_002_def.png" not in url_map
    assert any("image not found" in err for err in errors)
