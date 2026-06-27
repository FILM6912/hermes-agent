"""Regression test for stage-364 Opus-caught SHOULD-FIX (side-channel approach):

When the live SSE stream errors mid-stream and the frontend falls back to
journal replay, live frames must carry an `id:` field so the frontend's
`_lastRunJournalSeq` cursor advances during the live phase. Otherwise replay
arrives with `after_seq=0` and the server replays every journaled event from
seq 1, double-rendering tokens against the live-phase `assistantText`
accumulator.

Implementation (stage-364 — side-channel approach to avoid breaking the
queue tuple contract used by 4 existing tests):

  - api/config.py adds `STREAM_LAST_EVENT_ID: dict = {}` module-level dict.
  - api/streaming.py `put()` captures `journaled["event_id"]` from
    `RunJournalWriter.append_sse_event()` return and writes it to
    `STREAM_LAST_EVENT_ID[stream_id]`.
  - app/domain/chat_streaming.py reads ``STREAM_LAST_EVENT_ID[stream_id]`` at
    SSE emit time and includes ``id:`` in formatted frames.
  - api/streaming.py finally-block cleanup pops STREAM_LAST_EVENT_ID.

The queue tuple shape is preserved as (event, data), so existing tests like
test_cancel_puts_sentinel_in_queue still work.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STREAMING_PY = (REPO_ROOT / "app" / "domain" / "streaming.py").read_text(encoding="utf-8")
ROUTES_PY = (REPO_ROOT / "app" / "domain" / "routes.py").read_text(encoding="utf-8")
CHAT_STREAM_PY = (REPO_ROOT / "app" / "domain" / "chat_streaming.py").read_text(encoding="utf-8")
CONFIG_PY = (REPO_ROOT / "app" / "domain" / "config.py").read_text(encoding="utf-8")


def test_stream_last_event_id_dict_exists_in_config():
    """`STREAM_LAST_EVENT_ID` must be declared as a module-level dict in
    api/config.py alongside the other STREAM_* registries."""
    assert "STREAM_LAST_EVENT_ID: dict = {}" in CONFIG_PY, (
        "STREAM_LAST_EVENT_ID dict missing from api/config.py — needed as "
        "the side-channel that lets SSE consumers emit `id:` on live frames"
    )


def test_put_writes_event_id_to_side_channel_dict():
    """The `put()` helper must capture the event_id from the journal and
    write it to STREAM_LAST_EVENT_ID[stream_id]."""
    put_def_idx = STREAMING_PY.find("def put(event, data):")
    assert put_def_idx != -1, "put(event, data) not found in api/streaming.py"
    put_body = STREAMING_PY[put_def_idx:put_def_idx + 2500]
    assert "journaled = run_journal.append_sse_event(event, data)" in put_body, (
        "put() must capture append_sse_event return value"
    )
    assert "STREAM_LAST_EVENT_ID[stream_id]" in put_body, (
        "put() must write event_id to STREAM_LAST_EVENT_ID[stream_id] — "
        "this is the side-channel the SSE consumer reads at emit time"
    )


def test_queue_tuple_shape_preserved_as_two_tuple():
    """The queue still uses 2-tuples (event, data) so existing consumers
    that unpack `event, data = q.get()` are not broken."""
    put_def_idx = STREAMING_PY.find("def put(event, data):")
    put_body = STREAMING_PY[put_def_idx:put_def_idx + 2500]
    assert "q.put_nowait((event, data))" in put_body, (
        "Queue tuple shape must remain (event, data) — changing to 3-tuple "
        "breaks 4 existing tests in test_cancel_interrupt, test_sprint42, "
        "test_sprint51, test_issue1857_usage_overwrite"
    )


def test_sse_handler_reads_event_id_from_side_channel():
    """The native chat SSE service must read STREAM_LAST_EVENT_ID and emit id:."""
    live_idx = CHAT_STREAM_PY.find("def iter_live_chat_stream_bytes")
    assert live_idx != -1, "iter_live_chat_stream_bytes not found"
    live_body = CHAT_STREAM_PY[live_idx : live_idx + 2000]
    assert "STREAM_LAST_EVENT_ID.get(stream_id)" in live_body, (
        "iter_live_chat_stream_bytes must read STREAM_LAST_EVENT_ID[stream_id]"
    )
    assert "format_sse_event(event, data, event_id)" in live_body, (
        "iter_live_chat_stream_bytes must pass event_id into format_sse_event"
    )


def test_cleanup_pops_stream_last_event_id():
    """The streaming worker's finally block must pop STREAM_LAST_EVENT_ID
    alongside the other STREAM_* dicts to prevent memory leak."""
    # Find the cleanup block — multiple .pop(stream_id, None) lines
    cleanup_idx = STREAMING_PY.find("STREAM_LIVE_TOOL_CALLS.pop(stream_id, None)")
    assert cleanup_idx != -1, "cleanup block not found"
    cleanup_block = STREAMING_PY[cleanup_idx:cleanup_idx + 500]
    assert "STREAM_LAST_EVENT_ID.pop(stream_id, None)" in cleanup_block, (
        "STREAM_LAST_EVENT_ID must be popped on worker finally to prevent "
        "unbounded memory growth across streams"
    )


def test_imports_present():
    """STREAM_LAST_EVENT_ID must be imported in streaming.py (writer) and chat service (reader)."""
    assert "STREAM_LAST_EVENT_ID," in STREAMING_PY, "streaming.py must import"
    assert "STREAM_LAST_EVENT_ID" in CHAT_STREAM_PY, "chat_streaming must read side-channel"
