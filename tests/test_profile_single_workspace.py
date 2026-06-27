# coding: utf-8
"""Regression coverage for one-workspace-per-profile policy."""

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

import app.domain.profiles as profiles_mod
import app.domain.workspace as workspace_mod


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    fake_home = tmp_path / '.hermes'
    fake_home.mkdir(parents=True)
    state = tmp_path / 'webui_state'
    state.mkdir(parents=True)
    monkeypatch.setenv('HERMES_BASE_HOME', str(fake_home))
    monkeypatch.setenv('HERMES_WEBUI_STATE_DIR', str(state))
    monkeypatch.setenv('HERMES_WEBUI_MULTI_USER', '0')
    monkeypatch.setattr(profiles_mod, '_DEFAULT_HERMES_HOME', fake_home)
    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_WORKSPACE_NAME', raising=False)
    monkeypatch.setattr(workspace_mod, 'nested_workspaces_enabled', lambda: False)
    return fake_home


def _install_create_profile_mock(fake_hermes_home):
    def fake_create(name, **kw):
        (fake_hermes_home / 'profiles' / name).mkdir(parents=True, exist_ok=True)

    mock = ModuleType('hermes_cli.profiles')
    mock.create_profile = fake_create
    mock.seed_profile_skills = lambda *a, **k: None
    sys.modules['hermes_cli'] = ModuleType('hermes_cli')
    sys.modules['hermes_cli.profiles'] = mock


def test_load_workspaces_returns_single_auto_workspace(fake_hermes_home, monkeypatch):
    profile_home = fake_hermes_home
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: profile_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')

    workspaces = workspace_mod.load_workspaces()

    assert len(workspaces) == 1
    assert workspaces[0]['path'] == workspace_mod.profile_workspace_rel()
    assert (profile_home / 'workspace').is_dir()


def test_load_workspaces_normalizes_multiple_entries(fake_hermes_home, monkeypatch):
    profile_home = fake_hermes_home
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: profile_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')

    state_dir = workspace_mod._state_dir_for_profile_home(profile_home)
    ws_file = state_dir / 'workspaces.json'
    ws_file.parent.mkdir(parents=True, exist_ok=True)
    ws_file.write_text(
        json.dumps([
            {'path': '/tmp/a', 'name': 'A'},
            {'path': '/tmp/b', 'name': 'B'},
        ]),
        encoding='utf-8',
    )

    workspaces = workspace_mod.load_workspaces()

    assert len(workspaces) == 1
    assert workspaces[0]['path'] == workspace_mod.profile_workspace_rel()


def test_ensure_profile_workspace_persists_state(fake_hermes_home):
    profile_home = fake_hermes_home / 'profiles' / 'demo'
    profile_home.mkdir(parents=True)

    entry = workspace_mod.ensure_profile_workspace(profile_home, name='demo')

    assert entry['path'] == workspace_mod.profile_workspace_rel()
    ws_file = profile_home / 'webui_state' / 'workspaces.json'
    assert ws_file.exists()


def test_create_profile_api_auto_creates_workspace(fake_hermes_home):
    _install_create_profile_mock(fake_hermes_home)
    try:
        with patch.object(profiles_mod, 'list_profiles_api', return_value=[]):
            result = profiles_mod.create_profile_api('alpha')
    finally:
        for key in list(sys.modules):
            if key == 'hermes_cli' or key.startswith('hermes_cli.'):
                del sys.modules[key]

    profile_dir = fake_hermes_home / 'profiles' / 'alpha'
    assert result['name'] == 'alpha'
    assert (fake_hermes_home / 'workspace' / 'alpha').is_dir()
    assert (profile_dir / 'webui_state' / 'workspaces.json').exists()


def test_resolve_profile_workspace_named_profile_uses_shared_subdir(fake_hermes_home, monkeypatch):
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    profile_home = fake_hermes_home / 'profiles' / 'usera'
    profile_home.mkdir(parents=True)
    resolved = workspace_mod.resolve_profile_workspace('./workspace', profile_home)
    assert resolved == (fake_hermes_home / 'workspace' / 'usera').resolve()


def test_resolve_profile_workspace_remaps_legacy_profile_path(fake_hermes_home, monkeypatch):
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    profile_home = fake_hermes_home / 'profiles' / 'usera'
    profile_home.mkdir(parents=True)
    legacy = profile_home / 'workspace'
    legacy.mkdir()
    resolved = workspace_mod.resolve_profile_workspace(str(legacy), profile_home)
    assert resolved == (fake_hermes_home / 'workspace' / 'usera').resolve()


def test_resolve_trusted_workspace_recreates_missing_profile_workspace(
    fake_hermes_home, monkeypatch
):
    """A named profile's missing canonical workspace is recreated on resolve.

    Regression for ``Path does not exist: .../workspace/<name>``: a profile
    created under the legacy ``profiles/<name>/workspace`` layout (or whose
    shared workspace dir was wiped from container/host state) referenced the
    shared ``workspace/<name>`` directory that no longer existed. Resolving the
    profile's own auto-managed workspace must recreate it instead of raising.
    """
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    profile_home = fake_hermes_home / 'profiles' / 'user1'
    profile_home.mkdir(parents=True)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: profile_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'user1')
    # In Docker the boot default workspace is the shared ~/.hermes/workspace root,
    # which makes the profile's workspace/<name> subdir trusted via rule (C).
    monkeypatch.setattr(
        workspace_mod, '_BOOT_DEFAULT_WORKSPACE', str(fake_hermes_home / 'workspace')
    )

    canonical = fake_hermes_home / 'workspace' / 'user1'
    assert not canonical.exists()

    resolved = workspace_mod.resolve_trusted_workspace(str(canonical))

    assert resolved == canonical.resolve()
    assert canonical.is_dir()


def test_resolve_trusted_workspace_does_not_create_arbitrary_missing_path(
    fake_hermes_home, monkeypatch
):
    """Auto-create is scoped to the profile's own workspace, not any input."""
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    profile_home = fake_hermes_home / 'profiles' / 'user1'
    profile_home.mkdir(parents=True)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: profile_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'user1')

    bogus = fake_hermes_home / 'workspace' / 'someone-else'
    assert not bogus.exists()

    with pytest.raises(ValueError, match="Path does not exist"):
        workspace_mod.resolve_trusted_workspace(str(bogus))
    assert not bogus.exists()


def test_resolve_trusted_workspace_recreates_profile_workspace_when_active_is_default(
    fake_hermes_home, monkeypatch
):
    """The real-world failure path PR #14 missed.

    A named profile's own canonical workspace (``workspace/user1``) is requested
    while a DIFFERENT profile is active. In production the per-request profile
    is stored in a ``threading.local`` set by the async security middleware, but
    sync endpoints run on a separate threadpool worker where that thread-local
    is empty — so ``get_active_profile_name()`` falls back to the process-global
    ``'default'``. PR #14 only recreated the *active* profile's canonical dir, so
    the guard never matched and resolution raised ``Path does not exist``.

    The fix must recreate any *known* profile's own canonical workspace, even
    when a different profile is active.
    """
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    profile_home = fake_hermes_home / 'profiles' / 'user1'
    profile_home.mkdir(parents=True)
    # Active context resolves to the DEFAULT root profile, not user1 — exactly
    # what happens inside the sync endpoint worker thread in the container.
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: fake_hermes_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')
    monkeypatch.setattr(
        workspace_mod, '_BOOT_DEFAULT_WORKSPACE', str(fake_hermes_home / 'workspace')
    )

    canonical = fake_hermes_home / 'workspace' / 'user1'
    assert not canonical.exists()

    resolved = workspace_mod.resolve_trusted_workspace(str(canonical))

    assert resolved == canonical.resolve()
    assert canonical.is_dir()


def test_resolve_trusted_workspace_does_not_create_workspace_for_unknown_profile(
    fake_hermes_home, monkeypatch
):
    """A workspace subdir for a profile that does not exist is never created."""
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: fake_hermes_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')
    monkeypatch.setattr(
        workspace_mod, '_BOOT_DEFAULT_WORKSPACE', str(fake_hermes_home / 'workspace')
    )
    (fake_hermes_home / 'workspace').mkdir(parents=True)

    ghost = fake_hermes_home / 'workspace' / 'ghost'
    assert not ghost.exists()

    with pytest.raises(ValueError, match="Path does not exist"):
        workspace_mod.resolve_trusted_workspace(str(ghost))
    assert not ghost.exists()


def test_resolve_trusted_workspace_remaps_missing_shared_root_default_subdir(
    fake_hermes_home, monkeypatch
):
    """Regression: ``.../workspace/default`` resolves to the Docker mount root.

    The root profile's canonical workspace is ``~/.hermes/workspace``, but stale
    session/composer paths often reference ``.../workspace/default``. When the
    bind mount exists at the shared root and the ``default`` subdir is absent,
    resolution must succeed against the mount root instead of raising.
    """
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: fake_hermes_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')
    monkeypatch.setattr(workspace_mod, 'nested_workspaces_enabled', lambda: False)
    monkeypatch.setattr(
        workspace_mod, '_BOOT_DEFAULT_WORKSPACE', str(fake_hermes_home / 'workspace')
    )

    shared_root = fake_hermes_home / 'workspace'
    shared_root.mkdir(parents=True)
    bogus = shared_root / 'default'
    assert not bogus.exists()

    resolved = workspace_mod.resolve_trusted_workspace(str(bogus))

    assert resolved == shared_root.resolve()
    assert not bogus.exists()


def test_resolve_trusted_workspace_keeps_existing_shared_root_default_subdir(
    fake_hermes_home, monkeypatch
):
    """An on-disk nested ``default`` folder is not remapped away."""
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: fake_hermes_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')
    monkeypatch.setattr(workspace_mod, 'nested_workspaces_enabled', lambda: False)
    monkeypatch.setattr(
        workspace_mod, '_BOOT_DEFAULT_WORKSPACE', str(fake_hermes_home / 'workspace')
    )

    nested = fake_hermes_home / 'workspace' / 'default'
    nested.mkdir(parents=True)

    resolved = workspace_mod.resolve_trusted_workspace(str(nested))

    assert resolved == nested.resolve()


def test_ensure_profile_workspace_exists_creates_known_profile_dir(
    fake_hermes_home, monkeypatch
):
    """The centralized helper creates a known profile's canonical workspace."""
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    (fake_hermes_home / 'profiles' / 'user1').mkdir(parents=True)
    monkeypatch.setattr(profiles_mod, 'get_active_hermes_home', lambda: fake_hermes_home)
    monkeypatch.setattr(profiles_mod, 'get_active_profile_name', lambda: 'default')

    canonical = fake_hermes_home / 'workspace' / 'user1'
    assert not canonical.exists()

    created = workspace_mod.ensure_profile_workspace_exists(canonical)

    assert created is True
    assert canonical.is_dir()


def test_max_workspaces_per_profile_is_one():
    assert workspace_mod.MAX_WORKSPACES_PER_PROFILE == 1


def test_resolve_profile_workspace_relative_default(fake_hermes_home, monkeypatch):
    monkeypatch.delenv('HERMES_WEBUI_PROFILE_WORKSPACE', raising=False)
    monkeypatch.delenv('HERMES_WEBUI_DEFAULT_WORKSPACE', raising=False)
    resolved = workspace_mod.resolve_profile_workspace('./workspace', fake_hermes_home)
    assert resolved == (fake_hermes_home / 'workspace').resolve()


def test_delete_profile_workspace_removes_shared_subdir(fake_hermes_home):
    profile_home = fake_hermes_home / 'profiles' / 'demo'
    profile_home.mkdir(parents=True)
    ws = fake_hermes_home / 'workspace' / 'demo'
    ws.mkdir(parents=True)
    (ws / 'note.txt').write_text('x', encoding='utf-8')

    deleted = workspace_mod.delete_profile_workspace(profile_home)

    assert not ws.exists()
    assert str(ws.resolve()) in deleted


def test_delete_profile_workspace_removes_legacy_dir(fake_hermes_home):
    profile_home = fake_hermes_home / 'profiles' / 'legacy'
    profile_home.mkdir(parents=True)
    legacy_ws = profile_home / 'workspace'
    legacy_ws.mkdir(parents=True)
    (legacy_ws / 'old.txt').write_text('x', encoding='utf-8')

    deleted = workspace_mod.delete_profile_workspace(profile_home)

    assert not legacy_ws.exists()
    assert str(legacy_ws.resolve()) in deleted


def test_delete_profile_workspace_skips_default_root(fake_hermes_home):
    ws_root = fake_hermes_home / 'workspace'
    ws_root.mkdir(parents=True)
    (ws_root / 'important.txt').write_text('x', encoding='utf-8')

    deleted = workspace_mod.delete_profile_workspace(fake_hermes_home)

    assert deleted == []
    assert ws_root.exists()


def test_delete_profile_api_removes_shared_workspace(fake_hermes_home, monkeypatch):
    import shutil

    import hermes_cli.profiles as cli_profiles

    profile_home = fake_hermes_home / 'profiles' / 'demo'
    profile_home.mkdir(parents=True)
    ws = fake_hermes_home / 'workspace' / 'demo'
    ws.mkdir(parents=True)
    (ws / 'note.txt').write_text('x', encoding='utf-8')

    def fake_delete_profile(name, yes=True):
        path = fake_hermes_home / 'profiles' / name
        if not path.is_dir():
            raise FileNotFoundError(f"Profile '{name}' does not exist.")
        shutil.rmtree(path)
        return path

    monkeypatch.setattr(profiles_mod, '_active_profile', 'default')
    monkeypatch.setattr(profiles_mod, '_is_root_profile', lambda n: n == 'default')
    monkeypatch.setattr(profiles_mod, '_invalidate_root_profile_cache', lambda: None)
    monkeypatch.setattr(cli_profiles, 'delete_profile', fake_delete_profile)

    result = profiles_mod.delete_profile_api('demo')

    assert result == {'ok': True, 'name': 'demo'}
    assert not profile_home.exists()
    assert not ws.exists()
