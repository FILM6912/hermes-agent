"""Regression tests for profile-switch latency optimizations."""

import sys
import time
from unittest.mock import patch

import pytest


def _setup_profile_home(tmp_path, monkeypatch, profiles, profile_names):
    default_home = tmp_path / ".hermes"
    default_home.mkdir()
    for name in profile_names:
        p = default_home / "profiles" / name
        (p / "workspace").mkdir(parents=True)
        (p / "config.yaml").write_text(
            f"model:\n  default: {name}-model\n  provider: openai\nworkspace: workspace\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("HERMES_HOME", str(default_home))
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(tmp_path / "state"))
    profiles._DEFAULT_HERMES_HOME = default_home
    monkeypatch.setenv("HERMES_BASE_HOME", str(default_home))
    profiles._invalidate_root_profile_cache()
    profiles._active_profile = "default"
    profiles.clear_request_profile()
    return default_home


def test_switch_profile_fast_after_warmup(tmp_path, monkeypatch):
    """First switch after init_profile_state should not pay a cold import tax."""
    import app.domain.profiles as profiles

    _setup_profile_home(tmp_path, monkeypatch, profiles, ["writer"])

    for mod in list(sys.modules):
        if mod == "app.domain.workspace" or mod.startswith("app.domain.workspace."):
            del sys.modules[mod]

    profiles._invalidate_root_profile_cache()
    profiles.init_profile_state()

    t0 = time.perf_counter()
    profiles.switch_profile("writer", process_wide=False)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, (
        f"switch_profile took {elapsed_ms:.1f}ms after warmup; "
        "expected <100ms (cold api.workspace import should run at startup)"
    )


def test_switch_profile_client_skips_invalidate_for_same_profile(tmp_path, monkeypatch):
    """Re-selecting the active profile must not clear the models cache."""
    import app.domain.profiles as profiles
    from app.services.profiles import ProfileService

    _setup_profile_home(tmp_path, monkeypatch, profiles, ["writer"])
    profiles.init_profile_state()
    profiles.set_request_profile("writer")

    svc = ProfileService()
    with patch("app.domain.config.invalidate_models_cache") as invalidate:
        result = svc.switch_profile_client("writer")
        invalidate.assert_not_called()

    assert result["active"] == "writer"
    profiles.clear_request_profile()


def test_switch_profile_client_invalidates_on_profile_change(tmp_path, monkeypatch):
    import app.domain.profiles as profiles
    from app.services.profiles import ProfileService

    _setup_profile_home(tmp_path, monkeypatch, profiles, ["writer", "reader"])
    profiles.init_profile_state()
    profiles.set_request_profile("writer")

    svc = ProfileService()
    with patch(
        "app.domain.config.invalidate_models_cache_after_profile_switch"
    ) as invalidate:
        svc.switch_profile_client("reader")
        invalidate.assert_called_once()
    profiles.clear_request_profile()


def test_profile_switch_keeps_per_profile_disk_cache(tmp_path, monkeypatch):
    """Switching profiles must not delete other profiles' models_cache.*.json files."""
    import app.domain.config as config
    import app.domain.profiles as profiles

    _setup_profile_home(tmp_path, monkeypatch, profiles, ["writer", "reader"])
    profiles.init_profile_state()
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    writer_cache = state / "models_cache.writer.json"
    reader_cache = state / "models_cache.reader.json"
    writer_cache.write_text("{}", encoding="utf-8")
    reader_cache.write_text("{}", encoding="utf-8")

    profiles.set_request_profile("writer")
    config.invalidate_models_cache_after_profile_switch()

    assert writer_cache.exists()
    assert reader_cache.exists()
    profiles.clear_request_profile()
