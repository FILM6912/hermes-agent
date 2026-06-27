from __future__ import annotations

import pytest

from app.document_api.core.config import Settings
from app.document_api.core.storage_urls import (
    extract_storage_object_paths,
    fix_storage_public_url_typos,
    public_storage_bucket_base,
    public_storage_object_url,
    resolve_document_public_base_url,
    rewrite_storage_urls_in_content,
    rewrite_storage_urls_in_row,
)


def _settings(**overrides: object) -> Settings:
    return Settings.model_construct(**overrides)


def test_resolve_public_base_url_from_explicit_env():
    s = _settings(hermes_webui_public_url="https://hermes.example.com")
    assert resolve_document_public_base_url(s) == "https://hermes.example.com"


def test_resolve_public_base_url_empty_without_explicit_env():
    s = _settings(hermes_webui_host="192.168.1.10", hermes_webui_port=8787)
    assert resolve_document_public_base_url(s) == ""


def test_resolve_public_base_url_empty_when_bind_all_interfaces():
    s = _settings(hermes_webui_host="0.0.0.0", hermes_webui_port=8787)
    assert resolve_document_public_base_url(s) == ""


def test_public_storage_object_url_uses_backend_not_supabase():
    s = _settings(
        hermes_webui_public_url="http://192.168.99.2:8787",
        supabase_url="http://192.168.99.1:8000",
        supabase_storage_bucket="document-files",
    )
    url = public_storage_object_url(
        "document-files",
        "rp-008344/files/img_001.jpeg",
        s,
    )
    assert url == (
        "http://192.168.99.2:8787/storage/v1/object/public/"
        "document-files/rp-008344/files/img_001.jpeg"
    )
    assert "192.168.99.1:8000" not in url


def test_public_storage_object_url_relative_by_default():
    s = _settings(
        hermes_webui_host="0.0.0.0",
        hermes_webui_port=8787,
        supabase_url="http://192.168.99.1:8000",
        supabase_storage_bucket="document-files",
    )
    url = public_storage_object_url(
        "document-files",
        "rp-008344/files/img_001.jpeg",
        s,
    )
    assert url == (
        "/storage/v1/object/public/document-files/rp-008344/files/img_001.jpeg"
    )


def test_public_storage_bucket_base_explicit_absolute():
    s = _settings(hermes_webui_public_url="http://127.0.0.1:8787")
    assert public_storage_bucket_base("document-files", s) == (
        "http://127.0.0.1:8787/storage/v1/object/public/document-files"
    )


def test_public_storage_bucket_base_relative_by_default():
    s = _settings(hermes_webui_host="127.0.0.1", hermes_webui_port=8787)
    assert public_storage_bucket_base("document-files", s) == (
        "/storage/v1/object/public/document-files"
    )


def test_extract_paths_from_backend_and_legacy_supabase_urls():
    s = _settings(
        hermes_webui_public_url="http://127.0.0.1:8787",
        supabase_url="http://192.168.99.1:8000",
        supabase_storage_bucket="document-files",
    )
    backend = (
        "![img](http://127.0.0.1:8787/storage/v1/object/public/document-files/"
        "doc/files/img.jpeg)"
    )
    legacy = (
        "![img](http://192.168.99.1:8000/storage/v1/object/public/document-files/"
        "doc/files/img2.jpeg)"
    )
    relative = "![img](/storage/v1/object/public/document-files/doc/files/img3.jpeg)"
    content = "\n".join([backend, legacy, relative])
    paths = extract_storage_object_paths(content, bucket="document-files", settings=s)
    assert paths == {
        "doc/files/img.jpeg",
        "doc/files/img2.jpeg",
        "doc/files/img3.jpeg",
    }


def test_document_public_base_url_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOCUMENT_PUBLIC_BASE_URL", "http://docs.local:9000")
    monkeypatch.delenv("HERMES_WEBUI_PUBLIC_URL", raising=False)
    s = Settings()
    assert resolve_document_public_base_url(s) == "http://docs.local:9000"


def test_rewrite_storage_urls_in_content_switches_public_base():
    s_new = _settings(hermes_webui_public_url="https://hermes.example.com")
    stored = (
        "![img](http://192.168.99.1:8787/storage/v1/object/public/document-files/"
        "doc/files/img.jpeg)\n"
        "legacy ![img2](http://192.168.99.1:8000/storage/v1/object/public/document-files/"
        "doc/files/img2.jpeg)\n"
        "relative ![img3](/storage/v1/object/public/document-files/doc/files/img3.jpeg)"
    )
    rewritten = rewrite_storage_urls_in_content(stored, settings=s_new)
    expected = (
        "![img](https://hermes.example.com/storage/v1/object/public/document-files/"
        "doc/files/img.jpeg)\n"
        "legacy ![img2](https://hermes.example.com/storage/v1/object/public/document-files/"
        "doc/files/img2.jpeg)\n"
        "relative ![img3](https://hermes.example.com/storage/v1/object/public/document-files/doc/files/img3.jpeg)"
    )
    assert rewritten == expected
    assert "192.168.99.1" not in rewritten


def test_rewrite_storage_urls_in_content_relative_when_env_unset():
    s = _settings(
        hermes_webui_public_url="",
        supabase_url="http://192.168.99.1:8000",
    )
    stored = (
        "![img](http://192.168.99.1:8787/storage/v1/object/public/document-files/"
        "doc/files/img.jpeg)"
    )
    rewritten = rewrite_storage_urls_in_content(stored, settings=s)
    assert rewritten == (
        "![img](/storage/v1/object/public/document-files/doc/files/img.jpeg)"
    )


def test_rewrite_storage_urls_in_content_fixes_component_public_typo():
    broken = (
        "![img](https://corp-brain.aitech.co.th/storage/v1/component/public/"
        "document-files/spec/files/img_002.jpeg)"
    )
    fixed = rewrite_storage_urls_in_content(
        broken,
        settings=_settings(hermes_webui_public_url="https://corp-brain.aitech.co.th"),
    )
    assert "/storage/v1/object/public/" in fixed
    assert "component/public" not in fixed


def test_rewrite_storage_urls_in_row_updates_metadata():
    s = _settings(hermes_webui_public_url="http://docs.local:9000")
    row = rewrite_storage_urls_in_row(
        {
            "content": "see ![x](/storage/v1/object/public/document-files/a/b.png)",
            "metadata": {
                "image_url": "http://old.host:8787/storage/v1/object/public/document-files/a/b.png",
                "source_file_url": "http://old.host:8787/storage/v1/object/public/document-files/a/source.pdf",
            },
        },
        settings=s,
    )
    assert row["content"].startswith("see ![x](http://docs.local:9000/storage/v1/object/public/")
    assert row["metadata"]["image_url"].startswith("http://docs.local:9000/storage/v1/object/public/")
    assert row["metadata"]["source_file_url"].startswith("http://docs.local:9000/storage/v1/object/public/")
