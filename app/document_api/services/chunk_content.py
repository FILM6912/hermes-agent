from __future__ import annotations

import hashlib
import json
from typing import Any

from app.document_api.core.config import get_settings
from app.document_api.core.storage_urls import rewrite_storage_urls_in_row
from app.document_api.services.document_pipeline import _vector_table_ident


def _pg_conn():
    import psycopg2

    s = get_settings()
    return psycopg2.connect(
        host=s.pg_host,
        port=s.pg_port,
        dbname=s.pg_database,
        user=s.pg_user,
        password=s.pg_password,
        sslmode=s.pg_sslmode,
    )


def _table() -> str:
    return _vector_table_ident(get_settings().supabase_table_name)


def _file_where_clause() -> str:
    return """
    metadata->>'source_filename' = %s
    AND (document_name = %s OR (metadata->>'document_name') = %s)
    """


def list_chunks_for_file(source_filename: str, document_name: str) -> list[dict[str, Any]]:
    doc = document_name.strip()
    src = source_filename.strip()
    sql = f"""
    SELECT id::text, content, chunk_index, token_count, metadata, document_name,
           created_by, updated_by, created_at::text, updated_at::text
    FROM {_table()}
    WHERE {_file_where_clause()}
    ORDER BY chunk_index NULLS LAST, id
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (src, doc, doc))
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        cid, content, cidx, tok, meta, dname, cb, ub, ca, ua = row
        meta_d = meta if isinstance(meta, dict) else {}
        body = content or ""
        out.append(
            rewrite_storage_urls_in_row(
                {
                    "id": cid,
                    "chunk_index": int(cidx) if cidx is not None else None,
                    "token_count": int(tok) if tok is not None else 0,
                    "document_name": dname,
                    "content": body,
                    "metadata": meta_d,
                    "created_by": cb,
                    "updated_by": ub,
                    "created_at": ca,
                    "updated_at": ua,
                }
            )
        )
    return out


def get_chunk_by_id(
    chunk_id: str,
    *,
    source_filename: str,
    document_name: str,
) -> dict[str, Any] | None:
    doc = document_name.strip()
    src = source_filename.strip()
    sql = f"""
    SELECT id::text, content, chunk_index, token_count, metadata, document_name,
           created_by, updated_by, created_at::text, updated_at::text
    FROM {_table()}
    WHERE id = %s::uuid AND {_file_where_clause()}
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (chunk_id, src, doc, doc))
            row = cur.fetchone()
    if not row:
        return None
    cid, content, cidx, tok, meta, dname, cb, ub, ca, ua = row
    return rewrite_storage_urls_in_row(
        {
            "id": cid,
            "content": content or "",
            "chunk_index": int(cidx) if cidx is not None else None,
            "token_count": int(tok) if tok is not None else 0,
            "document_name": dname,
            "metadata": meta if isinstance(meta, dict) else {},
            "created_by": cb,
            "updated_by": ub,
            "created_at": ca,
            "updated_at": ua,
        }
    )


def _next_chunk_index(cur, source_filename: str, document_name: str) -> int:
    doc = document_name.strip()
    src = source_filename.strip()
    cur.execute(
        f"""
        SELECT COALESCE(MAX(chunk_index), -1) + 1
        FROM {_table()}
        WHERE {_file_where_clause()}
        """,
        (src, doc, doc),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _template_metadata(cur, source_filename: str, document_name: str) -> dict[str, Any]:
    doc = document_name.strip()
    src = source_filename.strip()
    cur.execute(
        f"""
        SELECT metadata FROM {_table()}
        WHERE {_file_where_clause()}
        ORDER BY chunk_index NULLS LAST
        LIMIT 1
        """,
        (src, doc, doc),
    )
    row = cur.fetchone()
    if row and row[0] and isinstance(row[0], dict):
        base = dict(row[0])
        base["source_filename"] = src
        base["document_name"] = doc
        return base
    return {"source_filename": src, "document_name": doc}


def create_chunk(
    *,
    source_filename: str,
    document_name: str,
    content: str,
    chunk_index: int | None,
    re_embed: bool,
    embeddings: Any | None,
    actor_username: str | None = None,
) -> dict[str, Any]:
    from app.document_api.services.document_pipeline import _embed_with_error, estimate_token_count

    doc = document_name.strip()
    src = source_filename.strip()
    body = content or ""
    tok = estimate_token_count(body)
    chash = hashlib.md5(body.encode()).hexdigest()

    conn = _pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                meta = _template_metadata(cur, src, doc)
                idx = int(chunk_index) if chunk_index is not None else _next_chunk_index(cur, src, doc)
                meta["chunk_index"] = idx
                meta["token_count"] = tok
                meta["content_hash"] = chash

                vec_str: str | None = None
                emb_err: str | None = None
                if re_embed and embeddings is not None:
                    vec, emb_err = _embed_with_error(embeddings, body)
                    if vec:
                        vec_str = f"[{','.join(str(float(x)) for x in vec)}]"

                if vec_str:
                    cur.execute(
                        f"""
                        INSERT INTO {_table()}
                          (content, document_name, chunk_index, token_count, created_by, updated_by, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                        RETURNING id::text
                        """,
                        (
                            body,
                            doc,
                            idx,
                            tok,
                            actor_username,
                            actor_username,
                            json.dumps(meta, ensure_ascii=False),
                            vec_str,
                        ),
                    )
                else:
                    cur.execute(
                        f"""
                        INSERT INTO {_table()}
                          (content, document_name, chunk_index, token_count, created_by, updated_by, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NULL)
                        RETURNING id::text
                        """,
                        (
                            body,
                            doc,
                            idx,
                            tok,
                            actor_username,
                            actor_username,
                            json.dumps(meta, ensure_ascii=False),
                        ),
                    )
                new_id = cur.fetchone()[0]
        return {
            "id": new_id,
            "chunk_index": idx,
            "token_count": tok,
            "embedding_applied": bool(vec_str),
            "embedding_error": emb_err,
        }
    finally:
        conn.close()


def update_chunk(
    *,
    chunk_id: str,
    source_filename: str,
    document_name: str,
    content: str | None,
    re_embed: bool,
    embeddings: Any | None,
    actor_username: str | None = None,
) -> dict[str, Any] | None:
    from app.document_api.services.document_pipeline import _embed_with_error, estimate_token_count

    doc = document_name.strip()
    src = source_filename.strip()
    conn = _pg_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT content, metadata FROM {_table()}
                    WHERE id = %s::uuid AND {_file_where_clause()}
                    """,
                    (chunk_id, src, doc, doc),
                )
                row = cur.fetchone()
                if not row:
                    return None
                old_content, meta = row
                meta_d = dict(meta) if isinstance(meta, dict) else {}
                new_body = content if content is not None else (old_content or "")
                tok = estimate_token_count(new_body)
                meta_d["token_count"] = tok
                meta_d["content_hash"] = hashlib.md5(new_body.encode()).hexdigest()

                emb_err: str | None = None
                emb_applied = False
                params_base = (
                    new_body,
                    tok,
                    json.dumps(meta_d, ensure_ascii=False),
                    actor_username,
                    chunk_id,
                    src,
                    doc,
                    doc,
                )

                if re_embed and embeddings is not None:
                    vec, emb_err = _embed_with_error(embeddings, new_body)
                    if vec:
                        vec_str = f"[{','.join(str(float(x)) for x in vec)}]"
                        cur.execute(
                            f"""
                            UPDATE {_table()}
                            SET content = %s, token_count = %s, metadata = %s::jsonb,
                                embedding = %s::vector, updated_by = %s, updated_at = NOW()
                            WHERE id = %s::uuid AND {_file_where_clause()}
                            RETURNING id::text, chunk_index
                            """,
                            (
                                new_body,
                                tok,
                                json.dumps(meta_d, ensure_ascii=False),
                                vec_str,
                                actor_username,
                                chunk_id,
                                src,
                                doc,
                                doc,
                            ),
                        )
                        emb_applied = True
                    else:
                        cur.execute(
                            f"""
                            UPDATE {_table()}
                            SET content = %s, token_count = %s, metadata = %s::jsonb,
                                embedding = NULL, updated_by = %s, updated_at = NOW()
                            WHERE id = %s::uuid AND {_file_where_clause()}
                            RETURNING id::text, chunk_index
                            """,
                            params_base,
                        )
                else:
                    cur.execute(
                        f"""
                        UPDATE {_table()}
                        SET content = %s, token_count = %s, metadata = %s::jsonb,
                            updated_by = %s, updated_at = NOW()
                        WHERE id = %s::uuid AND {_file_where_clause()}
                        RETURNING id::text, chunk_index
                        """,
                        params_base,
                    )
                out = cur.fetchone()
                if not out:
                    return None
                return {
                    "id": out[0],
                    "chunk_index": int(out[1]) if out[1] is not None else None,
                    "token_count": tok,
                    "embedding_applied": emb_applied,
                    "embedding_error": emb_err,
                }
    finally:
        conn.close()


def delete_chunk(
    *,
    chunk_id: str,
    source_filename: str,
    document_name: str,
) -> bool:
    doc = document_name.strip()
    src = source_filename.strip()
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {_table()}
                WHERE id = %s::uuid AND {_file_where_clause()}
                """,
                (chunk_id, src, doc, doc),
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()
