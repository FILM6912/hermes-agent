"""Regression coverage for faster Docker container restarts."""

from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parents[1]
INIT_SCRIPT = (REPO / "docker_init.bash").read_text(encoding="utf-8")
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")
STARTUP_PY = (REPO / "app" / "core" / "startup.py").read_text(encoding="utf-8")


def test_docker_init_skips_rsync_when_sync_stamp_matches():
    assert ".docker_sync_stamp" in INIT_SCRIPT
    assert "Skipping /apptoo -> /app rsync" in INIT_SCRIPT


def test_dockerfile_writes_sync_stamp_at_build_time():
    assert ".docker_sync_stamp" in DOCKERFILE


def test_docker_init_skips_home_chown_when_probe_uid_matches():
    chown_start = INIT_SCRIPT.index("chown_home_hermeswebui()")
    chown_end = INIT_SCRIPT.index("\n}\n", chown_start)
    fn_block = INIT_SCRIPT[chown_start:chown_end]
    assert "Skipping recursive home chown" in fn_block


def test_docker_init_always_chowns_agents_skills_bind_mount():
    assert "chown_agents_skills_bind_mount()" in INIT_SCRIPT
    call_site = INIT_SCRIPT.index("chown_home_hermeswebui || error_exit")
    after_home_chown = INIT_SCRIPT[call_site : call_site + 200]
    assert "chown_agents_skills_bind_mount" in after_home_chown


def test_docker_init_hindsight_fast_restart_marker():
    assert ".hindsight_installed" in INIT_SCRIPT
    assert "hindsight-client already verified (fast restart)" in INIT_SCRIPT


def test_dockerfile_preinstalls_agent_deps_at_build_time():
    assert "hermes-agent-build" in DOCKERFILE
    assert ".agent_deps_installed" in DOCKERFILE
    assert ".deps_installed" in DOCKERFILE
    assert '"/apptoo/hermes-agent-build[all]"' in DOCKERFILE


def test_docker_init_skips_agent_deps_when_image_baked():
    assert "hermes-agent Python deps pre-installed in image" in INIT_SCRIPT
    assert "HERMES_WEBUI_REINSTALL_AGENT_DEPS" in INIT_SCRIPT


def test_docker_init_pins_webui_virtualenv_and_repairs_agent_venv():
    assert "HERMES_WEBUI_VIRTUAL_ENV=/app/venv" in INIT_SCRIPT
    assert "repair_agent_venv_python" in INIT_SCRIPT
    assert "read-only mount; WebUI uses /app/venv" in INIT_SCRIPT


def test_startup_defers_container_startup_work_to_background_threads():
    assert "startup_session_recovery" in STARTUP_PY
    assert "startup_agent_import_check" in STARTUP_PY
    assert "_deferred_container_startup_tasks" in STARTUP_PY
    assert 'name="container-startup"' in STARTUP_PY
    assert "rebuild_index=False" in STARTUP_PY


def test_docker_init_bash_syntax_still_valid():
    result = subprocess.run(
        ["bash", "-n", str(REPO / "docker_init.bash")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
