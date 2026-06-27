from __future__ import annotations

from app.document_api.services.document_pipeline import _SUPPORTED_EXT, get_converter
from app.document_api.services.office_legacy_convert import LEGACY_OFFICE_EXTENSIONS


def test_supported_extensions_include_legacy_office():
    for ext in (".doc", ".ppt", ".xls", ".xlsb", ".odt"):
        assert ext in _SUPPORTED_EXT
        assert ext in LEGACY_OFFICE_EXTENSIONS


def test_get_converter_accepts_modern_macro_formats():
    assert get_converter("report.docm").supports(".docm")
    assert get_converter("deck.pptm").supports(".pptm")
    assert get_converter("book.xls").supports(".xls")
