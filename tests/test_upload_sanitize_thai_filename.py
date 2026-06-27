"""Upload basename sanitization for non-ASCII filenames."""
from app.domain.upload import _sanitize_upload_name


def test_thai_filename_becomes_ascii_safe():
    safe = _sanitize_upload_name('2024-05-21_เปรียบเทียบ_งบไทย_รายได้ไทย.jpg')
    assert safe.endswith('.jpg')
    assert safe.isascii()
    assert 'เปร' not in safe


def test_ascii_filename_unchanged():
    assert _sanitize_upload_name('compare-thai.jpg') == 'compare-thai.jpg'
