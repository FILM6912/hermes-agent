"""โหลดเทมเพลต prompt จากไฟล์ในโฟลเดอร์ `prompts/` ที่ root โปรเจกต์"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"


def prompts_dir() -> Path:
    return _PROMPTS_DIR


def load_markdown_section(*, filename: str, section: str) -> str:
    """
    อ่านไฟล์ markdown ใน prompts/ แล้วดึงบล็อกหลังหัวข้อ `## {section}` จนถึง `##` ถัดไปหรือจบไฟล์
    """
    path = _PROMPTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"ไม่พบไฟล์ prompt: {path}")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    capturing = False
    parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            name = stripped[3:].strip()
            if name == section:
                capturing = True
                continue
            if capturing:
                break
            continue
        if capturing:
            parts.append(line)
    body = "\n".join(parts).strip()
    if not body:
        raise ValueError(f"ไม่พบส่วน ## {section} ใน {path}")
    return body


def load_system_prompt(*, filename: str, section: str) -> str:
    """ข้อความ system จาก ``prompts/`` — ไฟล์ไม่มีตัวแทน ``__KEY__``; ข้อมูลไดนามิกประกอบเป็นข้อความ user ในโค้ด"""
    return load_markdown_section(filename=filename, section=section)


def render_prompt(filename: str, section: str, replacements: dict[str, str]) -> str:
    """โหลดไฟล์ markdown ใน prompts/ แล้วแทนที่ตัวแทน __KEY__ (ค่าต้องเป็น str แล้ว)"""
    tpl = load_markdown_section(filename=filename, section=section)
    out = tpl
    for key, val in replacements.items():
        out = out.replace(key, val)
    return out
