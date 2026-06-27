from __future__ import annotations

from typing import Iterable

from app.document_api.core.config import get_settings
from app.document_api.core.storage_urls import public_storage_bucket_base
from app.document_api.services.document_pipeline import _safe_storage_name


TABLE_NAME = "document_folder"


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


def ensure_folder_table() -> None:
    migrate = """
    DO $m$
    BEGIN
      IF to_regclass('public.document_folder_files') IS NOT NULL
         AND to_regclass('public.document_folder') IS NULL THEN
        ALTER TABLE public.document_folder_files RENAME TO document_folder;
      END IF;
    END $m$;
    """
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id BIGSERIAL PRIMARY KEY,
        folder_name TEXT NOT NULL,
        file_name TEXT NOT NULL,
        created_by TEXT,
        updated_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (folder_name, file_name)
    )
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(migrate)
            cur.execute(ddl)
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS created_by TEXT")
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS updated_by TEXT")
            cur.execute(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cur.execute(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS llm_summary TEXT")
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS department_id TEXT")
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS approved_by TEXT")
            cur.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ")
            cur.execute(
                f"""
                UPDATE {TABLE_NAME}
                SET approved_by = updated_by,
                    approved_at = updated_at
                WHERE approved_by IS NULL
                  AND updated_by IS NOT NULL
                """
            )
        conn.commit()


def _ensure_department_id_column() -> None:
    ensure_folder_table()

def update_folder_file_summary(
    folder_name: str,
    file_name: str,
    summary: str,
    *,
    actor_username: str | None = None,
) -> bool:
    folder = (folder_name or "").strip()
    src = (file_name or "").strip()
    if not folder or not src:
        return False
    ensure_folder_table()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE_NAME}
                SET llm_summary = %s,
                    updated_by = COALESCE(%s, updated_by),
                    updated_at = NOW()
                WHERE folder_name = %s AND file_name = %s
                """,
                (summary, actor_username, folder, src),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def insert_folder_files(
    rows: Iterable[tuple[str, str]],
    *,
    actor_username: str | None = None,
    uploaded_by: str | None = None,
    approved_by: str | None = None,
    record_approval: bool = False,
    llm_summaries: dict[tuple[str, str], str] | None = None,
    department_id: str | None = None,
) -> int:
    rows = [(folder.strip(), file_name.strip()) for folder, file_name in rows if folder.strip() and file_name.strip()]
    if not rows:
        return 0

    _ensure_department_id_column()
    summaries = llm_summaries or {}
    dept = (department_id or "").strip().lower() or None
    created_by = (uploaded_by or actor_username or "").strip() or None
    updated_by = (actor_username or approved_by or uploaded_by or "").strip() or None

    value_groups: list[str] = []
    flat_params: list[str | None] = []
    for folder_name, file_name in rows:
        summary = summaries.get((folder_name, file_name))
        approver = (approved_by or (actor_username if record_approval else None) or "").strip() or None
        if approver:
            value_groups.append("(%s, %s, %s, %s, %s, %s, %s, NOW())")
        else:
            value_groups.append("(%s, %s, %s, %s, %s, %s, %s, NULL)")
        flat_params.extend(
            [
                folder_name,
                file_name,
                created_by,
                updated_by,
                summary,
                dept,
                approver,
            ]
        )

    sql = f"""
    INSERT INTO {TABLE_NAME} (
        folder_name, file_name, created_by, updated_by, llm_summary, department_id, approved_by, approved_at
    )
    VALUES {", ".join(value_groups)}
    ON CONFLICT (folder_name, file_name) DO UPDATE SET
      created_by = COALESCE({TABLE_NAME}.created_by, EXCLUDED.created_by),
      updated_by = COALESCE(EXCLUDED.updated_by, {TABLE_NAME}.updated_by),
      llm_summary = COALESCE(EXCLUDED.llm_summary, {TABLE_NAME}.llm_summary),
      department_id = COALESCE({TABLE_NAME}.department_id, EXCLUDED.department_id),
      approved_by = COALESCE(EXCLUDED.approved_by, {TABLE_NAME}.approved_by),
      approved_at = COALESCE(EXCLUDED.approved_at, {TABLE_NAME}.approved_at),
      updated_at = NOW()
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, flat_params)
            inserted = cur.rowcount
        conn.commit()
    return inserted


def list_folder_files(*, department_id: str | None = None) -> list[dict]:
    _ensure_department_id_column()
    dept = (department_id or "").strip().lower()
    if dept:
        sql = f"""
        SELECT id, folder_name, file_name, created_by, updated_by, created_at, updated_at,
               llm_summary, department_id, approved_by, approved_at
        FROM {TABLE_NAME}
        WHERE department_id = %s
        ORDER BY folder_name ASC, file_name ASC
        """
        params: tuple[str, ...] = (dept,)
    else:
        sql = f"""
        SELECT id, folder_name, file_name, created_by, updated_by, created_at, updated_at,
               llm_summary, department_id, approved_by, approved_at
        FROM {TABLE_NAME}
        ORDER BY folder_name ASC, file_name ASC
        """
        params = ()
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    out = []
    for row in rows:
        (
            file_id,
            folder_name,
            file_name,
            cb,
            ub,
            ca,
            ua,
            llm_summary,
            row_dept,
            approved_by,
            approved_at,
        ) = row
        out.append(
            {
                "id": int(file_id),
                "folder_name": folder_name,
                "file_name": file_name,
                "created_by": cb,
                "updated_by": ub,
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else (str(ca) if ca else None),
                "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else (str(ua) if ua else None),
                "llm_summary": llm_summary or "",
                "department_id": row_dept,
                "approved_by": approved_by,
                "approved_at": approved_at.isoformat()
                if hasattr(approved_at, "isoformat")
                else (str(approved_at) if approved_at else None),
            }
        )
    return out


def folder_exists(folder_name: str) -> bool:
    sql = f"SELECT 1 FROM {TABLE_NAME} WHERE folder_name=%s LIMIT 1"
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name,))
            return cur.fetchone() is not None


def list_files_by_folder(folder_name: str) -> list[str]:
    sql = f"""
    SELECT file_name
    FROM {TABLE_NAME}
    WHERE folder_name=%s
    ORDER BY file_name ASC
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name,))
            rows = cur.fetchall()
    return [file_name for (file_name,) in rows]


def list_file_records_by_folder(folder_name: str) -> list[dict]:
    sql = f"""
    SELECT id, file_name, created_by, updated_by, created_at, updated_at, llm_summary, approved_by, approved_at
    FROM {TABLE_NAME}
    WHERE folder_name=%s
    ORDER BY file_name ASC
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name,))
            rows = cur.fetchall()
    settings = get_settings()
    bucket_base = public_storage_bucket_base(settings.supabase_storage_bucket, settings)
    out = []
    for row in rows:
        file_id, file_name, cb, ub, ca, ua, llm_summary, approved_by, approved_at = row
        out.append(
            {
                "id": int(file_id),
                "file_name": file_name,
                "created_by": cb,
                "updated_by": ub,
                "created_at": ca.isoformat() if hasattr(ca, "isoformat") else (str(ca) if ca else None),
                "updated_at": ua.isoformat() if hasattr(ua, "isoformat") else (str(ua) if ua else None),
                "source_file_url": f"{bucket_base}/{_safe_storage_name(folder_name)}/source/{_safe_storage_name(file_name)}",
                "llm_summary": llm_summary or "",
                "approved_by": approved_by,
                "approved_at": approved_at.isoformat()
                if hasattr(approved_at, "isoformat")
                else (str(approved_at) if approved_at else None),
            }
        )
    return out


def file_exists_in_folder(folder_name: str, file_name: str) -> bool:
    sql = f"""
    SELECT 1
    FROM {TABLE_NAME}
    WHERE folder_name=%s AND file_name=%s
    LIMIT 1
    """
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name, file_name))
            return cur.fetchone() is not None


def delete_folder(folder_name: str) -> int:
    sql = f"DELETE FROM {TABLE_NAME} WHERE folder_name=%s"
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name,))
            deleted = cur.rowcount
        conn.commit()
    return deleted


def delete_file_from_folder(folder_name: str, file_name: str) -> int:
    sql = f"DELETE FROM {TABLE_NAME} WHERE folder_name=%s AND file_name=%s"
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (folder_name, file_name))
            deleted = cur.rowcount
        conn.commit()
    return deleted


def replace_folder_files(folder_name: str, files: list[str], *, actor_username: str | None = None) -> int:
    cleaned_files = [f.strip() for f in files if f.strip()]
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE_NAME} WHERE folder_name=%s", (folder_name,))
            deleted = cur.rowcount
            if cleaned_files:
                values_sql = ",".join(["(%s, %s, %s, %s)"] * len(cleaned_files))
                flattened: list[str | None] = []
                for file_name in cleaned_files:
                    flattened.extend([folder_name, file_name, actor_username, actor_username])
                cur.execute(
                    f"""
                    INSERT INTO {TABLE_NAME} (folder_name, file_name, created_by, updated_by)
                    VALUES {values_sql}
                    ON CONFLICT (folder_name, file_name) DO UPDATE SET
                      created_by = COALESCE({TABLE_NAME}.created_by, EXCLUDED.created_by),
                      updated_by = COALESCE(EXCLUDED.updated_by, {TABLE_NAME}.updated_by),
                      updated_at = NOW()
                    """,
                    flattened,
                )
        conn.commit()
    return deleted
