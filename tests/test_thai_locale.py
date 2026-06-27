from collections import Counter
from pathlib import Path
import re


REPO = Path(__file__).resolve().parent.parent


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_locale_block(src: str, locale_key: str) -> str:
    start_match = re.search(rf"\b{re.escape(locale_key)}\s*:\s*\{{", src)
    assert start_match, f"{locale_key} locale block not found"

    start = start_match.end() - 1
    depth = 0
    in_single = False
    in_double = False
    in_backtick = False
    escape = False

    for i in range(start, len(src)):
        ch = src[i]

        if escape:
            escape = False
            continue

        if in_single:
            if ch == "\\":
                escape = True
            elif ch == "'":
                in_single = False
            continue

        if in_double:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
            continue

        if in_backtick:
            if ch == "\\":
                escape = True
            elif ch == "`":
                in_backtick = False
            continue

        if ch == "'":
            in_single = True
            continue
        if ch == '"':
            in_double = True
            continue
        if ch == "`":
            in_backtick = True
            continue

        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1 : i]

    raise AssertionError(f"{locale_key} locale block braces are not balanced")


def locale_keys(src: str, locale_key: str) -> list[str]:
    key_pattern = re.compile(r"^\s*([a-zA-Z0-9_]+)\s*:", re.MULTILINE)
    return key_pattern.findall(extract_locale_block(src, locale_key))


def test_thai_locale_block_exists():
    src = read(REPO / "static-legacy" / "i18n.js")
    th_block = extract_locale_block(src, "th")
    assert th_block
    assert "_lang: 'th'" in th_block
    assert "_label: 'ไทย'" in th_block
    assert "_speech: 'th-TH'" in th_block


def test_thai_locale_includes_representative_translations():
    src = read(REPO / "static-legacy" / "i18n.js")
    th_block = extract_locale_block(src, "th")
    expected = [
        "settings_title: 'การตั้งค่า'",
        "settings_label_language: 'ภาษา'",
        "login_title: 'เข้าสู่ระบบ'",
        "approval_heading: 'ต้องการการอนุมัติ'",
        "tab_chat: 'แชท'",
        "tab_tasks: 'งาน'",
        "tab_profiles: 'โปรไฟล์ Agent'",
        "empty_title: 'ให้ช่วยอะไรได้บ้าง?'",
        "onboarding_title: 'ยินดีต้อนรับสู่ Hermes Web UI'",
        "kanban_subtitle: 'บอร์ดหลายเอเจนต์ถาวร สำหรับงานที่เอเจนต์หยิบไปทำและจบได้เอง'",
        "kanban_dispatch: 'ส่งงาน'",
    ]
    for entry in expected:
        assert entry in th_block


def test_thai_settings_detail_descriptions_are_translated():
    src = read(REPO / "static-legacy" / "i18n.js")
    th_block = extract_locale_block(src, "th")
    expected = [
        "settings_desc_workspace_panel_open: 'เมื่อเปิดใช้ แผง workspace/ไฟล์บราว์เซอร์จะเปิดอัตโนมัติในแต่ละบทสนทนา'",
        "settings_desc_notifications: 'แจ้งเตือนระบบเมื่อคำตอบเสร็จขณะแอปอยู่เบื้องหลัง'",
        "settings_desc_token_usage: 'แสดงจำนวน input/output token ใต้คำตอบ assistant สลับด้วย /usage ได้'",
        "settings_desc_sidebar_density: 'ควบคุม metadata ที่รายการเซสชันในแถบด้านข้างแสดง'",
        "settings_desc_auto_title_refresh: 'สร้างชื่อเซสชันใหม่จากบทสนทนาล่าสุดอัตโนมัติ'",
        "settings_desc_external_sessions: 'แสดงบทสนทนาจาก CLI, Telegram, Discord, Slack และช่องทางอื่นในรายการ'",
        "settings_desc_sync_insights: 'ซิงค์การใช้โทเค็น WebUI ไป state.db เพื่อให้ hermes /insights รวมเซสชันเบราว์เซอร์'",
        "settings_desc_check_updates: 'แสดงแบนเนอร์เมื่อมี WebUI หรือ Agent เวอร์ชันใหม่'",
        "settings_desc_bot_name: 'ใช้กับโปรไฟล์เริ่มต้นเท่านั้น โปรไฟล์อื่นใช้ชื่อของตัวเอง'",
        "settings_desc_password: 'ป้อนรหัสผ่านใหม่เพื่อตั้งหรือเปลี่ยน ว่างไว้เพื่อคงค่าปัจจุบัน'",
    ]
    for entry in expected:
        assert entry in th_block


def test_thai_locale_matches_english_key_coverage():
    src = read(REPO / "static-legacy" / "i18n.js")
    en_keys = set(locale_keys(src, "en"))
    th_keys = set(locale_keys(src, "th"))
    assert sorted(en_keys - th_keys) == []
    assert sorted(th_keys - en_keys) == []


def test_thai_locale_has_no_duplicate_keys():
    src = read(REPO / "static-legacy" / "i18n.js")
    keys = locale_keys(src, "th")
    duplicates = sorted(k for k, count in Counter(keys).items() if count > 1)
    assert not duplicates, f"Thai locale has duplicate keys: {duplicates}"


def test_thai_locale_keys_use_standard_indentation():
    src = read(REPO / "static-legacy" / "i18n.js")
    th_block = extract_locale_block(src, "th")
    badly_indented = [
        line.strip()
        for line in th_block.splitlines()
        if re.match(r"^\s{1,3}[a-zA-Z0-9_]+\s*:", line)
    ]
    assert badly_indented == []
