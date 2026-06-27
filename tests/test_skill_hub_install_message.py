from app.domain.skill_hub_install_message import (
    strip_terminal_ansi,
    summarize_npx_skills_message,
    summarize_skill_install_message,
)

SAMPLE_REPO_OUTPUT = """
[38;5;250m[OK][0m Cloning repository
◇  Found 18 skills
◇  Installed 18 skills
│
◇  Installed 18 skills ─────────────────────────╮
│  ✓ ./.agents/skills/xlsx                      │
│  ✓ ./.agents/skills/pptx                      │
│  ✓ ./.agents/skills/pdf                       │
╰───────────────────────────────────────────────╯
"""


def test_strip_terminal_ansi_removes_spinner_fragments():
    raw = "[38;5;250mHello[0m \x1b[32mworld\x1b[0m"
    assert strip_terminal_ansi(raw) == "Hello world"


def test_summarize_repo_install_output():
    message = summarize_npx_skills_message(
        SAMPLE_REPO_OUTPUT,
        repo="anthropics/skills",
        ok=True,
    )
    assert message == "Installed 18 skills from anthropics/skills"


def test_summarize_single_skill_install():
    message = summarize_npx_skills_message(
        "◇ Installed 1 skill\n✓ ./.agents/skills/xlsx",
        repo="anthropics/skills",
        skill="xlsx",
        ok=True,
    )
    assert message == "Installed xlsx from anthropics/skills"


def test_summarize_skill_install_message_handles_rich_error():
    message = summarize_skill_install_message(
        "Error: Could not fetch 'skills-sh/x' from any source.",
        ok=False,
    )
    assert "Could not fetch" in message
