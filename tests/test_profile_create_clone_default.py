# coding: utf-8
"""Regression: new profiles clone from the default profile by default."""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

import app.domain.profiles as profiles_mod


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    (fake_home / 'config.yaml').write_text('model:\n  default: root-model\n', encoding='utf-8')
    skills = fake_home / 'skills' / 'demo-skill'
    skills.mkdir(parents=True)
    (skills / 'SKILL.md').write_text('# demo\n', encoding='utf-8')
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    return fake_home


def _install_create_profile_mock(fake_hermes_home):
    calls = []

    def fake_create(name, **kw):
        calls.append(kw)
        (fake_hermes_home / 'profiles' / name).mkdir(parents=True, exist_ok=True)

    mock = ModuleType('hermes_cli.profiles')
    mock.create_profile = fake_create
    mock.seed_profile_skills = lambda *a, **k: pytest.fail('seed should not run when cloning')
    sys.modules['hermes_cli'] = ModuleType('hermes_cli')
    sys.modules['hermes_cli.profiles'] = mock
    return calls


def test_create_profile_api_defaults_to_clone_from_default(fake_hermes_home):
    calls = _install_create_profile_mock(fake_hermes_home)
    try:
        with patch.object(profiles_mod, 'list_profiles_api', return_value=[]):
            result = profiles_mod.create_profile_api('beta')
    finally:
        for key in list(sys.modules):
            if key == 'hermes_cli' or key.startswith('hermes_cli.'):
                del sys.modules[key]

    assert result['name'] == 'beta'
    assert len(calls) == 1
    assert calls[0]['clone_from'] == 'default'
    assert calls[0]['clone_config'] is True


def test_resolve_profile_clone_defaults():
    clone_from, clone_config = profiles_mod._resolve_profile_clone_defaults(None, None)
    assert clone_from == 'default'
    assert clone_config is True

    clone_from, clone_config = profiles_mod._resolve_profile_clone_defaults('custom', False)
    assert clone_from == 'custom'
    assert clone_config is False


def test_create_profile_fallback_clones_skills_from_default(fake_hermes_home):
    profiles_mod._create_profile_fallback('gamma', clone_from='default', clone_config=True)
    profile_dir = fake_hermes_home / 'profiles' / 'gamma'
    assert (profile_dir / 'config.yaml').read_text(encoding='utf-8').startswith('model:')
    assert (profile_dir / 'skills' / 'demo-skill' / 'SKILL.md').exists()
