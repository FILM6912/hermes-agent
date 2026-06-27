"""Regression: spreadsheet preview strips duplicate index columns."""

from pathlib import Path


def test_spreadsheet_viewer_normalizes_index_column():
    viewer = Path("frontend/src/features/preview/components/SpreadsheetViewer.tsx").read_text(
        encoding="utf-8"
    )
    util = Path("frontend/src/features/preview/utils/spreadsheetDisplay.ts").read_text(
        encoding="utf-8"
    )
    assert "normalizeSpreadsheetTable" in viewer
    assert "stripRedundantIndexColumn" in util
    assert "PIPE_INDEX_CELL" in util
    assert "ลำดับ" in util
    assert "border-separate border-spacing-0" in viewer
    assert "sticky left-0 z-20" in viewer
    assert "overflow-auto py-4 pr-4 pl-0" in viewer
