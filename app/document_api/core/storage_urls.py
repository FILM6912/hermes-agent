from __future__ import annotations

import json
import re

from app.document_api.core.config import Settings, get_settings

_STORAGE_PUBLIC_PREFIX = "/storage/v1/object/public"
_STORAGE_COMPONENT_PUBLIC_TYPO = "/storage/v1/component/public/"
# Absolute or origin-relative public storage object URLs in markdown/metadata.
_STORAGE_PUBLIC_OBJECT_RE = re.compile(
    r"(?:https?://[^\s/\"'>)]+)?(/storage/v1/object/public/([^/\s)\"'>\]]+)/([^\s)\"'>\]]+))"
)
_METADATA_URL_KEYS = ("image_url", "source_file_url", "bucket_url")


def resolve_document_public_base_url(settings: Settings | None = None) -> str:
    """Browser-facing base URL for stored document links (WebUI, not Supabase).

    When ``HERMES_WEBUI_PUBLIC_URL`` (alias ``DOCUMENT_PUBLIC_BASE_URL``) is set,
    returns that absolute base for external consumers. Otherwise returns an empty
    string so callers emit origin-relative ``/storage/v1/...`` paths that resolve
    against whichever host the user opened the WebUI from (localhost, LAN IP, etc.).
    """
    s = settings or get_settings()
    explicit = (s.hermes_webui_public_url or "").strip().rstrip("/")
    return explicit


def public_storage_object_path(bucket: str, object_path: str) -> str:
    bucket_name = (bucket or "").strip().strip("/")
    path = (object_path or "").strip().lstrip("/")
    if path:
        return f"{_STORAGE_PUBLIC_PREFIX}/{bucket_name}/{path}"
    return f"{_STORAGE_PUBLIC_PREFIX}/{bucket_name}"


def public_storage_bucket_base(bucket: str, settings: Settings | None = None) -> str:
    base = resolve_document_public_base_url(settings)
    return f"{base}{public_storage_object_path(bucket, '')}"


def public_storage_object_url(
    bucket: str,
    object_path: str,
    settings: Settings | None = None,
) -> str:
    base = resolve_document_public_base_url(settings)
    return f"{base}{public_storage_object_path(bucket, object_path)}"


def _storage_url_prefixes(*, bucket: str, settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    bucket_name = (bucket or "").strip().strip("/")
    rel = f"{_STORAGE_PUBLIC_PREFIX}/{bucket_name}/"
    prefixes = [rel]
    public_base = resolve_document_public_base_url(s)
    if public_base:
        prefixes.append(f"{public_base}{rel}")
    supabase_base = (s.supabase_url or "").strip().rstrip("/")
    if supabase_base:
        prefixes.append(f"{supabase_base}{rel}")
    # De-dupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for prefix in prefixes:
        if prefix not in seen:
            seen.add(prefix)
            out.append(prefix)
    return out


def extract_storage_object_paths(
    content: str,
    *,
    bucket: str,
    settings: Settings | None = None,
) -> set[str]:
    """Extract object paths from markdown/content referencing public storage URLs."""
    text = content or ""
    paths: set[str] = set()
    for prefix in _storage_url_prefixes(bucket=bucket, settings=settings):
        pattern = re.compile(re.escape(prefix) + r"([^\s)\"']+)")
        paths.update(m.group(1) for m in pattern.finditer(text))
    return paths


def fix_storage_public_url_typos(content: str) -> str:
    """Correct ``/storage/v1/component/public/`` — a frequent LLM copy typo."""
    text = content or ""
    if not text or "component/public" not in text.casefold():
        return text
    return text.replace(_STORAGE_COMPONENT_PUBLIC_TYPO, _STORAGE_PUBLIC_PREFIX + "/")


def rewrite_storage_urls_in_content(content: str, *, settings: Settings | None = None) -> str:
    """Rewrite stored public storage links to the current ``HERMES_WEBUI_PUBLIC_URL`` base.

    Applies at read/search time so changing ``.env`` updates RAG markdown image URLs
    without re-ingesting documents. Accepts legacy absolute hosts (WebUI, Supabase, etc.)
    and origin-relative ``/storage/v1/object/public/...`` paths.
    """
    text = fix_storage_public_url_typos(content or "")
    if not text or _STORAGE_PUBLIC_PREFIX not in text:
        return text
    s = settings or get_settings()

    def _repl(match: re.Match[str]) -> str:
        bucket, object_path = match.group(2), match.group(3)
        return public_storage_object_url(bucket, object_path, s)

    return _STORAGE_PUBLIC_OBJECT_RE.sub(_repl, text)


def rewrite_storage_urls_in_metadata(
    metadata: dict[str, object] | None,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    if not metadata:
        return {}
    s = settings or get_settings()
    out = dict(metadata)
    for key in _METADATA_URL_KEYS:
        val = out.get(key)
        if isinstance(val, str) and _STORAGE_PUBLIC_PREFIX in val:
            out[key] = rewrite_storage_urls_in_content(val, settings=s)
    return out


def rewrite_storage_urls_in_row(row: dict, *, settings: Settings | None = None) -> dict:
    """Rewrite ``content`` and known metadata URL fields on a search/chunk row."""
    s = settings or get_settings()
    out = dict(row)
    content = out.get("content")
    if isinstance(content, str) and content:
        out["content"] = rewrite_storage_urls_in_content(content, settings=s)
    metadata = out.get("metadata")
    if isinstance(metadata, dict):
        out["metadata"] = rewrite_storage_urls_in_metadata(metadata, settings=s)
    elif isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            out["metadata"] = rewrite_storage_urls_in_metadata(parsed, settings=s)
    return out
