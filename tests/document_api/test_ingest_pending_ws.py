from __future__ import annotations

import asyncio

import pytest

from app.document_api.services.pending_ingest_catalog import (
    _notify_pending_changed,
    subscribe_all_pending,
    subscribe_pending,
    unsubscribe_all_pending,
    unsubscribe_pending,
)


def test_pending_notify_wakes_subscribers():
    async def _run():
        all_ev = subscribe_all_pending()
        one_ev = subscribe_pending("abc-123")
        _notify_pending_changed("abc-123")
        assert all_ev.is_set()
        assert one_ev.is_set()
        unsubscribe_all_pending(all_ev)
        unsubscribe_pending("abc-123", one_ev)

    asyncio.run(_run())


def test_pending_notify_all_only_for_global_subscriber():
    async def _run():
        all_ev = subscribe_all_pending()
        one_ev = subscribe_pending("other-id")
        all_ev.clear()
        one_ev.clear()
        _notify_pending_changed(None)
        assert all_ev.is_set()
        assert not one_ev.is_set()
        unsubscribe_all_pending(all_ev)
        unsubscribe_pending("other-id", one_ev)

    asyncio.run(_run())


def test_pending_ws_signature_includes_row_count():
    from app.document_api.api.v1.routes.ingest_pending import _pending_ws_signature

    one = _pending_ws_signature([{"id": "a", "updated_at": "1", "llm_summary": "", "status": "pending"}])
    two = _pending_ws_signature(
        [
            {"id": "a", "updated_at": "1", "llm_summary": "", "status": "pending"},
            {"id": "b", "updated_at": "1", "llm_summary": "", "status": "pending"},
        ]
    )
    assert one[0] == 1
    assert two[0] == 2
    assert one != two


def test_ingest_pending_ws_uses_department_scoped_rows():
    from unittest.mock import patch

    from app.document_api.api.v1.routes.ingest_pending import _run_pending_list_ws
    from app.document_api.rag_department_scope import RagDepartmentScope

    hr_scope = RagDepartmentScope(unrestricted=False, department_id="hr")
    sample_rows = [
        {
            "id": "abc",
            "document_name": "docs",
            "source_filename": "a.pdf",
            "llm_summary": "summary",
            "status": "pending",
            "updated_at": "1",
            "markdown_text": "x",
        }
    ]

    class _FakeWebSocket:
        sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    ws = _FakeWebSocket()

    async def _break_after_first_wait(*_args, **_kwargs):
        raise asyncio.CancelledError()

    async def _run():
        with patch(
            "app.document_api.rag_department_scope.list_scoped_pending_ingest",
            return_value=sample_rows,
        ) as scoped_list, patch(
            "app.document_api.api.v1.routes.ingest_pending.wait_any_events",
            side_effect=_break_after_first_wait,
        ):
            with pytest.raises(asyncio.CancelledError):
                await _run_pending_list_ws(ws, scope="department", department_scope=hr_scope)
            scoped_list.assert_called_once_with(hr_scope)

    asyncio.run(_run())
    assert ws.sent
    payload = ws.sent[0]
    assert payload["type"] == "ingest_pending"
    assert payload["scope"] == "department"
    assert len(payload["items"]) == 1


def test_wait_any_events_returns_true_when_already_set():
    async def _run():
        ev = asyncio.Event()
        ev.set()
        assert await wait_any_events(ev, timeout=0.01) is True
        assert not ev.is_set()

    from app.document_api.api.v1.routes.job_common import wait_any_events

    asyncio.run(_run())
