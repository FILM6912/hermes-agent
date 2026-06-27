"""Terminal and execute_code should share the WebUI virtualenv."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


def _extract_build_agent_thread_env():
    src = Path("app/domain/streaming.py").read_text(encoding="utf-8")
    match = re.search(
        r"(def _build_agent_thread_env\(.*?\n)(?=\ndef |\nclass )",
        src,
        re.DOTALL,
    )
    assert match, "_build_agent_thread_env not found"
    ns: dict = {"Path": Path, "os": os}
    exec(compile(match.group(1), "<streaming_extract>", "exec"), ns)
    return ns["_build_agent_thread_env"]


def test_build_agent_thread_env_pins_virtualenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_root = tmp_path / "venv"
    bin_dir = venv_root / "bin"
    bin_dir.mkdir(parents=True)
    (venv_root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    python = bin_dir / "python3"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)

    monkeypatch.setenv("HERMES_WEBUI_VIRTUAL_ENV", str(venv_root))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    build_env = _extract_build_agent_thread_env()
    env = build_env(
        {"TERMINAL_ENV": "local"},
        str(tmp_path / "workspace"),
        "sess-1",
        str(tmp_path / "profile"),
    )

    assert env["VIRTUAL_ENV"] == str(venv_root)
    assert env["PATH"].startswith(f"{bin_dir}{os.pathsep}")


def test_resolve_webui_virtual_env_honors_explicit_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import config as config_mod

    explicit = tmp_path / "custom-venv"
    explicit.mkdir()
    monkeypatch.setenv("HERMES_WEBUI_VIRTUAL_ENV", str(explicit))
    assert config_mod.resolve_webui_virtual_env() == str(explicit)


def test_discover_python_skips_broken_agent_venv_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import config as config_mod

    agent_dir = tmp_path / "hermes-agent"
    venv_bin = agent_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    broken = venv_bin / "python"
    broken.symlink_to("/nonexistent/python3")

    good_venv = tmp_path / "venv"
    good_bin = good_venv / "bin"
    good_bin.mkdir(parents=True)
    (good_venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    good_py = good_bin / "python3"
    good_py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    good_py.chmod(0o755)

    monkeypatch.delenv("HERMES_WEBUI_PYTHON", raising=False)
    monkeypatch.setattr(config_mod.sys, "executable", str(good_py))
    monkeypatch.setattr(config_mod, "REPO_ROOT", tmp_path)

    assert config_mod._discover_python(agent_dir) == str(good_py)
