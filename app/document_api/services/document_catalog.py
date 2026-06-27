from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterable

from app.document_api.core.config import get_settings
from app.document_api.core.storage_urls import (
    extract_storage_object_paths,
    public_storage_bucket_base,
    public_storage_object_url,
)
from app.document_api.services.document_pipeline import _safe_storage_name
from app.document_api.services.folder_catalog import TABLE_NAME as DOCUMENT_FOLDER_TABLE, delete_folder, ensure_folder_table, insert_folder_files, list_files_by_folder


def _pg_conn():
    import psycopg2

    settings = get_settings()
    return psycopg2.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=settings.pg_database,
        user=settings.pg_user,
        password=settings.pg_password,
        sslmode=settings.pg_sslmode,
    )


def _sb_client():
    from supabase.client import create_client

    settings = get_settings()
    return create_client(settings.supabase_url, supabase_key=settings.supabase_service_key)


def _bucket_base_url() -> str:
    settings = get_settings()
    return public_storage_bucket_base(settings.supabase_storage_bucket, settings)


def _extract_storage_paths(content: str, *, base_url: str, bucket: str) -> set[str]:
    del base_url  # legacy callers pass supabase_url; extractor handles all prefixes
    return extract_storage_object_paths(content, bucket=bucket)


def build_source_file_url(document_name: str | None, source_filename: str) -> str | None:
    settings = get_settings()
    if not settings.supabase_url:
        return None
    root_name = (document_name or "").strip() or source_filename
    storage_root = _safe_storage_name(root_name)
    storage_path = f"{storage_root}/source/{_safe_storage_name(source_filename)}"
    return f"{_bucket_base_url()}/{storage_path}"


def _source_storage_path(document_name: str, source_filename: str) -> str:
    return f"{_safe_storage_name(document_name)}/source/{_safe_storage_name(source_filename)}"


def _move_object_in_bucket(bucket_name: str, old_path: str, new_path: str) -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key or old_path == new_path:
        return
    sb = _sb_client()
    bucket = sb.storage.from_(bucket_name)
    try:
        bucket.move(old_path, new_path)
        return
    except Exception:
        payload = bucket.download(old_path)
        bucket.upload(
            path=new_path,
            file=payload,
            file_options={"upsert": "true"},
        )
        bucket.remove([old_path])


def _move_object(old_path: str, new_path: str) -> None:
    settings = get_settings()
    _move_object_in_bucket(settings.supabase_storage_bucket, old_path, new_path)


def _move_prefix_objects_in_bucket(bucket_name: str, old_prefix: str, new_prefix: str) -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        return
    sb = _sb_client()
    listed = sb.storage.from_(bucket_name).list(path=old_prefix) or []
    pairs: list[tuple[str, str]] = []
    for obj in listed:
        name = obj.get("name")
        if not name:
            continue
        old_path = f"{old_prefix}/{name}"
        new_path = f"{new_prefix}/{name}"
        pairs.append((old_path, new_path))

    if not pairs:
        return

    max_workers = min(max(1, settings.rename_move_workers), max(1, len(pairs)))
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(_move_object_in_bucket, bucket_name, old_path, new_path) for old_path, new_path in pairs
        ]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                errors.append(str(e))

    if errors:
        raise RuntimeError(f"failed to move some objects: {errors[:3]}")


def _move_prefix_objects(old_prefix: str, new_prefix: str) -> None:
    settings = get_settings()
    _move_prefix_objects_in_bucket(settings.supabase_storage_bucket, old_prefix, new_prefix)


def _remove_prefix_in_bucket(bucket_name: str, prefix: str) -> None:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key or not prefix.strip():
        return
    sb = _sb_client()
    try:
        listed = sb.storage.from_(bucket_name).list(path=prefix) or []
    except Exception:
        return
    paths = [f"{prefix}/{obj['name']}" for obj in listed if obj.get("name")]
    if paths:
        try:
            sb.storage.from_(bucket_name).remove(paths)
        except Exception:
            pass


def list_documents() -> list[dict]:
    settings = get_settings()
    sql = f"""
    SELECT
      d.metadata->>'source_filename' AS source_filename,
      COUNT(*)::int AS chunk_count,
      MAX(f.folder_name) AS folder_name,
      MAX(f.llm_summary) AS llm_summary
    FROM {settings.supabase_table_name} d
    LEFT JOIN {DOCUMENT_FOLDER_TABLE} f
      ON f.file_name = d.metadata->>'source_filename'
    GROUP BY d.metadata->>'source_filename'
    ORDER BY d.metadata->>'source_filename' ASC
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [
        {
            "source_filename": source_filename,
            "chunk_count": chunk_count,
            "folder_name": folder_name,
            "llm_summary": llm_summary or "",
        }
        for source_filename, chunk_count, folder_name, llm_summary in rows
        if source_filename
    ]


def get_document(source_filename: str, document_name: str | None = None) -> dict | None:
    settings = get_settings()
    doc_filter = (document_name or "").strip()
    sql = f"""
    SELECT content, metadata
    FROM {settings.supabase_table_name}
    WHERE metadata->>'source_filename'=%s
    """
    params: list[str] = [source_filename]
    if doc_filter:
        sql += """
    AND (document_name = %s OR (metadata->>'document_name') = %s)
    """
        params.extend([doc_filter, doc_filter])
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    if not rows:
        return None

    image_paths: set[str] = set()
    source_file_url: str | None = None
    source_file_storage_paths: set[str] = set()
    for content, metadata in rows:
        image_paths.update(
            _extract_storage_paths(
                content or "",
                base_url=settings.supabase_url.rstrip("/"),
                bucket=settings.supabase_storage_bucket,
            )
        )
        if source_file_url is None and isinstance(metadata, dict):
            source_file_url = metadata.get("source_file_url")
            storage_path = metadata.get("source_file_storage_path")
            if storage_path:
                source_file_storage_paths.add(str(storage_path))
        elif isinstance(metadata, dict):
            storage_path = metadata.get("source_file_storage_path")
            if storage_path:
                source_file_storage_paths.add(str(storage_path))
    folder_names = []
    ensure_folder_table()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT folder_name FROM {DOCUMENT_FOLDER_TABLE} WHERE file_name=%s ORDER BY folder_name",
                (source_filename,),
            )
            folder_rows = cur.fetchall()
            folder_names = [name for (name,) in folder_rows]
    if source_file_url is None:
        source_file_url = build_source_file_url(folder_names[0] if folder_names else None, source_filename)
    return {
        "source_filename": source_filename,
        "chunk_count": len(rows),
        "folders": folder_names,
        "image_paths": sorted(image_paths),
        "source_file_url": source_file_url,
        "source_file_storage_paths": sorted(source_file_storage_paths),
    }


def move_document_to_folder(source_filename: str, folder_name: str) -> dict:
    ensure_folder_table()
    folder = folder_name.strip()
    source = source_filename.strip()
    if not folder or not source:
        return {"updated": False}
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {DOCUMENT_FOLDER_TABLE} WHERE file_name=%s", (source,))
        conn.commit()
    inserted = insert_folder_files([(folder, source)])
    return {"updated": inserted > 0, "folder_name": folder}


def _delete_storage_objects(paths: Iterable[str]) -> None:
    settings = get_settings()
    paths = [p for p in paths if p]
    if not paths or not settings.supabase_url or not settings.supabase_service_key:
        return
    sb_client = _sb_client()
    # Supabase remove API accepts list of object paths in bucket.
    sb_client.storage.from_(settings.supabase_storage_bucket).remove(paths)


def _storage_paths_referenced_elsewhere(
    paths: set[str],
    *,
    source_filename: str,
    document_name: str | None,
) -> set[str]:
    """Paths still referenced by vector rows that are not being deleted."""
    if not paths:
        return set()
    settings = get_settings()
    still_used: set[str] = set()
    doc_filter = (document_name or "").strip()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if doc_filter:
                cur.execute(
                    f"""
                    SELECT content FROM {settings.supabase_table_name}
                    WHERE NOT (
                      metadata->>'source_filename' = %s
                      AND (document_name = %s OR (metadata->>'document_name') = %s)
                    )
                    """,
                    (source_filename, doc_filter, doc_filter),
                )
            else:
                cur.execute(
                    f"""
                    SELECT content FROM {settings.supabase_table_name}
                    WHERE metadata->>'source_filename' <> %s
                    """,
                    (source_filename,),
                )
            for (content,) in cur.fetchall():
                still_used.update(
                    extract_storage_object_paths(
                        content or "",
                        bucket=settings.supabase_storage_bucket,
                    )
                )
    return still_used


def delete_document(source_filename: str, document_name: str | None = None) -> dict:
    settings = get_settings()
    doc_filter = (document_name or "").strip()
    details = get_document(source_filename, document_name=doc_filter or None)
    if not details:
        return {"deleted_chunks": 0, "deleted_images": 0, "deleted_sources": 0}

    image_paths: set[str] = set(details["image_paths"])
    source_paths: set[str] = set(details.get("source_file_storage_paths", []))
    if doc_filter:
        source_paths.add(_source_storage_path(doc_filter, source_filename))

    # Only delete objects referenced by this file's chunks (and its source PDF).
    # Never list entire document-set storage prefixes — siblings share files/.
    referenced_elsewhere = _storage_paths_referenced_elsewhere(
        image_paths,
        source_filename=source_filename,
        document_name=doc_filter or None,
    )
    image_paths -= referenced_elsewhere

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            if doc_filter:
                cur.execute(
                    f"""
                    DELETE FROM {settings.supabase_table_name}
                    WHERE metadata->>'source_filename' = %s
                      AND (document_name = %s OR (metadata->>'document_name') = %s)
                    """,
                    (source_filename, doc_filter, doc_filter),
                )
            else:
                cur.execute(
                    f"DELETE FROM {settings.supabase_table_name} WHERE metadata->>'source_filename'=%s",
                    (source_filename,),
                )
            deleted_chunks = cur.rowcount
            if doc_filter:
                cur.execute(
                    f"DELETE FROM {DOCUMENT_FOLDER_TABLE} WHERE file_name=%s AND folder_name=%s",
                    (source_filename, doc_filter),
                )
            else:
                cur.execute(f"DELETE FROM {DOCUMENT_FOLDER_TABLE} WHERE file_name=%s", (source_filename,))
        conn.commit()

    paths_to_delete = sorted(image_paths | source_paths)
    _delete_storage_objects(paths_to_delete)
    return {
        "deleted_chunks": deleted_chunks,
        "deleted_images": len(image_paths),
        "deleted_sources": len(source_paths),
    }


def delete_documents_by_folder(folder_name: str) -> dict:
    ensure_folder_table()
    settings = get_settings()
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM transcript WHERE document_name=%s", (folder_name,))
            conn.commit()
    except Exception:
        pass
    try:
        _remove_prefix_in_bucket(settings.supabase_transcript_bucket, _safe_storage_name(folder_name))
    except Exception:
        pass
    files = list_files_by_folder(folder_name)
    deleted_docs = 0
    deleted_chunks = 0
    deleted_images = 0
    for file_name in files:
        out = delete_document(file_name, document_name=folder_name)
        if out["deleted_chunks"] > 0:
            deleted_docs += 1
        deleted_chunks += out["deleted_chunks"]
        deleted_images += out["deleted_images"]
    delete_folder(folder_name)
    return {
        "folder_name": folder_name,
        "deleted_documents": deleted_docs,
        "deleted_chunks": deleted_chunks,
        "deleted_images": deleted_images,
    }


def rename_document_set(old_document_name: str, new_document_name: str) -> dict:
    old_name = old_document_name.strip()
    new_name = new_document_name.strip()
    if not old_name or not new_name or old_name == new_name:
        return {"updated": False}

    ensure_folder_table()
    files = list_files_by_folder(old_name)
    if not files:
        return {"updated": False}

    old_root = _safe_storage_name(old_name)
    new_root = _safe_storage_name(new_name)
    old_bucket_prefix = f"{_bucket_base_url()}/{old_root}/files/"
    new_bucket_prefix = f"{_bucket_base_url()}/{new_root}/files/"

    # Move all storage objects under old document root.
    _move_prefix_objects(f"{old_root}/files", f"{new_root}/files")
    _move_prefix_objects(f"{old_root}/source", f"{new_root}/source")

    settings = get_settings()
    try:
        _move_prefix_objects_in_bucket(settings.supabase_transcript_bucket, old_root, new_root)
    except Exception:
        pass

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE {DOCUMENT_FOLDER_TABLE}
                SET folder_name = %s
                WHERE folder_name = %s
                """,
                (new_name, old_name),
            )
            try:
                cur.execute(
                    "UPDATE transcript SET document_name = %s WHERE document_name = %s",
                    (new_name, old_name),
                )
            except Exception:
                pass
            for file_name in files:
                source_storage_path = _source_storage_path(new_name, file_name)
                source_file_url = f"{_bucket_base_url()}/{source_storage_path}"
                cur.execute(
                    f"""
                    UPDATE {settings.supabase_table_name}
                    SET
                      content = REPLACE(content, %s, %s),
                      metadata = jsonb_set(
                        jsonb_set(
                          jsonb_set(
                            jsonb_set(
                              COALESCE(metadata, '{{}}'::jsonb),
                              '{{document_name}}',
                              to_jsonb(%s::text),
                              true
                            ),
                            '{{source_file_storage_path}}',
                            to_jsonb(%s::text),
                            true
                          ),
                          '{{source_file_url}}',
                          to_jsonb(%s::text),
                          true
                        ),
                        '{{bucket_url}}',
                        to_jsonb(%s::text),
                        true
                      )
                    WHERE metadata->>'source_filename' = %s
                    """,
                    (
                        old_bucket_prefix,
                        new_bucket_prefix,
                        new_name,
                        source_storage_path,
                        source_file_url,
                        _bucket_base_url(),
                        file_name,
                    ),
                )
        conn.commit()
    return {"updated": True, "old_document_name": old_name, "new_document_name": new_name}


def rename_document_file(document_name: str, old_file_name: str, new_file_name: str) -> dict:
    doc_name = document_name.strip()
    old_name = old_file_name.strip()
    new_name = new_file_name.strip()
    if not doc_name or not old_name or not new_name or old_name == new_name:
        return {"updated": False}

    old_source_path = _source_storage_path(doc_name, old_name)
    new_source_path = _source_storage_path(doc_name, new_name)
    _move_object(old_source_path, new_source_path)

    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE {DOCUMENT_FOLDER_TABLE}
                SET file_name = %s
                WHERE folder_name = %s AND file_name = %s
                """,
                (new_name, doc_name, old_name),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return {"updated": False}
            settings = get_settings()
            try:
                cur.execute(
                    "UPDATE document_chunk SET source_filename = %s WHERE source_filename = %s",
                    (new_name, old_name),
                )
            except Exception:
                pass
            cur.execute(
                f"""
                UPDATE {settings.supabase_table_name}
                SET metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(metadata, '{{}}'::jsonb),
                        '{{source_filename}}',
                        to_jsonb(%s::text),
                        true
                    ),
                    '{{document_name}}',
                    to_jsonb(%s::text),
                    true
                )
                WHERE metadata->>'source_filename' = %s
                """,
                (new_name, doc_name, old_name),
            )
            cur.execute(
                f"""
                UPDATE {settings.supabase_table_name}
                SET metadata = jsonb_set(
                    jsonb_set(
                        COALESCE(metadata, '{{}}'::jsonb),
                        '{{source_file_storage_path}}',
                        to_jsonb(%s::text),
                        true
                    ),
                    '{{source_file_url}}',
                    to_jsonb(%s::text),
                    true
                )
                WHERE metadata->>'source_filename' = %s
                """,
                (
                    new_source_path,
                    f"{_bucket_base_url()}/{new_source_path}",
                    new_name,
                ),
            )
        conn.commit()
    return {
        "updated": True,
        "document_name": doc_name,
        "old_file_name": old_name,
        "new_file_name": new_name,
    }
