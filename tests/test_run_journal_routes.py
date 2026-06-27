from pathlib import Path
from types import SimpleNamespace
import io


ROOT = Path(__file__).resolve().parents[1]
ROUTES_SRC = (ROOT / "app" / "domain" / "routes.py").read_text()
CHAT_STREAMING_SRC = (ROOT / "app" / "domain" / "chat_streaming.py").read_text()
CHAT_STREAM_SRC = (ROOT / "app" / "services" / "chat_stream.py").read_text()


def test_stream_status_exposes_replay_summary():
    status_pos = ROUTES_SRC.index('parsed.path == "/api/chat/stream/status"')
    routes_block = ROUTES_SRC[status_pos : status_pos + 400]
    owner_block = CHAT_STREAMING_SRC[
        CHAT_STREAMING_SRC.index("def chat_stream_status_payload") :
        CHAT_STREAMING_SRC.index("def chat_stream_status_payload") + 1200
    ]

    assert "chat_stream_status_payload" in routes_block
    assert "find_run_summary(stream_id)" in owner_block
    assert '"replay_available"' in owner_block
    assert '"journal"' in owner_block
    assert "run_journal_status_payload" in owner_block


def test_dead_stream_sse_replays_journal_before_404_fallback():
    handler_pos = ROUTES_SRC.index("def _handle_sse_stream")
    routes_block = ROUTES_SRC[handler_pos : handler_pos + 400]
    service_block = CHAT_STREAMING_SRC[
        CHAT_STREAMING_SRC.index("def write_legacy_chat_sse_stream") :
        CHAT_STREAMING_SRC.index("def write_legacy_chat_sse_stream") + 2600
    ]

    assert "write_legacy_chat_sse_stream" in routes_block
    assert "journal_replay_available(stream_id)" in service_block
    assert "stream not found" in service_block
    assert "iter_journal_replay_bytes" in service_block
    assert "parse_after_seq" in service_block
    assert "SSE_RESPONSE_HEADERS" in CHAT_STREAMING_SRC
    assert "text/event-stream; charset=utf-8" in CHAT_STREAMING_SRC
    assert "from app.domain.chat_streaming import" in CHAT_STREAM_SRC


def test_replay_emits_event_ids_and_stale_restart_diagnostic():
    replay_pos = CHAT_STREAMING_SRC.index("def iter_journal_replay_bytes")
    block = CHAT_STREAMING_SRC[replay_pos : replay_pos + 1600]

    assert "_read_run_events" in block
    assert "format_sse_event" in block
    assert "_stale_interrupted_event" in block


def test_session_payload_exposes_runtime_journal_for_stale_streams():
    assert "original_stream_id = getattr(s, \"active_stream_id\", None)" in ROUTES_SRC
    assert '"runtime_journal"' in ROUTES_SRC
    assert 'terminal_state = "lost-worker-bookkeeping"' in CHAT_STREAMING_SRC


def test_status_payload_marks_non_terminal_dead_journal_as_stale():
    from app.domain.chat_streaming import run_journal_status_payload

    payload = run_journal_status_payload(
        {
            "session_id": "session_1",
            "run_id": "run_1",
            "last_seq": 3,
            "last_event_id": "run_1:3",
            "last_event": "token",
            "terminal": False,
            "terminal_state": "running",
        },
        active=False,
    )

    assert payload["terminal"] is False
    assert payload["terminal_state"] == "lost-worker-bookkeeping"
    assert payload["last_event_id"] == "run_1:3"


def test_status_payload_preserves_terminal_error_state():
    from app.domain.chat_streaming import run_journal_status_payload

    payload = run_journal_status_payload(
        {
            "session_id": "session_1",
            "run_id": "run_1",
            "terminal": True,
            "terminal_state": "interrupted-by-crash",
            "last_event": "apperror",
        },
        active=False,
    )

    assert payload["terminal"] is True
    assert payload["terminal_state"] == "interrupted-by-crash"


def test_replay_run_journal_writes_replayed_events_and_synthetic_terminal(monkeypatch):
    import app.domain.chat_streaming as chat_streaming
    import app.domain.routes as routes

    handler = SimpleNamespace(wfile=io.BytesIO())
    monkeypatch.setattr(
        chat_streaming,
        "_find_run_summary",
        lambda stream_id: {
            "session_id": "session_1",
            "run_id": stream_id,
            "terminal": False,
        },
    )
    monkeypatch.setattr(
        chat_streaming,
        "_read_run_events",
        lambda session_id, run_id, after_seq=None: {
            "events": [
                {
                    "event": "token",
                    "payload": {"text": "hello"},
                    "event_id": f"{run_id}:1",
                }
            ]
        },
    )
    monkeypatch.setattr(
        chat_streaming,
        "_stale_interrupted_event",
        lambda session_id, run_id, after_seq=None: {
            "event": "apperror",
            "payload": {"type": "interrupted"},
            "event_id": f"{run_id}:2",
        },
    )

    assert routes._replay_run_journal(handler, "run_1", 0) is True
    body = handler.wfile.getvalue().decode("utf-8")
    assert "id: run_1:1\n" in body
    assert "event: token\n" in body
    assert "id: run_1:2\n" in body
    assert "event: apperror\n" in body


def test_replay_run_journal_honors_after_seq_cursor(monkeypatch):
    import app.domain.chat_streaming as chat_streaming
    import app.domain.routes as routes

    captured = {}
    handler = SimpleNamespace(wfile=io.BytesIO())
    monkeypatch.setattr(
        chat_streaming,
        "_find_run_summary",
        lambda stream_id: {
            "session_id": "session_1",
            "run_id": stream_id,
            "terminal": True,
        },
    )

    def fake_read_run_events(session_id, run_id, after_seq=None):
        captured["after_seq"] = after_seq
        return {
            "events": [
                {
                    "event": "done",
                    "payload": {"session": {"session_id": session_id}},
                    "event_id": f"{run_id}:4",
                }
            ]
        }

    monkeypatch.setattr(chat_streaming, "_read_run_events", fake_read_run_events)

    assert routes._replay_run_journal(handler, "run_1", 3) is True
    assert captured["after_seq"] == 3
    body = handler.wfile.getvalue().decode("utf-8")
    assert "id: run_1:4\n" in body
    assert "event: done\n" in body
