"""Regression: CSP must allow WebAssembly compilation for Extend UI viewers."""
import re
from pathlib import Path

_HELPERS_PY = Path(__file__).resolve().parents[1] / "app/domain/helpers.py"
_SECURITY_PY = Path(__file__).resolve().parents[1] / "app/middleware/security.py"


def _csp_from_helpers() -> str:
    text = _HELPERS_PY.read_text(encoding="utf-8")
    match = re.search(
        r"'Content-Security-Policy',\s*\n\s*\"([^\"]+)\"",
        text,
    )
    assert match, "enforcing CSP string not found in helpers.py"
    return match.group(1)


def _csp_report_only() -> str:
    text = _SECURITY_PY.read_text(encoding="utf-8")
    match = re.search(
        r'return \(\s*\n\s*\"([^\"]+)\"',
        text,
    )
    assert match, "report-only CSP builder not found in security.py"
    return match.group(1)


class TestCSPWasmUnsafeEval:
    def test_enforcing_script_src_allows_wasm(self):
        script_match = re.search(r"script-src\s+([^;]+);", _csp_from_helpers())
        assert script_match, "script-src directive must exist"
        assert "'wasm-unsafe-eval'" in script_match.group(1), (
            "script-src must include 'wasm-unsafe-eval' for Extend UI WASM viewers"
        )

    def test_enforcing_worker_src_allows_blob_workers(self):
        worker_match = re.search(r"worker-src\s+([^;]+);", _csp_from_helpers())
        assert worker_match, "worker-src directive must exist"
        sources = worker_match.group(1)
        assert "'self'" in sources and "blob:" in sources, (
            "worker-src must allow same-origin and blob workers"
        )

    def test_report_only_script_src_allows_wasm(self):
        script_match = re.search(r"script-src\s+([^;]+);", _csp_report_only())
        assert script_match, "report-only script-src directive must exist"
        assert "'wasm-unsafe-eval'" in script_match.group(1)
