"""Async job watcher notifications must work from worker threads."""

from __future__ import annotations

import asyncio
import threading

from app.document_api.services.job_manager import (
    _capture_watch_loop,
    _signal_asyncio_event,
    subscribe_all_jobs,
    unsubscribe_all_jobs,
)


def test_signal_asyncio_event_from_worker_thread():
    async def _run() -> None:
        ev = subscribe_all_jobs()
        _capture_watch_loop()
        loop = asyncio.get_running_loop()
        loop.call_soon(_capture_watch_loop)

        def worker() -> None:
            _signal_asyncio_event(ev)

        thread = threading.Thread(target=worker)
        thread.start()
        await asyncio.wait_for(ev.wait(), timeout=1.0)
        thread.join()
        unsubscribe_all_jobs(ev)

    asyncio.run(_run())


def test_wait_any_events_does_not_drop_already_set_event():
    from app.document_api.api.v1.routes.job_common import wait_any_events

    async def _run() -> None:
        ev = asyncio.Event()
        ev.set()
        await wait_any_events(ev, timeout=0.01)
        assert not ev.is_set()

    asyncio.run(_run())
