# coding: utf-8
"""Workspace picker lists a workspace per profile (not just the active one).

Regression for "why doesn't it show everything?": ``GET /api/v1/workspaces``
returned only the active profile's single auto-managed workspace, hiding every
other profile's workspace from the picker. ``list_all_profile_workspaces``
aggregates one resolved entry per known profile while preserving the
one-workspace-per-profile *save* semantics.
"""

import sys
from types import ModuleType

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod


class _ProfileInfo:
    def __init__(self, name, path, **kwargs):
        self.name = name
        self.path = path
        self.is_default = kwargs.get('is_default', name == 'default')
        self.gateway_running = kwargs.get('gateway_running', False)
        self.model = kwargs.get('model')
        self.provider = kwargs.get('provider')
        self.has_env = kwargs.get('has_env', False)
        self.skill_count = kwargs.get('skill_count', 0)


@pytest.fixture
def multi_profile_home(tmp_path, monkeypatch):
    """A fake ~/.hermes with default + two named profiles and their workspaces."""
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_WORKSPACE_NAME', raising=False)

    for name in ('user1', 'userb'):
        (fake_home / 'profiles' / name).mkdir(parents=True)
        (fake_home / 'workspace' / name).mkdir(parents=True)
    (fake_home / 'workspace').mkdir(parents=True, exist_ok=True)

    profiles = [
        _ProfileInfo('default', fake_home, is_default=True),
        _ProfileInfo('user1', fake_home / 'profiles' / 'user1'),
        _ProfileInfo('userb', fake_home / 'profiles' / 'userb'),
    ]

    # Provide a stub hermes_cli.profiles.list_profiles so list_profiles_api works.
    cli_mod = ModuleType('hermes_cli.profiles')
    cli_mod.list_profiles = lambda: profiles
    sys.modules['hermes_cli'] = ModuleType('hermes_cli')
    sys.modules['hermes_cli.profiles'] = cli_mod
    profiles_mod._profiles_list_cache = None
    profiles_mod._invalidate_root_profile_cache()

    yield fake_home

    for key in list(sys.modules):
        if key == 'hermes_cli' or key.startswith('hermes_cli.'):
            del sys.modules[key]


def _set_active(monkeypatch, home, name):
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: name)


def test_lists_one_entry_per_profile(multi_profile_home, monkeypatch):
    fake_home = multi_profile_home
    _set_active(monkeypatch, fake_home / 'profiles' / 'user1', 'user1')

    workspaces = workspace_mod.list_all_profile_workspaces()
    by_path = {w['path']: w for w in workspaces}

    assert str((fake_home / 'workspace').resolve()) in by_path
    assert str((fake_home / 'workspace' / 'user1').resolve()) in by_path
    assert str((fake_home / 'workspace' / 'userb').resolve()) in by_path


def test_active_profile_workspace_resolved_absolutely(multi_profile_home, monkeypatch):
    """The active profile's entry is its real resolved dir, not './workspace'."""
    fake_home = multi_profile_home
    _set_active(monkeypatch, fake_home / 'profiles' / 'user1', 'user1')

    workspaces = workspace_mod.list_all_profile_workspaces()
    paths = [w['path'] for w in workspaces]

    active_path = str((fake_home / 'workspace' / 'user1').resolve())
    assert active_path in paths
    # No relative placeholder leaks into the picker.
    assert workspace_mod.profile_workspace_rel() not in paths
    assert './workspace' not in paths


def test_no_duplicate_entries(multi_profile_home, monkeypatch):
    fake_home = multi_profile_home
    _set_active(monkeypatch, fake_home / 'profiles' / 'user1', 'user1')

    workspaces = workspace_mod.list_all_profile_workspaces()
    paths = [w['path'] for w in workspaces]

    assert len(paths) == len(set(paths))


def test_named_profiles_use_their_name(multi_profile_home, monkeypatch):
    fake_home = multi_profile_home
    _set_active(monkeypatch, fake_home, 'default')

    workspaces = workspace_mod.list_all_profile_workspaces()
    by_path = {w['path']: w for w in workspaces}

    assert by_path[str((fake_home / 'workspace' / 'user1').resolve())]['name'] == 'user1'
    assert by_path[str((fake_home / 'workspace' / 'userb').resolve())]['name'] == 'userb'


def test_missing_canonical_dir_does_not_crash_and_is_listed(multi_profile_home, monkeypatch):
    """A profile whose canonical workspace dir is missing is still listed."""
    fake_home = multi_profile_home
    # userb exists as a profile but its workspace dir was wiped from state.
    import shutil
    shutil.rmtree(fake_home / 'workspace' / 'userb')
    _set_active(monkeypatch, fake_home / 'profiles' / 'user1', 'user1')

    workspaces = workspace_mod.list_all_profile_workspaces()
    paths = [w['path'] for w in workspaces]

    # Listing did not raise, and the missing-dir profile is still offered.
    assert str((fake_home / 'workspace' / 'userb').resolve()) in paths
    # Listing is read-only: it must not recreate the directory.
    assert not (fake_home / 'workspace' / 'userb').exists()
