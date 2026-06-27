# coding: utf-8
"""Profile-scoped MCP server management (?profile=)."""

import json
import os
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest
import yaml

import app.domain.mcp_runtime as mcp_runtime_mod
import app.domain.profiles as profiles_mod
from app.domain.routes import (
    _handle_mcp_discover,
    _handle_mcp_server_delete,
    _handle_mcp_server_test,
    _handle_mcp_server_toggle,
    _handle_mcp_server_update,
    _handle_mcp_servers_import,
    _handle_mcp_servers_list,
    _mcp_connect_errors_for_profile,
    _mcp_obvious_connect_error,
    _mcp_servers_needing_discovery,
    _run_mcp_discovery,
    _server_summary,
)


def _make_handler(path='/api/mcp/servers'):
    h = MagicMock()
    h.path = path
    h.command = 'GET'
    return h


def _json_payload(handler):
    body = handler.wfile.write.call_args[0][0]
    return json.loads(body.decode('utf-8'))


@pytest.fixture(autouse=True)
def _reset_profile_mcp_runtime_state():
    mcp_runtime_mod._MCP_LAST_PROFILE_HOME = None
    yield
    mcp_runtime_mod._MCP_LAST_PROFILE_HOME = None


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    (fake_home / 'config.yaml').write_text(
        yaml.safe_dump({'mcp_servers': {'default-srv': {'command': 'default-cmd'}}}),
        encoding='utf-8',
    )
    usera_home = fake_home / 'profiles' / 'usera'
    usera_home.mkdir(parents=True)
    (usera_home / 'config.yaml').write_text(
        yaml.safe_dump({'mcp_servers': {'usera-srv': {'command': 'usera-cmd'}}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    return fake_home


class TestProfileScopedMcpList:
    @patch('app.domain.routes.reload_config')
    def test_list_named_profile_servers(self, _reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=usera')
        h = _make_handler()
        _handle_mcp_servers_list(h, parsed)
        payload = _json_payload(h)
        assert payload['profile'] == 'usera'
        names = {s['name'] for s in payload['servers']}
        assert names == {'usera-srv'}

    @patch('app.domain.routes.reload_config')
    def test_list_unknown_profile_404(self, _reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=missing')
        h = _make_handler()
        _handle_mcp_servers_list(h, parsed)
        assert h.send_response.call_args[0][0] == 404


class TestProfileScopedMcpMutations:
    @patch('app.domain.routes.reload_config')
    def test_add_server_to_named_profile(self, mock_reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=usera')
        h = _make_handler()
        body = {'command': 'new-cmd', 'profile': 'usera'}
        _handle_mcp_server_update(h, 'new-srv', body, parsed)
        payload = _json_payload(h)
        assert payload['ok'] is True
        assert payload['profile'] == 'usera'
        cfg = yaml.safe_load((fake_hermes_home / 'profiles' / 'usera' / 'config.yaml').read_text())
        assert cfg['mcp_servers']['new-srv']['command'] == 'new-cmd'
        mock_reload.assert_not_called()

    @patch('app.domain.routes.reload_config')
    def test_delete_from_named_profile(self, mock_reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=usera')
        h = _make_handler()
        _handle_mcp_server_delete(h, 'usera-srv', parsed, {'profile': 'usera'})
        payload = _json_payload(h)
        assert payload == {'ok': True, 'deleted': 'usera-srv', 'profile': 'usera'}
        cfg = yaml.safe_load((fake_hermes_home / 'profiles' / 'usera' / 'config.yaml').read_text())
        assert 'usera-srv' not in cfg.get('mcp_servers', {})
        mock_reload.assert_not_called()

    @patch('app.domain.routes.reload_config')
    def test_toggle_on_named_profile(self, mock_reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=usera')
        h = _make_handler()
        _handle_mcp_server_toggle(h, 'usera-srv', {'enabled': False, 'profile': 'usera'}, parsed)
        payload = _json_payload(h)
        assert payload == {'ok': True, 'name': 'usera-srv', 'enabled': False, 'profile': 'usera'}
        cfg = yaml.safe_load((fake_hermes_home / 'profiles' / 'usera' / 'config.yaml').read_text())
        assert cfg['mcp_servers']['usera-srv']['enabled'] is False
        mock_reload.assert_not_called()

    @patch('app.domain.routes.reload_config')
    def test_active_profile_update_reloads_config(self, mock_reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers?profile=default')
        h = _make_handler()
        body = {'command': 'updated', 'profile': 'default'}
        _handle_mcp_server_update(h, 'default-srv', body, parsed)
        _json_payload(h)
        mock_reload.assert_called_once()


class TestMcpDiscover:
    @patch('app.domain.routes.shutil.which', return_value='/usr/bin/python3')
    @patch('tools.mcp_tool.get_mcp_status')
    @patch('app.domain.mcp_runtime.discover_profile_mcp_tools')
    @patch('app.domain.streaming._ENV_LOCK')
    def test_discover_endpoint_connects_profile(self, _lock, mock_discover, mock_status, _which, fake_hermes_home):
        mock_discover.return_value = ['mcp_playwright_browser_close']
        mock_status.return_value = [
            {'name': 'usera-srv', 'transport': 'stdio', 'tools': 3, 'connected': True},
        ]
        parsed = urlparse('/api/mcp/discover?profile=usera')
        h = _make_handler('/api/mcp/discover')
        h.command = 'POST'
        _handle_mcp_discover(h, parsed, {'profile': 'usera'})
        payload = _json_payload(h)
        assert payload['ok'] is True
        assert payload['profile'] == 'usera'
        assert payload['tool_count'] == 3
        assert payload['connected_count'] == 1
        mock_discover.assert_called_once()

    @patch('app.domain.routes.shutil.which', return_value='/usr/bin/python3')
    @patch('app.domain.mcp_runtime.discover_profile_mcp_tools', side_effect=RuntimeError('boom'))
    @patch('tools.mcp_tool.get_mcp_status', return_value=[])
    @patch('app.domain.streaming._ENV_LOCK')
    def test_discover_endpoint_returns_502_on_failure(self, _lock, _status, _discover, _which, fake_hermes_home):
        parsed = urlparse('/api/mcp/discover?profile=usera')
        h = _make_handler('/api/mcp/discover')
        h.command = 'POST'
        _handle_mcp_discover(h, parsed, {'profile': 'usera'})
        assert h.send_response.call_args[0][0] == 502
        payload = _json_payload(h)
        assert payload['ok'] is False
        assert payload['error']

    @patch('app.domain.routes.shutil.which', return_value='/usr/bin/python3')
    @patch('tools.mcp_tool.get_mcp_status', return_value=[])
    @patch('app.domain.mcp_runtime.discover_profile_mcp_tools', return_value=[])
    @patch('app.domain.streaming._ENV_LOCK')
    def test_run_mcp_discovery_uses_profile_home(self, _lock, mock_discover, _status, _which, fake_hermes_home, monkeypatch):
        captured = {}

        def _capture_discover(_home):
            captured['home'] = os.environ.get('HERMES_HOME')
            return []

        mock_discover.side_effect = _capture_discover
        result = _run_mcp_discovery('usera')
        assert result['profile'] == 'usera'
        assert captured['home'] == str(fake_hermes_home / 'profiles' / 'usera')

    @patch('app.domain.routes.shutil.which', return_value='/usr/bin/python3')
    @patch('tools.mcp_tool.get_mcp_status', return_value=[])
    @patch('app.domain.mcp_runtime.discover_profile_mcp_tools')
    @patch('app.domain.streaming._ENV_LOCK')
    def test_discover_skips_when_all_servers_connected_or_obvious(self, _lock, mock_discover, _status, _which, fake_hermes_home, monkeypatch):
        monkeypatch.setattr('app.domain.routes.shutil.which', lambda cmd: None if cmd == 'opensandbox-mcp' else '/usr/bin/python3')
        mcp_runtime_mod._MCP_LAST_PROFILE_HOME = str(fake_hermes_home / 'profiles' / 'usera')
        _status.return_value = [
            {'name': 'playwright', 'transport': 'stdio', 'tools': 23, 'connected': True},
        ]
        cfg_path = fake_hermes_home / 'profiles' / 'usera' / 'config.yaml'
        cfg_path.write_text(yaml.safe_dump({
            'mcp_servers': {
                'playwright': {'command': 'npx', 'args': ['@playwright/mcp@latest']},
                'opensandbox': {'command': 'opensandbox-mcp'},
            }
        }), encoding='utf-8')
        _handle_mcp_discover(
            _make_handler('/api/mcp/discover'),
            urlparse('/api/mcp/discover?profile=usera'),
            {'profile': 'usera'},
        )
        mock_discover.assert_not_called()


class TestMcpServerTest:
    @patch('app.domain.routes._run_mcp_discovery')
    @patch('app.domain.routes._mcp_tools_from_runtime_status', return_value=[{'name': 'tool_a', 'server': 'usera-srv'}])
    @patch('app.domain.routes._mcp_runtime_status_by_name', return_value={})
    def test_server_test_returns_tools(self, _runtime, _tools, mock_discover, fake_hermes_home):
        mock_discover.return_value = {
            'ok': True,
            'profile': 'usera',
            'servers': [{
                'name': 'usera-srv',
                'transport': 'stdio',
                'enabled': True,
                'active': True,
                'status': 'active',
                'tool_count': 1,
            }],
            'errors': {},
        }
        parsed = urlparse('/api/mcp/servers/usera-srv/test?profile=usera')
        h = _make_handler('/api/mcp/servers/usera-srv/test')
        h.command = 'POST'
        _handle_mcp_server_test(h, 'usera-srv', parsed, {'profile': 'usera'})
        payload = _json_payload(h)
        assert payload['ok'] is True
        assert payload['server']['name'] == 'usera-srv'
        assert payload['tool_count'] == 1
        assert payload['tools'][0]['name'] == 'tool_a'

    @patch('app.domain.routes._run_mcp_discovery')
    @patch('app.domain.routes._mcp_runtime_status_by_name', return_value={})
    def test_server_test_unknown_server_404(self, _runtime, _discover, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers/missing/test?profile=usera')
        h = _make_handler('/api/mcp/servers/missing/test')
        h.command = 'POST'
        _handle_mcp_server_test(h, 'missing', parsed, {'profile': 'usera'})
        assert h.send_response.call_args[0][0] == 404


class TestMcpJsonImport:
    def test_import_json_servers(self, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers/import?profile=usera')
        h = _make_handler('/api/mcp/servers/import')
        h.command = 'POST'
        body = {
            'profile': 'usera',
            'servers': {
                'opensandbox': {
                    'command': 'opensandbox-mcp',
                    'args': ['--domain', 'localhost:8080', '--protocol', 'http'],
                },
            },
        }
        _handle_mcp_servers_import(h, parsed, body)
        payload = _json_payload(h)
        assert payload == {'ok': True, 'imported': ['opensandbox'], 'profile': 'usera'}
        cfg = yaml.safe_load((fake_hermes_home / 'profiles' / 'usera' / 'config.yaml').read_text())
        assert cfg['mcp_servers']['opensandbox']['command'] == 'opensandbox-mcp'
        assert cfg['mcp_servers']['opensandbox']['args'] == [
            '--domain', 'localhost:8080', '--protocol', 'http',
        ]

    def test_import_rejects_invalid_config(self, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers/import?profile=usera')
        h = _make_handler('/api/mcp/servers/import')
        h.command = 'POST'
        _handle_mcp_servers_import(h, parsed, {
            'profile': 'usera',
            'servers': {'broken': {'timeout': 30}},
        })
        assert h.send_response.call_args[0][0] == 400

    @patch('app.domain.routes.reload_config')
    def test_update_accepts_config_object(self, mock_reload, fake_hermes_home):
        parsed = urlparse('/api/mcp/servers/import?profile=default')
        h = _make_handler()
        h.command = 'PUT'
        body = {
            'profile': 'default',
            'config': {
                'command': 'opensandbox-mcp',
                'args': ['--domain', 'localhost:8080'],
                'enabled': True,
            },
        }
        _handle_mcp_server_update(h, 'opensandbox', body, parsed)
        payload = _json_payload(h)
        assert payload['ok'] is True
        cfg = yaml.safe_load((fake_hermes_home / 'config.yaml').read_text())
        assert cfg['mcp_servers']['opensandbox']['command'] == 'opensandbox-mcp'


class TestMcpConnectErrors:
    def test_server_summary_shows_connect_error(self):
        summary = _server_summary(
            'opensandbox',
            {'command': 'opensandbox-mcp', 'args': ['--domain', 'localhost:8080']},
            {'connected': False, 'tools': 0},
            "missing executable 'opensandbox-mcp'",
        )
        assert summary['status'] == 'error'
        assert summary['connect_error'] == "missing executable 'opensandbox-mcp'"
        assert summary['tool_count'] is None

    def test_obvious_connect_error_for_missing_command(self, monkeypatch):
        monkeypatch.setattr('app.domain.routes.shutil.which', lambda _cmd: None)
        err = _mcp_obvious_connect_error(
            'opensandbox',
            {'command': 'opensandbox-mcp'},
            connected=False,
        )
        assert err and 'opensandbox-mcp' in err

    def test_connect_errors_after_discover(self, monkeypatch):
        monkeypatch.setattr('app.domain.routes.shutil.which', lambda _cmd: None)
        runtime = {'opensandbox': {'connected': False, 'tools': 0}}
        servers_cfg = {'opensandbox': {'command': 'opensandbox-mcp', 'enabled': True}}
        errors = _mcp_connect_errors_for_profile(
            'usera', servers_cfg, runtime, after_discover=True,
        )
        assert 'opensandbox' in errors
        summary = _server_summary(
            'opensandbox',
            servers_cfg['opensandbox'],
            runtime['opensandbox'],
            errors['opensandbox'],
        )
        assert summary['status'] == 'error'

    def test_servers_needing_discovery_skips_obvious_failures(self, monkeypatch):
        monkeypatch.setattr('app.domain.routes.shutil.which', lambda _cmd: None)
        runtime = {'playwright': {'connected': True, 'tools': 23}}
        servers_cfg = {
            'playwright': {'command': 'npx', 'args': ['@playwright/mcp@latest']},
            'opensandbox': {'command': 'opensandbox-mcp'},
        }
        assert _mcp_servers_needing_discovery(servers_cfg, runtime) == []

    def test_servers_needing_discovery_includes_unconnected(self, monkeypatch):
        monkeypatch.setattr('app.domain.routes.shutil.which', lambda _cmd: '/usr/bin/python3')
        runtime = {}
        servers_cfg = {'playwright': {'command': 'npx', 'args': ['-y', '@playwright/mcp@latest']}}
        assert _mcp_servers_needing_discovery(servers_cfg, runtime) == ['playwright']
