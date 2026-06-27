# coding: utf-8
"""Workspace settings loaded from environment variables."""

from pathlib import Path

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    return fake_home


def test_profile_workspace_rel_reads_profile_env(monkeypatch):
    monkeypatch.setenv('HERMES_WEBUI_PROFILE_WORKSPACE', './projects')
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    assert workspace_mod.profile_workspace_rel() == './projects'


def test_profile_workspace_rel_falls_back_to_default_env(monkeypatch):
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.setenv('HERMES_WEBUI_DEFAULT_WORKSPACE', './code')
    assert workspace_mod.profile_workspace_rel() == './code'


def test_profile_workspace_display_name_from_env(monkeypatch):
    monkeypatch.setenv('HERMES_WEBUI_WORKSPACE_NAME', 'Main')
    assert workspace_mod.profile_workspace_display_name() == 'Main'


def test_resolve_profile_workspace_honors_env_relative_path(fake_hermes_home, monkeypatch):
    monkeypatch.setenv('HERMES_WEBUI_PROFILE_WORKSPACE', './projects')
    resolved = workspace_mod.resolve_profile_workspace('./projects', fake_hermes_home)
    assert resolved == (fake_hermes_home / 'projects').resolve()


def test_resolve_profile_workspace_custom_rel_stays_under_profile_home(fake_hermes_home, monkeypatch):
    monkeypatch.setenv('HERMES_WEBUI_PROFILE_WORKSPACE', './projects')
    profile_home = fake_hermes_home / 'profiles' / 'demo'
    profile_home.mkdir(parents=True)
    resolved = workspace_mod.resolve_profile_workspace('./projects', profile_home)
    assert resolved == (profile_home / 'projects').resolve()


def test_state_dir_resolves_relative_to_hermes_home(tmp_path, monkeypatch):
    from app.domain.config import _resolve_hermes_path

    fake_home = tmp_path / '.hermes'
    fake_home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(fake_home))
    assert _resolve_hermes_path('./webui') == (fake_home / 'webui').resolve()
    assert _resolve_hermes_path('/var/state/webui') == Path('/var/state/webui').resolve()
