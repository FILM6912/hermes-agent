"""Tests for app.domain.session_persistence (c2 PR1 facade)."""

import json

import pytest

import app.domain.config as config
import app.domain.models as models
from app.domain.models import Session, new_session
from app.domain.session_persistence import (
    load_session_with_recovery,
    persist_session,
    write_shrink_guard_backup,
)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    index_file = session_dir / "_index.json"
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", index_file)
    monkeypatch.setattr(config, "SESSION_INDEX_FILE", index_file, raising=False)
    models.SESSIONS.clear()
    yield session_dir
    models.SESSIONS.clear()


def test_write_shrink_guard_backup_on_shrinking_save(_isolate_state):
    s = new_session()
    s.messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    persist_session(s)
    bak = s.path.with_suffix(".json.bak")
    assert not bak.exists()

    s.messages = [{"role": "user", "content": "a"}]
    persist_session(s)
    assert bak.exists()
    bak_data = json.loads(bak.read_text(encoding="utf-8"))
    assert len(bak_data.get("messages") or []) == 2


def test_load_session_with_recovery_restores_from_bak(_isolate_state):
    sid = "abc123"
    live = _isolate_state / f"{sid}.json"
    live.write_text(
        json.dumps(
            {
                "session_id": sid,
                "title": "t",
                "messages": [{"role": "user", "content": "0"}],
                "tool_calls": [],
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    bak = _isolate_state / f"{sid}.json.bak"
    bak.write_text(
        json.dumps(
            {
                "session_id": sid,
                "title": "t",
                "messages": [
                    {"role": "user", "content": "0"},
                    {"role": "assistant", "content": "1"},
                    {"role": "user", "content": "2"},
                ],
                "tool_calls": [],
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_session_with_recovery(sid)
    assert loaded is not None
    assert len(loaded.messages) == 3
    assert len(json.loads(live.read_text(encoding="utf-8")).get("messages") or []) == 3


def test_persist_session_refuses_metadata_only_stub(_isolate_state):
    s = new_session()
    s.messages = [{"role": "user", "content": "hi"}]
    persist_session(s)
    stub = Session.load_metadata_only(s.session_id)
    assert stub is not None
    with pytest.raises(RuntimeError, match="metadata-only"):
        persist_session(stub)
