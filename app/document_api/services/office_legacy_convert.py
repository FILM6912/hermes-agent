from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Legacy / alternate Office formats → LibreOffice convert-to target (modern OOXML).
LEGACY_OFFICE_TARGETS: dict[str, str] = {
    ".doc": "docx",
    ".dot": "docx",
    ".ppt": "pptx",
    ".pot": "pptx",
    ".pps": "pptx",
    ".ppsm": "pptx",
    ".xls": "xlsx",
    ".xlsb": "xlsx",
    ".odt": "docx",
    ".ods": "xlsx",
    ".odp": "pptx",
}

LEGACY_OFFICE_EXTENSIONS: frozenset[str] = frozenset(LEGACY_OFFICE_TARGETS)


class OfficeLegacyConvertError(RuntimeError):
    pass


def is_legacy_office_extension(suffix: str) -> bool:
    return suffix.lower() in LEGACY_OFFICE_EXTENSIONS


def find_soffice_binary() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


def convert_legacy_office_file(src: Path, out_dir: Path, *, timeout_sec: int = 300) -> Path:
    """Convert legacy Office binary to modern OOXML via headless LibreOffice."""
    suffix = src.suffix.lower()
    target = LEGACY_OFFICE_TARGETS.get(suffix)
    if not target:
        raise OfficeLegacyConvertError(f"no LibreOffice target for {suffix}")

    soffice = find_soffice_binary()
    if not soffice:
        raise OfficeLegacyConvertError(
            "LibreOffice (soffice) is required for legacy Office formats "
            f"such as {suffix}; install libreoffice-writer/calc/impress or libreoffice package"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = out_dir / "lo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--nologo",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to",
        target,
        "--outdir",
        str(out_dir.resolve()),
        str(src.resolve()),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            timeout=timeout_sec,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise OfficeLegacyConvertError(f"LibreOffice timed out converting {src.name}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise OfficeLegacyConvertError(
            f"LibreOffice failed to convert {src.name}"
            + (f": {detail[:500]}" if detail else "")
        )

    modern_ext = f".{target}"
    out_path = out_dir / f"{src.stem}{modern_ext}"
    if not out_path.is_file():
        candidates = sorted(out_dir.glob(f"{src.stem}*{modern_ext}"))
        if len(candidates) == 1:
            out_path = candidates[0]
        else:
            raise OfficeLegacyConvertError(
                f"LibreOffice did not produce expected {modern_ext} for {src.name}"
            )
    return out_path
