#!/usr/bin/env python3
"""Patch hermes-agent skill_view to resolve skills by frontmatter name.

skills_list() indexes skills using YAML frontmatter ``name``, but skill_view()
strategy 2 only matched directory names. Skills installed via npx skills can
use a directory slug that differs from the frontmatter name (e.g. soft-skill vs
high-end-visual-design), which made skill_view fail while skills_list succeeded.

This script is idempotent and safe to run on every container start.
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD_BLOCK = """            for found_skill_md in iter_skill_index_files(search_dir, "SKILL.md"):
                if found_skill_md.parent.name == name:
                    _record(found_skill_md.parent, found_skill_md)
"""

NEW_BLOCK = """            for found_skill_md in iter_skill_index_files(search_dir, "SKILL.md"):
                skill_parent = found_skill_md.parent
                if skill_parent.name == name:
                    _record(skill_parent, found_skill_md)
                    continue
                try:
                    frontmatter, _ = _parse_frontmatter(
                        found_skill_md.read_text(encoding="utf-8")[:4000]
                    )
                    if frontmatter.get("name") == name:
                        _record(skill_parent, found_skill_md)
                except Exception:
                    continue
"""

MARKER = "frontmatter.get(\"name\") == name"


def patch_skills_tool(path: Path) -> bool:
    """Return True when the file was modified or already patched."""
    if not path.is_file():
        print(f"skip: skills_tool.py not found at {path}", file=sys.stderr)
        return False

    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"ok: already patched {path}")
        return True

    if OLD_BLOCK not in text:
        print(f"warn: unexpected skills_tool.py layout at {path}; patch not applied", file=sys.stderr)
        return False

    path.write_text(text.replace(OLD_BLOCK, NEW_BLOCK, 1), encoding="utf-8")
    print(f"patched: {path}")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: patch_agent_skill_view_frontmatter.py <skills_tool.py> [...]", file=sys.stderr)
        return 2

    changed = 0
    for raw in argv[1:]:
        if patch_skills_tool(Path(raw)):
            changed += 1
    return 0 if changed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
