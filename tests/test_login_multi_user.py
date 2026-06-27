"""Login page must show username server-side when multi-user mode is active."""

from __future__ import annotations

import importlib


def test_login_template_has_multi_user_placeholders():
    routes = (importlib.import_module("app.domain.routes").__file__)
    text = open(routes, encoding="utf-8").read()
    assert "{{LOGIN_MULTI_USER_ATTR}}" in text
    assert "{{LOGIN_USERNAME_ATTRS}}" in text
    assert "{{LOGIN_PW_ATTRS}}" in text
    login_block = text[text.find('if parsed.path == "/login"'): text.find('if parsed.path == "/api/auth/status"')]
    assert "is_multi_user_enabled" in login_block


def test_login_js_enables_multi_user_from_form_attribute():
    login_js = open("static-legacy/login.js", encoding="utf-8").read()
    assert "data-multi-user') === '1'" in login_js
    assert "if (multiUser) enableMultiUserLogin();" in login_js


def test_login_js_posts_username_and_password_in_multi_user_mode():
    login_js = open("static-legacy/login.js", encoding="utf-8").read()
    assert "function isMultiUserLogin()" in login_js
    assert "function buildLoginBody()" in login_js
    assert "return { username: uname, password: pw }" in login_js
    assert "JSON.stringify(body)" in login_js


def test_login_page_html_for_multi_user_mode(monkeypatch):
    routes_mod = importlib.import_module("app.domain.routes")
    monkeypatch.setattr("app.domain.users.is_multi_user_enabled", lambda: True)

    strings = routes_mod._LOGIN_LOCALE["en"]
    page = (
        routes_mod._LOGIN_PAGE_HTML.replace("{{BOT_NAME}}", "Hermes")
        .replace("{{BOT_NAME_INITIAL}}", "H")
        .replace("{{WEBUI_VERSION}}", "test")
        .replace("{{LANG}}", strings["lang"])
        .replace("{{LOGIN_TITLE}}", strings["title"])
        .replace(
            "{{LOGIN_SUBTITLE}}",
            strings.get("multi_user_subtitle", strings["subtitle"]),
        )
        .replace('{{LOGIN_MULTI_USER_ATTR}}', ' data-multi-user="1"')
        .replace("{{LOGIN_USERNAME_ATTRS}}", " autofocus required")
        .replace("{{LOGIN_PW_ATTRS}}", "")
        .replace(
            "{{LOGIN_MULTI_USER_SUBTITLE}}",
            strings.get("multi_user_subtitle", ""),
        )
        .replace(
            "{{LOGIN_USERNAME_PLACEHOLDER}}",
            strings.get("username_placeholder", "Username"),
        )
        .replace(
            "{{LOGIN_USERNAME_REQUIRED}}",
            strings.get("username_required", "Username required"),
        )
        .replace("{{LOGIN_PLACEHOLDER}}", strings["placeholder"])
        .replace("{{LOGIN_BTN}}", strings["btn"])
        .replace("{{LOGIN_INVALID_PW}}", strings["invalid_pw"])
        .replace("{{LOGIN_CONN_FAILED}}", strings["conn_failed"])
    )
    assert 'data-multi-user="1"' in page
    assert 'id="username"' in page
    assert "display:none" not in page.split('id="username"')[1].split(">")[0]
    assert "autofocus required" in page
