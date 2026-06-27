"""WebSocket สำหรับ /ingest-pending"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.document_api.api.v1.routes.job_common import list_dashboard_pending_ingest, wait_any_events
from app.document_api.api.v1.schemas import PendingIngestEntry
from app.document_api.services.job_manager import subscribe_all_jobs, unsubscribe_all_jobs
from app.document_api.services.pending_ingest_catalog import (
    get_pending_by_id,
    is_valid_pending_id,
    subscribe_all_pending,
    subscribe_pending,
    unsubscribe_all_pending,
    unsubscribe_pending,
)

ws_router = APIRouter()


def _row_to_entry(row: dict) -> PendingIngestEntry:
    if "markdown_length" in row:
        return PendingIngestEntry(**row)
    return PendingIngestEntry(
        id=str(row["id"]),
        document_name=str(row.get("document_name") or ""),
        source_filename=str(row.get("source_filename") or ""),
        llm_summary=str(row.get("llm_summary") or ""),
        status=str(row.get("status") or ""),
        job_id=row.get("job_id"),
        created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        markdown_length=len(str(row.get("markdown_text") or "")),
    )


def _pending_ws_signature(rows: list[dict]) -> tuple[int, tuple[tuple[str, str, str, str], ...]]:
    sig: list[tuple[str, str, str, str]] = []
    for row in rows:
        sig.append(
            (
                str(row.get("id") or ""),
                str(row.get("updated_at") or ""),
                str(row.get("llm_summary") or ""),
                str(row.get("status") or ""),
            )
        )
    return len(rows), tuple(sig)


async def _wait_pending_notify(event: asyncio.Event, *, timeout: float = 1.0) -> None:
    event.clear()
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


async def _run_pending_list_ws(
    websocket: WebSocket,
    *,
    scope: str = "all",
    department_scope=None,
) -> None:
    from app.document_api.rag_department_scope import (
        RagDepartmentScope,
        list_scoped_pending_ingest,
    )

    last_signature: tuple[int, tuple[tuple[str, str, str, str], ...]] | None = None
    notify_pending = subscribe_all_pending()
    notify_jobs = subscribe_all_jobs()
    push_after_notify = True
    scoped = department_scope if isinstance(department_scope, RagDepartmentScope) else None
    try:
        while True:
            if scoped is not None:
                rows = list_scoped_pending_ingest(scoped)
            else:
                rows = list_dashboard_pending_ingest()
            sig = _pending_ws_signature(rows)
            if rows:
                if push_after_notify or sig != last_signature:
                    payload = {
                        "type": "ingest_pending",
                        "scope": scope,
                        "items": [_row_to_entry(r).model_dump(mode="json") for r in rows],
                    }
                    await websocket.send_json(payload)
                    last_signature = sig
                push_after_notify = await wait_any_events(
                    notify_pending, notify_jobs, timeout=0.5
                )
            else:
                if push_after_notify or sig != last_signature:
                    payload: dict = {"type": "ingest_pending", "scope": scope, "items": []}
                    await websocket.send_json(payload)
                    last_signature = sig
                push_after_notify = await wait_any_events(
                    notify_pending, notify_jobs, timeout=1.0
                )
    finally:
        unsubscribe_all_pending(notify_pending)
        unsubscribe_all_jobs(notify_jobs)


@ws_router.websocket("/ingest-pending/ws")
@ws_router.websocket("/ingest-pending")
async def ingest_pending_ws(
    websocket: WebSocket,
):
    from app.document_api.rag_department_scope import resolve_rag_department_scope
    from app.document_api.ws_context import bind_document_api_ws_access, ensure_document_api_ws_authorized

    await websocket.accept()
    async with bind_document_api_ws_access(websocket) as request:
        if not await ensure_document_api_ws_authorized(websocket, request):
            return
        scope_ctx = resolve_rag_department_scope()
        try:
            if scope_ctx.unrestricted:
                await _run_pending_list_ws(websocket, scope="all")
            else:
                await _run_pending_list_ws(
                    websocket,
                    scope="department",
                    department_scope=scope_ctx,
                )
        except WebSocketDisconnect:
            return


@ws_router.websocket("/ingest-pending/{pending_id}/ws")
@ws_router.websocket("/ingest-pending/{pending_id}")
async def ingest_pending_detail_ws(
    websocket: WebSocket,
    pending_id: str,
):
    from app.document_api.rag_department_scope import assert_row_accessible, resolve_rag_department_scope
    from app.document_api.ws_context import bind_document_api_ws_access, ensure_document_api_ws_authorized

    await websocket.accept()
    pid = pending_id.strip()
    async with bind_document_api_ws_access(websocket) as request:
        if not await ensure_document_api_ws_authorized(websocket, request):
            return
        scope_ctx = resolve_rag_department_scope()
        if not is_valid_pending_id(pid):
            await websocket.send_json(
                {
                    "type": "ingest_pending_item",
                    "pending_id": pid,
                    "error": "invalid pending id",
                }
            )
            await websocket.close(code=1008, reason="invalid pending id")
            return

        last_signature: tuple[str, str, str, str] | None = None
        notify = subscribe_pending(pid)
        try:
            while True:
                row = get_pending_by_id(pid)
                if row:
                    assert_row_accessible(
                        scope_ctx,
                        row.get("department_id"),
                        created_by=row.get("created_by"),
                    )
                if not row or row.get("status") != "pending" or not row.get("summary_ready"):
                    await websocket.send_json(
                        {
                            "type": "ingest_pending_item",
                            "pending_id": pid,
                            "error": "pending ingest not found",
                        }
                    )
                    last_signature = None
                    await _wait_pending_notify(notify, timeout=0.5)
                    continue
                entry = _row_to_entry(row)
                sig = (
                    str(entry.updated_at or ""),
                    entry.llm_summary,
                    entry.status,
                    str(entry.markdown_length),
                )
                if sig != last_signature:
                    payload = {
                        "type": "ingest_pending_item",
                        "item": entry.model_dump(mode="json"),
                    }
                    await websocket.send_json(payload)
                    last_signature = sig
                await _wait_pending_notify(notify, timeout=0.5)
        except WebSocketDisconnect:
            return
        finally:
            unsubscribe_pending(pid, notify)
