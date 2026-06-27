"""Unit tests for FastAPI phase 4 memory/upload services."""

from __future__ import annotations


def test_memory_service_read_returns_expected_keys(tmp_path, monkeypatch):
    from app.services.memory import MemoryService

    home = tmp_path / "hermes"
    mem_dir = home / "memories"
    mem_dir.mkdir(parents=True)
    (mem_dir / "MEMORY.md").write_text("agent notes", encoding="utf-8")
    (mem_dir / "USER.md").write_text("user profile", encoding="utf-8")
    (home / "SOUL.md").write_text("persona", encoding="utf-8")

    monkeypatch.setattr(
        "app.repositories.memory.MemoryRepository._memory_paths",
        lambda self: (
            mem_dir / "MEMORY.md",
            mem_dir / "USER.md",
            home / "SOUL.md",
        ),
    )
    monkeypatch.setattr(
        "app.domain.routes._external_notes_sources_enabled",
        lambda config_data=None: False,
    )

    payload = MemoryService().read_memory()
    assert payload["memory"] == "agent notes"
    assert payload["user"] == "user profile"
    assert payload["soul"] == "persona"
    assert payload["external_notes_enabled"] is False
    assert payload["memory_path"].endswith("MEMORY.md")


def test_memory_service_write_rejects_invalid_section():
    from app.services.memory import MemoryService

    payload, status = MemoryService().write_memory(section="invalid", content="x")
    assert status == 400
    assert "section must be" in payload["error"]


def test_memory_service_write_persists_section(tmp_path, monkeypatch):
    from app.services.memory import MemoryService

    home = tmp_path / "hermes"
    mem_dir = home / "memories"
    mem_dir.mkdir(parents=True)
    mem_file = mem_dir / "MEMORY.md"
    user_file = mem_dir / "USER.md"
    soul_file = home / "SOUL.md"

    monkeypatch.setattr(
        "app.repositories.memory.MemoryRepository._memory_paths",
        lambda self: (mem_file, user_file, soul_file),
    )

    payload, status = MemoryService().write_memory(section="memory", content="updated")
    assert status is None
    assert payload == {"ok": True, "section": "memory", "path": str(mem_file)}
    assert mem_file.read_text(encoding="utf-8") == "updated"


def test_upload_service_rejects_non_multipart():
    from app.services.upload import UploadService

    payload, status = UploadService().upload_multipart(
        body=b"{}",
        content_type="application/json",
        content_length=2,
    )
    assert status == 400
    assert "error" in payload
