"""HashRouter login redirects must not use legacy /login?next= pathname URLs."""

from __future__ import annotations

from app.core.security import is_public_path, is_spa_shell_path, spa_login_redirect_url


def test_spa_shell_paths_are_public_without_server_login_redirect():
    assert is_spa_shell_path("/")
    assert is_spa_shell_path("/chat")
    assert is_spa_shell_path("/chat/abc")
    assert is_public_path("/")
    assert is_public_path("/chat")


def test_spa_login_redirect_uses_hash_router_format():
    assert spa_login_redirect_url("/chat") == "/#/login?next=/chat"
    assert spa_login_redirect_url("/#/chat") == "/#/login?next=/chat"


def test_react_login_redirect_utils_exist():
    src = open("frontend/src/features/auth/utils/loginRedirect.ts", encoding="utf-8").read()
    assert "normalizeLegacyLoginUrl" in src
    assert "resolvePostLoginPath" in src
    api = open("frontend/src/lib/api.ts", encoding="utf-8").read()
    assert "window.location.href = `/#/login?next=${next}`" in api
