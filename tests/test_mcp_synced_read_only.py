"""MCP servers synced from the default profile are read-only in non-root profiles."""

import app.domain.profiles as profiles_mod


def _write_yaml(path, data):
    import yaml

    path.write_text(yaml.dump(data, default_flow_style=False), encoding='utf-8')


def test_mcp_server_synced_from_default_is_read_only(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_is_root_profile', lambda name: name == 'default')

    _write_yaml(
        fake_home / 'config.yaml',
        {'mcp_servers': {'shared-mcp': {'command': 'echo'}}},
    )

    from app.domain.routes import (
        _mcp_reject_synced_server_mutation,
        _mcp_server_is_synced_from_default,
        _server_summary,
    )

    assert _mcp_server_is_synced_from_default('shared-mcp', 'usera') is True
    assert _mcp_server_is_synced_from_default('shared-mcp', 'default') is False
    assert _mcp_server_is_synced_from_default('local-mcp', 'usera') is False

    summary = _server_summary(
        'shared-mcp',
        {'command': 'echo', 'enabled': True},
        profile_name='usera',
    )
    assert summary['read_only'] is True
    assert summary['synced_from_default'] is True

    try:
        _mcp_reject_synced_server_mutation('shared-mcp', 'usera')
        raise AssertionError('expected ValueError')
    except ValueError as exc:
        assert 'synced from the default profile' in str(exc)
