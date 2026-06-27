"""Regression test for issue #1968 — non-default profile MCP servers never load.

The bug: `discover_mcp_tools()` was called at the top of `_run_agent_streaming`
before the `HERMES_HOME` env mutation that stamps the per-session profile.
Result: `_load_mcp_config()` always read the default profile's
`~/.hermes/config.yaml`, never the non-default profile's MCP servers.

The fix moves the call past the `_ENV_LOCK` env-mutation block so
`discover_mcp_tools()` runs with the correct `HERMES_HOME` for the session's
profile.

This is a static check (source ordering) rather than a runtime test, because
mocking the entire agent stack to reach the call site would be brittle and
miss the actual lexical ordering that's the load-bearing fix.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STREAMING_PY = (ROOT / "app" / "domain" / "streaming.py").read_text(encoding="utf-8")


def _line_of(pattern: str) -> int:
    """Return the 1-indexed line number of the first match for `pattern`."""
    for idx, line in enumerate(STREAMING_PY.splitlines(), start=1):
        if re.search(pattern, line):
            return idx
    raise AssertionError(f"pattern not found in api/streaming.py: {pattern!r}")


def test_discover_profile_mcp_tools_called_after_hermes_home_mutation():
    """The fix for #1968: profile MCP discovery must execute AFTER the
    `HERMES_HOME = _profile_home` assignment, otherwise non-default profile
    MCP servers are never discovered.
    """
    env_apply_line = _line_of(r"_apply_process_agent_env_unlocked\(_thread_env\)")
    discover_call_line = _line_of(r"discover_profile_mcp_tools\(_profile_home\)")
    assert discover_call_line > env_apply_line, (
        f"discover_profile_mcp_tools() at line {discover_call_line} must be AFTER the "
        f"profile env apply at line {env_apply_line} (issue #1968). "
        "Otherwise non-default profile MCP servers never load."
    )


def test_discover_profile_mcp_tools_called_after_env_lock_release():
    """Profile MCP discovery should run AFTER the `_ENV_LOCK` block releases —
    discovery itself can take up to 120s (per `_run_on_mcp_loop` timeout in
    hermes-agent), and holding the env lock across that would serialize all
    concurrent sessions through MCP discovery.

    Lexical check: the discover call must come after the `# Lock released` marker
    that follows the `with _ENV_LOCK:` block.
    """
    lock_release_marker = _line_of(r"# Lock released — agent runs without holding it")
    discover_call_line = _line_of(r"discover_profile_mcp_tools\(_profile_home\)")
    assert discover_call_line > lock_release_marker, (
        f"discover_profile_mcp_tools() at line {discover_call_line} should run AFTER "
        f"the _ENV_LOCK release at line {lock_release_marker}, not inside the "
        "lock block (which would serialize MCP discovery across sessions)."
    )


def test_discover_profile_mcp_tools_only_called_once_in_streaming():
    """Sanity check: only one profile MCP discovery call in streaming.py."""
    call_lines = [
        line for line in STREAMING_PY.splitlines()
        if "discover_profile_mcp_tools(" in line
        and not line.lstrip().startswith("#")
    ]
    assert len(call_lines) == 1, (
        f"Expected exactly 1 discover_profile_mcp_tools() call in streaming.py "
        f"(comments excluded), found {len(call_lines)}: {call_lines!r}."
    )


def test_discover_profile_mcp_tools_call_is_inside_try_except():
    """MCP discovery is best-effort — failures must not crash the chat stream."""
    lines = STREAMING_PY.splitlines()
    call_idx = None
    for idx, line in enumerate(lines):
        if "discover_profile_mcp_tools(" in line and not line.lstrip().startswith("#"):
            call_idx = idx
            break
    assert call_idx is not None, "discover_profile_mcp_tools() call line not found"
    block_start = max(0, call_idx - 12)
    block_end = min(len(lines), call_idx + 5)
    block = "\n".join(lines[block_start:block_end])
    assert "try:" in block, (
        f"discover_profile_mcp_tools() at line {call_idx + 1} must be inside a try block "
        "so MCP failures don't crash the chat stream.  Surrounding code:\n" + block
    )
    assert "except" in block, (
        f"discover_profile_mcp_tools() at line {call_idx + 1} must have an except clause."
    )
