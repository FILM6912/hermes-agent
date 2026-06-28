from pathlib import Path

import app.domain.config as config
import app.domain.profiles as profiles


def test_profiles_unwrap_profile_home_to_base():
    base = Path('/tmp/hermes-base')
    profile_home = base / 'profiles' / 'webui'
    assert profiles._unwrap_profile_home_to_base(profile_home) == base


def test_default_hermes_home_returns_path_object():
    home = config._platform_default_hermes_home()
    assert isinstance(home, Path)


def test_windows_default_prefers_userprofile_when_config_exists(tmp_path, monkeypatch):
    """Film-style layout: CLI config under %USERPROFILE%\\.hermes, not LOCALAPPDATA."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_BASE_HOME", raising=False)
    user_home = tmp_path / "user"
    dot_hermes = user_home / ".hermes"
    dot_hermes.mkdir(parents=True)
    (dot_hermes / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    local_hermes = tmp_path / "LocalAppData" / "hermes"
    local_hermes.mkdir(parents=True)

    monkeypatch.setattr(config, "HOME", user_home)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert config._platform_default_hermes_home() == dot_hermes
