# coding: utf-8
"""Each /api/profiles entry exposes its own workspace metadata."""

import json

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
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    return fake_home


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


def test_list_profiles_api_includes_profile_workspace(fake_hermes_home, monkeypatch):
    usera_home = fake_hermes_home / 'profiles' / 'usera'
    usera_home.mkdir(parents=True)
    userb_home = fake_hermes_home / 'profiles' / 'userb'
    userb_home.mkdir(parents=True)
    (fake_hermes_home / 'workspace' / 'usera').mkdir(parents=True)
    (fake_hermes_home / 'workspace' / 'userb').mkdir(parents=True)

    state_dir = usera_home / 'webui_state'
    state_dir.mkdir(parents=True)
    (state_dir / 'workspaces.json').write_text(
        json.dumps([{'path': './workspace', 'name': 'usera'}]),
        encoding='utf-8',
    )

    profiles = [
        _ProfileInfo('default', fake_hermes_home, is_default=True),
        _ProfileInfo('usera', usera_home),
        _ProfileInfo('userb', userb_home),
    ]

    monkeypatch.setattr(
        profiles_mod,
        'list_profiles',
        lambda: profiles,
        raising=False,
    )

    def fake_list_profiles():
        return profiles

    import hermes_cli.profiles as cli_profiles
    monkeypatch.setattr(cli_profiles, 'list_profiles', fake_list_profiles)

    profiles_mod._profiles_list_cache = None
    result = profiles_mod.list_profiles_api()

    by_name = {item['name']: item for item in result}
    assert by_name['default']['default_workspace'] == str((fake_hermes_home / 'workspace').resolve())
    assert by_name['usera']['default_workspace'] == str((fake_hermes_home / 'workspace' / 'usera').resolve())
    assert by_name['userb']['default_workspace'] == str((fake_hermes_home / 'workspace' / 'userb').resolve())
    assert by_name['usera']['workspace_name'] == 'usera'
    assert by_name['userb']['workspace_name'] == 'userb'


def test_list_profiles_api_dedupes_duplicate_default(fake_hermes_home, monkeypatch):
    """hermes_cli may list both root default and profiles/default — keep one row."""
    nested_default = fake_hermes_home / 'profiles' / 'default'
    nested_default.mkdir(parents=True)
    user_home = fake_hermes_home / 'profiles' / 'user'
    user_home.mkdir(parents=True)

    profiles = [
        _ProfileInfo('default', fake_hermes_home, is_default=True, model='qwen3.5-9b'),
        _ProfileInfo('default', nested_default, is_default=True, model='qwen3.5-9b'),
        _ProfileInfo('user', user_home, model='qwen3.5-9b'),
        _ProfileInfo('user1', fake_hermes_home / 'profiles' / 'user1', model='qwen3.5-9b'),
    ]
    (fake_hermes_home / 'profiles' / 'user1').mkdir(parents=True)

    import hermes_cli.profiles as cli_profiles

    monkeypatch.setattr(cli_profiles, 'list_profiles', lambda: profiles)
    profiles_mod._profiles_list_cache = None
    profiles_mod._invalidate_root_profile_cache()

    result = profiles_mod.list_profiles_api()
    names = [item['name'] for item in result]

    assert names.count('default') == 1
    assert names == ['default', 'user', 'user1']
    assert result[0]['path'] == str(fake_hermes_home)


def test_default_workspace_for_home_uses_shared_subdir(fake_hermes_home, monkeypatch):
    usera_home = fake_hermes_home / 'profiles' / 'usera'
    usera_home.mkdir(parents=True)
    (fake_hermes_home / 'workspace' / 'usera').mkdir(parents=True)

    path = profiles_mod._default_workspace_for_home(usera_home)
    assert path == str((fake_hermes_home / 'workspace' / 'usera').resolve())
