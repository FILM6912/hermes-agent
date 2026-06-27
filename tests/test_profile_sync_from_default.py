# coding: utf-8
"""Profile sync-from-default copies SOUL.md, overwrites shared skills/MCP, merges other config."""

import pytest

import app.domain.profiles as profiles_mod


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    monkeypatch.setattr(profiles_mod, '_is_root_profile', lambda name: name == 'default')
    return fake_home


def _write_yaml(path, data):
    import yaml
    path.write_text(yaml.dump(data, default_flow_style=False), encoding='utf-8')


def test_sync_profile_from_default_adds_missing_items(fake_hermes_home):
    default_skill = fake_hermes_home / 'skills' / 'default-skill'
    default_skill.mkdir(parents=True)
    (default_skill / 'SKILL.md').write_text('# default\n', encoding='utf-8')
    (fake_hermes_home / 'SOUL.md').write_text('# Default soul\n', encoding='utf-8')
    _write_yaml(
        fake_hermes_home / 'config.yaml',
        {
            'model': {'default': 'root-model', 'temperature': 0.2},
            'agent': {'max_turns': 40},
            'mcp_servers': {
                'shared-mcp': {'command': 'echo', 'args': ['hi']},
            },
        },
    )

    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    user_skill = target_home / 'skills' / 'user-skill'
    user_skill.mkdir(parents=True)
    (user_skill / 'SKILL.md').write_text('# user\n', encoding='utf-8')
    _write_yaml(
        target_home / 'config.yaml',
        {
            'model': {'default': 'user-model'},
            'mcp_servers': {
                'user-mcp': {'command': 'user-cmd'},
            },
        },
    )

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['ok'] is True
    assert result['added']['skills'] == ['default-skill']
    assert 'user-skill' not in result['added']['skills']
    assert result['added']['files'] == ['SOUL.md']
    assert 'shared-mcp' in result['added']['mcp_servers']
    assert 'user-mcp' not in result['added']['mcp_servers']
    assert 'model' in result['added']['config']
    assert 'agent' in result['added']['config'] or 'agent.max_turns' in result['added']['config']

    import yaml
    merged = yaml.safe_load((target_home / 'config.yaml').read_text(encoding='utf-8'))
    assert merged['model']['default'] == 'root-model'
    assert merged['model']['temperature'] == 0.2
    assert merged['agent']['max_turns'] == 40
    assert 'shared-mcp' in merged['mcp_servers']
    assert 'user-mcp' in merged['mcp_servers']
    assert (target_home / 'skills' / 'default-skill' / 'SKILL.md').exists()
    assert (target_home / 'skills' / 'user-skill' / 'SKILL.md').exists()
    assert (target_home / 'SOUL.md').read_text(encoding='utf-8') == '# Default soul\n'


def test_sync_profile_from_default_overwrites_divergent_soul_with_exact_copy(fake_hermes_home):
    default_soul = '# Default soul\n\nShared persona traits.\n\nNew default guidance.\n'
    (fake_hermes_home / 'SOUL.md').write_text(default_soul, encoding='utf-8')
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    (target_home / 'SOUL.md').write_text('# User soul\n\nCustom note.\n', encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['files'] == ['SOUL.md']
    synced = (target_home / 'SOUL.md').read_text(encoding='utf-8')
    assert synced == default_soul
    assert 'User soul' not in synced
    assert 'Custom note.' not in synced


def test_sync_profile_from_default_soul_noop_when_already_identical(fake_hermes_home):
    soul = '# Default soul\n\nShared persona traits.\n'
    (fake_hermes_home / 'SOUL.md').write_text(soul, encoding='utf-8')
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    (target_home / 'SOUL.md').write_text(soul, encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['skipped']['files'] == ['SOUL.md']
    assert (target_home / 'SOUL.md').read_text(encoding='utf-8') == soul


def test_sync_profile_from_default_creates_soul_when_target_missing(fake_hermes_home):
    default_soul = '# Default soul\n\nShared persona traits.\n'
    (fake_hermes_home / 'SOUL.md').write_text(default_soul, encoding='utf-8')
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['files'] == ['SOUL.md']
    assert (target_home / 'SOUL.md').read_text(encoding='utf-8') == default_soul


def test_sync_profile_from_default_leaves_soul_untouched_when_default_has_none(fake_hermes_home):
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    existing = '# User soul\n\nCustom note.\n'
    (target_home / 'SOUL.md').write_text(existing, encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert 'SOUL.md' not in result['added']['files']
    assert 'SOUL.md' not in result['skipped']['files']
    assert (target_home / 'SOUL.md').read_text(encoding='utf-8') == existing


def test_sync_soul_from_source_overwrites_target_verbatim(tmp_path):
    source_home = tmp_path / 'default'
    target_home = tmp_path / 'usera'
    source_home.mkdir()
    target_home.mkdir()
    source_soul = '# Default soul\n\nShared persona traits.\n\nNew default guidance.\n'
    (source_home / 'SOUL.md').write_text(source_soul, encoding='utf-8')
    (target_home / 'SOUL.md').write_text('# User soul\n\nCustom note.', encoding='utf-8')

    added, skipped = profiles_mod._sync_soul_from_source(source_home, target_home)

    assert added == ['SOUL.md']
    assert skipped == []
    assert (target_home / 'SOUL.md').read_text(encoding='utf-8') == source_soul


def test_sync_profile_from_default_copies_full_model_section(fake_hermes_home):
    _write_yaml(
        fake_hermes_home / 'config.yaml',
        {
            'model': {
                'default': 'root-model',
                'provider': 'openrouter',
                'temperature': 0.2,
                'base_url': 'https://openrouter.ai/api/v1',
            },
        },
    )
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    _write_yaml(
        target_home / 'config.yaml',
        {
            'model': {
                'default': 'stale-model',
                'provider': 'openai',
                'max_tokens': 999,
            },
        },
    )

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['config'] == ['model']
    import yaml
    merged = yaml.safe_load((target_home / 'config.yaml').read_text(encoding='utf-8'))
    assert merged['model'] == {
        'default': 'root-model',
        'provider': 'openrouter',
        'temperature': 0.2,
        'base_url': 'https://openrouter.ai/api/v1',
    }
    assert 'max_tokens' not in merged['model']


def test_sync_profile_from_default_skips_model_when_already_matches(fake_hermes_home):
    model_cfg = {
        'default': 'shared-model',
        'provider': 'openrouter',
        'temperature': 0.5,
    }
    _write_yaml(fake_hermes_home / 'config.yaml', {'model': model_cfg})
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    _write_yaml(target_home / 'config.yaml', {'model': dict(model_cfg)})

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['skipped']['config'] == ['model']


def test_sync_profile_from_default_rejects_default_profile(fake_hermes_home):
    with pytest.raises(ValueError, match='default profile'):
        profiles_mod.sync_profile_from_default_api('default')


def test_sync_profile_from_default_symlinks_external_skills(fake_hermes_home):
    external_root = fake_hermes_home.parent / 'agents-skills'
    hub_skill = external_root / 'docx'
    hub_skill.mkdir(parents=True)
    (hub_skill / 'SKILL.md').write_text('---\nname: docx\n---\n', encoding='utf-8')

    default_skills = fake_hermes_home / 'skills'
    default_skills.mkdir(parents=True, exist_ok=True)
    default_skills.joinpath('docx').symlink_to(hub_skill)

    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    (target_home / 'skills').mkdir(exist_ok=True)

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['skills'] == ['docx']
    linked = target_home / 'skills' / 'docx'
    assert linked.is_symlink()
    assert linked.resolve() == hub_skill.resolve()


def test_sync_profile_from_default_overwrites_existing_skill(fake_hermes_home):
    default_skill = fake_hermes_home / 'skills' / 'shared-skill'
    default_skill.mkdir(parents=True)
    (default_skill / 'SKILL.md').write_text('# default v2\n', encoding='utf-8')

    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    stale_skill = target_home / 'skills' / 'shared-skill'
    stale_skill.mkdir(parents=True)
    (stale_skill / 'SKILL.md').write_text('# stale v1\n', encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['skills'] == ['shared-skill']
    assert (stale_skill / 'SKILL.md').read_text(encoding='utf-8') == '# default v2\n'


def test_sync_profile_from_default_skips_skill_when_already_matches(fake_hermes_home):
    skill_text = '# shared\n'
    default_skill = fake_hermes_home / 'skills' / 'shared-skill'
    default_skill.mkdir(parents=True)
    (default_skill / 'SKILL.md').write_text(skill_text, encoding='utf-8')

    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    target_skill = target_home / 'skills' / 'shared-skill'
    target_skill.mkdir(parents=True)
    (target_skill / 'SKILL.md').write_text(skill_text, encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['skipped']['skills'] == ['shared-skill']
    assert (target_skill / 'SKILL.md').read_text(encoding='utf-8') == skill_text


def test_sync_profile_from_default_overwrites_existing_mcp_server(fake_hermes_home):
    _write_yaml(
        fake_hermes_home / 'config.yaml',
        {
            'mcp_servers': {
                'shared-mcp': {'command': 'echo', 'args': ['hi']},
            },
        },
    )
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    _write_yaml(
        target_home / 'config.yaml',
        {
            'mcp_servers': {
                'shared-mcp': {'command': 'stale-cmd'},
                'user-mcp': {'command': 'user-cmd'},
            },
        },
    )

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['mcp_servers'] == ['shared-mcp']
    assert 'user-mcp' not in result['added']['mcp_servers']
    import yaml
    merged = yaml.safe_load((target_home / 'config.yaml').read_text(encoding='utf-8'))
    assert merged['mcp_servers']['shared-mcp'] == {'command': 'echo', 'args': ['hi']}
    assert merged['mcp_servers']['user-mcp'] == {'command': 'user-cmd'}


def test_sync_profile_from_default_copies_auth_json(fake_hermes_home):
    auth_payload = (
        '{"active_provider":"openrouter","credential_pool":{"openrouter":'
        '[{"id":"main","api_key":"secret-key"}]}}\n'
    )
    (fake_hermes_home / 'auth.json').write_text(auth_payload, encoding='utf-8')
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    (target_home / 'auth.json').write_text('{"active_provider":"anthropic"}\n', encoding='utf-8')

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert result['added']['files'] == ['auth.json']
    assert (target_home / 'auth.json').read_text(encoding='utf-8') == auth_payload


def test_sync_profile_from_default_overwrites_custom_providers(fake_hermes_home):
    _write_yaml(
        fake_hermes_home / 'config.yaml',
        {
            'model': {'default': 'root-model', 'provider': 'custom:lm-studio'},
            'custom_providers': [
                {'name': 'lm-studio', 'base_url': 'http://default:1234/v1', 'model': 'qwen'},
            ],
            'providers': {'openrouter': {'api_key': 'default-key'}},
            'fallback_providers': ['openrouter'],
        },
    )
    target_home = fake_hermes_home / 'profiles' / 'usera'
    target_home.mkdir(parents=True)
    _write_yaml(
        target_home / 'config.yaml',
        {
            'model': {'default': 'stale-model', 'provider': 'openai'},
            'custom_providers': [
                {'name': 'lm-studio', 'base_url': 'http://stale:9999/v1', 'model': 'old'},
            ],
            'providers': {'openrouter': {'api_key': 'stale-key'}},
            'fallback_providers': [],
            'openrouter': {'response_cache': False},
        },
    )

    result = profiles_mod.sync_profile_from_default_api('usera')

    assert 'custom_providers' in result['added']['config']
    assert 'providers' in result['added']['config']
    assert 'fallback_providers' in result['added']['config']
    import yaml
    merged = yaml.safe_load((target_home / 'config.yaml').read_text(encoding='utf-8'))
    assert merged['custom_providers'] == [
        {'name': 'lm-studio', 'base_url': 'http://default:1234/v1', 'model': 'qwen'},
    ]
    assert merged['providers'] == {'openrouter': {'api_key': 'default-key'}}
    assert merged['fallback_providers'] == ['openrouter']
    assert 'openrouter' not in merged


def test_sync_all_profiles_from_default_api(fake_hermes_home, monkeypatch):
    for name in ('usera', 'userb'):
        home = fake_hermes_home / 'profiles' / name
        home.mkdir(parents=True)
        (home / 'skills').mkdir(exist_ok=True)

    default_skill = fake_hermes_home / 'skills' / 'shared-skill'
    default_skill.mkdir(parents=True)
    (default_skill / 'SKILL.md').write_text('# shared\n', encoding='utf-8')

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == 'hermes_cli.profiles':
            raise ImportError('mocked for test')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', fake_import)

    result = profiles_mod.sync_all_profiles_from_default_api()

    assert result['ok'] is True
    names = {item['name'] for item in result['profiles']}
    assert names == {'usera', 'userb'}
    for name in names:
        skill_path = fake_hermes_home / 'profiles' / name / 'skills' / 'shared-skill' / 'SKILL.md'
        assert skill_path.exists()
