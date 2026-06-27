"""Regression: session title must still generate when turn 2 starts early.

Covers the race where the user sends a follow-up message while the turn-1
background title LLM call is still running.
"""

from __future__ import annotations

import contextlib
import threading
import time
from unittest.mock import MagicMock, patch

from app.domain.models import Session, title_from


def _turn1_messages(user_text: str, assistant_text: str = "Here is the answer."):
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]


def _turn2_messages(user_text: str, msg2: str, assistant2: str = "More detail."):
    return _turn1_messages(user_text) + [
        {"role": "user", "content": msg2},
        {"role": "assistant", "content": assistant2},
    ]


def test_should_schedule_background_title_on_turn2_with_provisional_title():
    from app.domain.streaming import _should_schedule_background_title

    user_text = "How do I fix authentication?"
    messages = _turn2_messages(user_text, "What about OAuth?")
    provisional = title_from(_turn1_messages(user_text), "Untitled")

    session = Session(session_id="race-turn2-provisional", title=provisional)
    session.messages = messages
    session.llm_title_generated = False

    should, user_snip, asst_snip = _should_schedule_background_title(session)

    assert should is True
    assert user_text in user_snip
    assert "Here is the answer" in asst_snip


def test_should_schedule_when_title_misassigned_to_turn2_prompt():
    from app.domain.streaming import _should_schedule_background_title

    user_text = "How do I fix authentication?"
    msg2 = "What about OAuth?"
    messages = _turn2_messages(user_text, msg2)
    wrong_title = title_from([{"role": "user", "content": msg2}], "New Chat")

    session = Session(session_id="race-misassigned-title", title=wrong_title)
    session.messages = messages
    session.llm_title_generated = False

    should, _, _ = _should_schedule_background_title(session)

    assert should is True


def test_prepare_chat_start_recovers_title_from_existing_messages(tmp_path, monkeypatch):
    from app.domain.routes import _prepare_chat_start_session_for_stream

    saved = []

    def fake_save(self, *args, **kwargs):
        saved.append(self.title)

    monkeypatch.setattr(Session, "save", fake_save)

    user_text = "How do I fix authentication?"
    msg2 = "What about OAuth?"
    s = Session(session_id="race-prepare-chat-start", title="New Chat")
    s.messages = _turn1_messages(user_text)

    _prepare_chat_start_session_for_stream(
        s,
        msg=msg2,
        attachments=[],
        workspace=str(tmp_path),
        model="test-model",
        model_provider=None,
        stream_id="stream-2",
        started_at=456.0,
    )

    assert s.title == title_from(s.messages, "Untitled")
    assert s.title != title_from([{"role": "user", "content": msg2}], "Untitled")
    assert saved[-1] == s.title


def test_background_title_routes_to_latest_stream_sink():
    from app.domain.streaming import (
        _clear_title_event_sink,
        _register_title_event_sink,
        _resolve_title_event_sink,
        _run_background_title_update,
    )

    events_turn1 = []
    events_turn2 = []

    def put1(event, data):
        events_turn1.append((event, data))

    def put2(event, data):
        events_turn2.append((event, data))

    user_text = "How do I fix authentication?"
    assistant_text = "Use OAuth2 with PKCE."
    messages = _turn1_messages(user_text, assistant_text)
    provisional = title_from(messages, "Untitled")
    llm_title = "Authentication Fix Guide"

    session = MagicMock()
    session.title = provisional
    session.llm_title_generated = False
    session.messages = messages
    session.session_id = "race-sink-session"
    session.save = MagicMock()

    with patch("app.domain.streaming.get_session", return_value=session), patch(
        "app.domain.streaming.SESSIONS", {session.session_id: session}
    ), patch("app.domain.streaming.LOCK", threading.Lock()), patch(
        "app.domain.streaming._aux_title_configured", return_value=True
    ), patch(
        "app.domain.streaming._generate_llm_session_title_via_aux",
        return_value=(llm_title, "llm_aux", llm_title),
    ), patch(
        "app.domain.streaming._get_session_agent_lock",
        return_value=contextlib.nullcontext(),
    ):
        _register_title_event_sink(session.session_id, put1)
        _register_title_event_sink(session.session_id, put2)

        _run_background_title_update(
            session_id=session.session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            placeholder_title=provisional,
            put_event=put1,
            agent=None,
        )

    title_events_turn2 = [data for event, data in events_turn2 if event == "title"]
    assert title_events_turn2
    assert title_events_turn2[0]["title"] == llm_title
    assert not any(event == "title" for event, _ in events_turn1)
    assert _resolve_title_event_sink(session.session_id, put1) is put2

    _clear_title_event_sink(session.session_id, put2)
    assert _resolve_title_event_sink(session.session_id, put1) is put1


def test_turn1_title_thread_still_writes_after_turn2_messages_added():
    from app.domain.streaming import _run_background_title_update

    user_text = "How do I fix authentication?"
    assistant_text = "Use OAuth2 with PKCE."
    llm_title = "Authentication Fix Guide"

    events = []

    def put_event(event, data):
        events.append((event, data))

    def slow_title(*_args, **_kwargs):
        time.sleep(0.05)
        return llm_title, "llm_aux", llm_title

    session = MagicMock()
    session.session_id = "race-late-write"
    session.llm_title_generated = False
    session.save = MagicMock()

    turn1_messages = _turn1_messages(user_text, assistant_text)
    provisional = title_from(turn1_messages, "Untitled")
    session.messages = list(turn1_messages)
    session.title = provisional

    def get_session_side_effect(_sid):
        return session

    with patch("app.domain.streaming.get_session", side_effect=get_session_side_effect), patch(
        "app.domain.streaming.SESSIONS", {}
    ), patch("app.domain.streaming.LOCK", threading.Lock()), patch(
        "app.domain.streaming._aux_title_configured", return_value=True
    ), patch(
        "app.domain.streaming._generate_llm_session_title_via_aux",
        side_effect=slow_title,
    ), patch(
        "app.domain.streaming._get_session_agent_lock",
        return_value=__import__("contextlib").nullcontext(),
    ):
        thread = threading.Thread(
            target=_run_background_title_update,
            kwargs={
                "session_id": session.session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "placeholder_title": provisional,
                "put_event": put_event,
                "agent": None,
            },
            daemon=True,
        )
        thread.start()

        # Simulate turn 2 completing while turn-1 title LLM is still running.
        session.messages = _turn2_messages(user_text, "What about OAuth?", "OAuth details.")
        thread.join(timeout=5)

    assert session.title == llm_title
    assert session.llm_title_generated is True
    assert any(event == "title" for event, _ in events)
