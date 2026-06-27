from __future__ import annotations

from pathlib import Path

import pytest

from app.document_api.services.office_legacy_convert import (
    LEGACY_OFFICE_EXTENSIONS,
    convert_legacy_office_file,
    find_soffice_binary,
    is_legacy_office_extension,
)


def test_legacy_office_extension_detection():
    assert is_legacy_office_extension(".doc")
    assert is_legacy_office_extension(".XLS")
    assert not is_legacy_office_extension(".docx")
    assert ".xls" in LEGACY_OFFICE_EXTENSIONS


def test_convert_legacy_office_file_requires_soffice(tmp_path: Path):
    src = tmp_path / "sample.doc"
    src.write_bytes(b"not a real doc")
    if find_soffice_binary() is None:
        with pytest.raises(RuntimeError, match="LibreOffice"):
            convert_legacy_office_file(src, tmp_path / "out")
    else:
        # Real conversion may fail on junk bytes; we only assert it reaches LO or errors cleanly.
        try:
            convert_legacy_office_file(src, tmp_path / "out")
        except RuntimeError:
            pass
