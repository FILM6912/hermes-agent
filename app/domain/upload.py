"""
Hermes Web UI -- File upload: multipart parser and upload handler.
"""
import logging
import mimetypes
import os
import re as _re
import email.parser
import shutil
import tempfile
from pathlib import Path

from app.domain.config import MAX_UPLOAD_BYTES, STATE_DIR
from app.domain.helpers import j, bad
from app.domain.models import get_session
from app.domain.workspace import resolve_trusted_workspace, safe_resolve_ws

_MAX_EXTRACTED_BYTES = 10 * MAX_UPLOAD_BYTES
WORKSPACE_UPLOADS_SUBDIR = ".uploads"
_ATTACHMENT_AT_SUFFIX_RE = _re.compile(
    r"\n\n((?:@[^\s\n]+)(?:\s+@[^\s\n]+)*)\s*$",
)
_LEGACY_ATTACHED_FILES_SUFFIX_RE = _re.compile(
    r"\n\n\[Attached files: ([^\]]+)\]\s*$",
    _re.DOTALL,
)


def attachment_at_token(path: str) -> str:
    """Return a composer-style ``@path`` token for agent-facing attachment hints."""
    token = str(path or "").strip()
    if not token:
        return ""
    if token.startswith("@"):
        return token
    return f"@{token}"


def format_attachment_path_suffix(paths: list[str]) -> str:
    """Append ``@path`` tokens after the user message (composer @-mention parity)."""
    tokens = [attachment_at_token(path) for path in paths if str(path).strip()]
    if not tokens:
        return ""
    return f"\n\n{' '.join(tokens)}"


def parse_attachment_path_suffix(message: str) -> list[str]:
    """Extract workspace paths from a trailing ``@path`` or legacy suffix."""
    if not message:
        return []
    match = _ATTACHMENT_AT_SUFFIX_RE.search(message)
    if match:
        return [
            token[1:] if token.startswith("@") else token
            for token in match.group(1).split()
            if token.strip()
        ]
    match = _LEGACY_ATTACHED_FILES_SUFFIX_RE.search(message)
    if match:
        return [part.strip() for part in match.group(1).split(",") if part.strip()]
    return []


def strip_attachment_path_suffix(message: str) -> str:
    """Drop agent-only attachment suffixes for display and transcript matching."""
    if not message:
        return message
    message = _ATTACHMENT_AT_SUFFIX_RE.sub("", message, count=1).rstrip()
    return _LEGACY_ATTACHED_FILES_SUFFIX_RE.sub("", message, count=1).rstrip()


_INLINE_AT_PATH_RE = _re.compile(r"(?:^|\s)@([^\s\n@]+)")
_UPLOAD_ONLY_BOILERPLATE_RE = _re.compile(
    r"^I've uploaded \d+ file\(s\):\s*(.*)$",
    _re.IGNORECASE | _re.DOTALL,
)
_LEGACY_FILES_SUFFIX_RE = _re.compile(r"\n\n_Files: [^_]+_\s*$")


def _is_path_like_at_token(path: str) -> bool:
    token = str(path or "").strip()
    if not token:
        return False
    if token.startswith((".", "/", "\\")):
        return True
    if "/" in token or "\\" in token:
        return True
    if len(token) >= 2 and token[1] == ":":
        return True
    return False


def _looks_like_upload_only_boilerplate(text: str) -> bool:
    match = _UPLOAD_ONLY_BOILERPLATE_RE.match(str(text or "").strip())
    if not match:
        return False
    rest = str(match.group(1) or "").strip()
    if not rest:
        return True
    tokens = [part.strip() for part in _re.split(r"[\s,]+", rest) if part.strip()]
    if not tokens:
        return True
    for token in tokens:
        bare = token[1:] if token.startswith("@") else token
        if token.startswith("@") and _is_path_like_at_token(bare):
            continue
        if _re.fullmatch(r"[\w.\-]+", bare):
            continue
        return False
    return True


def strip_attachment_paths_for_display(message: str) -> str:
    """Drop ``@path`` attachment hints from transcript display text only."""
    if not message:
        return message
    text = strip_attachment_path_suffix(message)
    text = _LEGACY_FILES_SUFFIX_RE.sub("", text, count=1).rstrip()

    def _strip_inline(match: _re.Match[str]) -> str:
        path = match.group(1)
        if _is_path_like_at_token(path):
            return " " if match.group(0).startswith((" ", "\t")) else ""
        return match.group(0)

    text = _INLINE_AT_PATH_RE.sub(_strip_inline, text)
    text = _re.sub(r"[ \t]{2,}", " ", text)
    text = _re.sub(r"\n{3,}", "\n\n", text).strip()
    if _looks_like_upload_only_boilerplate(text):
        return ""
    return text

logger = logging.getLogger(__name__)


def parse_multipart(rfile, content_type, content_length) -> tuple:
    import re as _re, email.parser as _ep
    m = _re.search(r'boundary=([^;\s]+)', content_type)
    if not m:
        raise ValueError('No boundary in Content-Type')
    boundary = m.group(1).strip('"').encode()
    raw = rfile.read(content_length)
    fields = {}
    files = {}
    delimiter = b'--' + boundary
    end_marker = b'--' + boundary + b'--'
    parts = raw.split(delimiter)
    for part in parts[1:]:
        stripped = part.lstrip(b'\r\n')
        if stripped.startswith(b'--'):
            break
        sep = b'\r\n\r\n' if b'\r\n\r\n' in part else b'\n\n'
        if sep not in part:
            continue
        header_raw, body = part.split(sep, 1)
        if body.endswith(b'\r\n'):
            body = body[:-2]
        elif body.endswith(b'\n'):
            body = body[:-1]
        header_text = header_raw.lstrip(b'\r\n').decode('utf-8', errors='replace')
        msg = _ep.HeaderParser().parsestr(header_text)
        disp = msg.get('Content-Disposition', '')
        name_m = _re.search(r'name="([^"]*)"', disp)
        file_m = _re.search(r'filename="([^"]*)"', disp)
        if not name_m:
            continue
        name = name_m.group(1)
        if file_m:
            files[name] = (file_m.group(1), body)
        else:
            fields[name] = body.decode('utf-8', errors='replace')
    return fields, files


def _sanitize_upload_name(filename: str) -> str:
    """Return an ASCII-safe on-disk upload basename.

    Non-ASCII characters (e.g. Thai filenames) are normalized to underscores so
    shell tools and vision backends can open the saved file reliably.
    """
    raw_name = Path(filename).name
    suffix = Path(raw_name).suffix
    stem = Path(raw_name).stem
    safe_stem = _re.sub(r'[^\w.\-]', '_', stem, flags=_re.ASCII).strip('._-')
    safe_suffix = _re.sub(r'[^\w.\-]', '', suffix, flags=_re.ASCII)
    if not safe_stem:
        safe_stem = 'upload'
    safe_name = f'{safe_stem[:180]}{safe_suffix}'[:200]
    if not safe_name or safe_name.strip('.') == '':
        raise ValueError('Invalid filename')
    return safe_name


def _attachment_root() -> Path:
    """Return the legacy per-session attachment inbox root.

    Chat uploads now land in ``<workspace>/.uploads/`` by default. The inbox is
    still used for archive extraction and as a fallback when no workspace can
    be resolved. Operators can override the inbox with HERMES_WEBUI_ATTACHMENT_DIR.
    """
    override = os.getenv('HERMES_WEBUI_ATTACHMENT_DIR', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    return (STATE_DIR / 'attachments').resolve()


def _unique_path_in_dir(dest_dir: Path, safe_name: str) -> Path:
    dest_dir = dest_dir.resolve()
    dest = (dest_dir / safe_name).resolve()
    if not dest.is_relative_to(dest_dir):
        raise ValueError('Invalid upload destination')
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    for idx in range(1, 1000):
        candidate = (dest_dir / f'{stem}-{idx}{suffix}').resolve()
        if not candidate.is_relative_to(dest_dir):
            raise ValueError('Invalid upload destination')
        if not candidate.exists():
            return candidate
    raise ValueError('Too many uploads with the same filename')


def _upload_destination(session_id: str, safe_name: str) -> Path:
    dest_dir = _session_attachment_dir(session_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    return _unique_path_in_dir(dest_dir, safe_name)


def _resolve_chat_upload_workspace(
    session_id: str,
    workspace_field: str = "",
) -> Path | None:
    from app.domain.workspace import nested_workspaces_enabled, resolve_main_user_workspace_root

    token = str(workspace_field or '').strip()
    try:
        if not token:
            session = get_session(session_id)
            token = str(getattr(session, 'workspace', '') or '').strip()
    except KeyError:
        return None

    if nested_workspaces_enabled():
        try:
            return resolve_main_user_workspace_root(token or None)
        except (ValueError, OSError) as exc:
            logger.debug(
                "Chat upload workspace %r unavailable for this account (%s); "
                "using account main workspace root",
                token or None,
                exc,
            )
            try:
                return resolve_main_user_workspace_root(None)
            except (ValueError, OSError):
                logger.warning(
                    "Could not resolve account main workspace for upload (session=%s)",
                    session_id,
                    exc_info=True,
                )
                return None

    if not token:
        return None
    try:
        return resolve_main_user_workspace_root(token)
    except (ValueError, OSError):
        logger.debug(
            "Could not resolve upload workspace from token %r (session=%s)",
            token,
            session_id,
            exc_info=True,
        )
        return None


def _workspace_uploads_dir(workspace_root: Path) -> Path:
    from app.domain.workspace import ensure_directory_writable

    uploads = safe_resolve_ws(workspace_root, WORKSPACE_UPLOADS_SUBDIR)
    ensure_directory_writable(uploads)
    return uploads


def _workspace_upload_destination(workspace_root: Path, safe_name: str) -> tuple[Path, str]:
    uploads_dir = _workspace_uploads_dir(workspace_root)
    dest = _unique_path_in_dir(uploads_dir, safe_name)
    rel = dest.relative_to(workspace_root.resolve()).as_posix()
    return dest, rel


def _upload_payload_for_path(dest: Path, *, workspace_rel: str = '') -> dict:
    mime = mimetypes.guess_type(dest.name)[0] or 'application/octet-stream'
    payload = {
        'filename': dest.name,
        'path': str(dest),
        'size': dest.stat().st_size,
        'mime': mime,
        'is_image': mime.startswith('image/'),
    }
    if workspace_rel:
        payload['workspace_rel'] = workspace_rel
    return payload


def _rewrite_attached_files_marker(message: str, replacements: dict[str, str]) -> str:
    if not replacements or not message:
        return message
    parts = parse_attachment_path_suffix(message)
    if not parts:
        return message
    rewritten = [replacements.get(part, part) for part in parts]
    base = strip_attachment_path_suffix(message)
    return f"{base}{format_attachment_path_suffix(rewritten)}".rstrip()


def _attachment_is_image(item) -> bool:
    if not isinstance(item, dict):
        return False
    mime = str(item.get("mime") or "").strip().lower()
    return item.get("is_image") is True or mime.startswith("image/")


def _attachment_path_tokens(item) -> set[str]:
    """Return every path spelling an attachment may appear under in agent text."""
    tokens: set[str] = set()
    if not isinstance(item, dict):
        return tokens
    for key in ("name", "path", "workspace_rel"):
        token = str(item.get(key) or "").strip()
        if token:
            tokens.add(token)
    rel = attachment_workspace_rel_path(item)
    if rel:
        tokens.add(rel)
        tokens.add(Path(rel).name)
    raw = str(item.get("path") or "").strip()
    if raw:
        tokens.add(Path(raw).name)
    return {token for token in tokens if token}


def strip_image_paths_from_attached_files_marker(
    message: str,
    attachments,
) -> str:
    """Drop image ``@path`` suffix tokens for native vision turns."""
    if not message:
        return message
    parts = parse_attachment_path_suffix(message)
    if not parts:
        return message

    image_tokens: set[str] = set()
    for item in attachments or []:
        if not _attachment_is_image(item):
            continue
        image_tokens.update(_attachment_path_tokens(item))

    kept: list[str] = []
    for part in parts:
        basename = Path(part).name
        if part in image_tokens or basename in image_tokens:
            continue
        kept.append(part)

    if kept == parts:
        return message
    base = strip_attachment_path_suffix(message)
    if not kept:
        return base
    return f"{base}{format_attachment_path_suffix(kept)}".rstrip()


def _session_upload_disk_path(
    token: str,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: str | Path | None = None,
) -> str:
    """Resolve a workspace upload token to an on-disk file for the active session."""
    rel_token = str(token or "").strip().lstrip("/")
    if not rel_token:
        return ""
    profile_home_path = Path(profile_home).expanduser() if profile_home else None
    if rel_token.startswith(f"{WORKSPACE_UPLOADS_SUBDIR}/"):
        hit = resolve_workspace_uploads_relative_path(
            rel_token,
            session_workspace=session_workspace,
            session_id=session_id,
            profile_home=profile_home_path,
        )
        if hit is not None:
            return str(hit.resolve())
    return ""


def resolve_agent_attachment_path(
    path: str,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: str | Path | None = None,
) -> str:
    """Resolve agent-facing upload paths to an on-disk file when possible."""
    token = str(path or "").strip()
    if not token:
        return token

    from app.domain.workspace import rewrite_virtual_path_in_file_arg

    workspace_token = str(
        session_workspace
        or os.environ.get("TERMINAL_CWD")
        or os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL")
        or ""
    ).strip()
    profile_home_path = Path(profile_home).expanduser() if profile_home else None

    try:
        absolute_candidate = Path(token).expanduser()
        if absolute_candidate.is_absolute():
            resolved = absolute_candidate.resolve()
            if resolved.is_file():
                if path_allowed_for_native_multimodal_image(
                    resolved,
                    workspace_token or None,
                    profile_home=profile_home_path,
                ):
                    return str(resolved)
                uploads_rel = attachment_workspace_rel_path({"path": token})
                if uploads_rel:
                    remapped = _session_upload_disk_path(
                        uploads_rel,
                        session_workspace=workspace_token or None,
                        session_id=session_id,
                        profile_home=profile_home_path,
                    )
                    if remapped:
                        return remapped
    except OSError:
        pass

    rewritten = rewrite_virtual_path_in_file_arg(
        token,
        terminal_cwd=os.environ.get("TERMINAL_CWD"),
        active_workspace_virtual=os.environ.get("HERMES_WEBUI_ACTIVE_WORKSPACE_VIRTUAL"),
    )
    try:
        candidate = Path(rewritten).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
    except OSError:
        pass

    rel = token.lstrip("/")
    if rel.startswith(f"{WORKSPACE_UPLOADS_SUBDIR}/"):
        try:
            from app.domain.workspace import resolve_main_user_workspace_root

            main_root = resolve_main_user_workspace_root(
                workspace_token or None,
                profile_home=profile_home_path,
            )
            uploads_hit = (main_root / rel).resolve()
            if uploads_hit.is_file():
                return str(uploads_hit)
        except (ValueError, OSError):
            pass

    session_hit = _session_upload_disk_path(
        token,
        session_workspace=workspace_token or None,
        session_id=session_id,
        profile_home=profile_home_path,
    )
    if session_hit:
        return session_hit

    return rewritten


def stage_chat_attachments_to_workspace(
    attachments,
    workspace: str | Path,
    *,
    message: str = '',
) -> tuple[list, str]:
    """Copy legacy inbox attachments into the account main ``<workspace>/.uploads/``."""
    normalized = list(attachments or [])
    if not normalized:
        return normalized, message

    try:
        from app.domain.workspace import resolve_main_user_workspace_root

        workspace_root = resolve_main_user_workspace_root(workspace)
    except (ValueError, OSError):
        return normalized, message

    uploads_dir = _workspace_uploads_dir(workspace_root)
    attachment_root = _attachment_root()
    replacements: dict[str, str] = {}
    staged: list = []

    for item in normalized:
        if not isinstance(item, dict):
            staged.append(item)
            continue

        src_token = str(item.get('path') or '').strip()
        if not src_token:
            staged.append(item)
            continue

        try:
            src = Path(src_token).expanduser().resolve()
        except OSError:
            staged.append(item)
            continue

        if not src.is_file():
            staged.append(item)
            continue

        try:
            if src.is_relative_to(uploads_dir):
                rel = src.relative_to(workspace_root.resolve()).as_posix()
                next_item = dict(item)
                next_item['path'] = str(src)
                next_item['name'] = str(item.get('name') or src.name)
                next_item['workspace_rel'] = rel
                staged.append(next_item)
                replacements[src_token] = rel
                continue
        except ValueError:
            pass

        copy_from_inbox = False
        try:
            copy_from_inbox = src.is_relative_to(attachment_root)
        except ValueError:
            copy_from_inbox = False

        if not copy_from_inbox:
            try:
                if src.is_relative_to(workspace_root.resolve()):
                    rel = src.relative_to(workspace_root.resolve()).as_posix()
                    next_item = dict(item)
                    next_item['path'] = str(src)
                    next_item['name'] = str(item.get('name') or src.name)
                    next_item['workspace_rel'] = rel
                    staged.append(next_item)
                    replacements[src_token] = rel
                    continue
            except ValueError:
                pass
            staged.append(item)
            continue

        safe_name = _sanitize_upload_name(str(item.get('name') or src.name))
        dest, rel = _workspace_upload_destination(workspace_root, safe_name)
        shutil.copy2(src, dest)
        next_item = dict(item)
        next_item['path'] = str(dest)
        next_item['name'] = dest.name
        next_item['workspace_rel'] = rel
        staged.append(next_item)
        replacements[src_token] = rel

    return staged, _rewrite_attached_files_marker(message, replacements)


def attachment_workspace_rel_path(item) -> str:
    """Best-effort workspace-relative path for an attachment record."""
    if not isinstance(item, dict):
        return ""
    rel = str(item.get("workspace_rel") or "").strip()
    if rel:
        return rel
    raw = str(item.get("path") or "").strip()
    if not raw:
        return ""
    marker = f"/{WORKSPACE_UPLOADS_SUBDIR}/"
    idx = raw.find(marker)
    if idx >= 0:
        return raw[idx + 1 :]
    if raw.startswith(f"{WORKSPACE_UPLOADS_SUBDIR}/"):
        return raw
    name = str(item.get("name") or Path(raw).name).strip()
    if name and WORKSPACE_UPLOADS_SUBDIR in raw:
        return f"{WORKSPACE_UPLOADS_SUBDIR}/{name}"
    return ""


def build_attachment_agent_context(
    attachments,
    *,
    active_workspace: str | Path | None = None,
    omit_images: bool = False,
) -> str:
    """Explicit agent hint: uploaded files live under the account main ``.uploads/``.

    When *omit_images* is True (native vision turn), image paths are excluded so
    the agent does not call ``vision_analyze`` on local filesystem paths.
    """
    from app.domain.workspace import (
        VIRTUAL_WORKSPACE_ROOT,
        nested_workspaces_enabled,
        resolve_main_user_workspace_root,
        resolve_trusted_workspace,
    )

    paths: list[str] = []
    use_main_virtual = False
    token = str(active_workspace or "").strip()
    if token and nested_workspaces_enabled():
        try:
            main_root = resolve_main_user_workspace_root(token)
            active_root = resolve_trusted_workspace(token)
            use_main_virtual = main_root.resolve() != active_root.resolve()
        except ValueError:
            use_main_virtual = False

    for item in attachments or []:
        rel = attachment_workspace_rel_path(item)
        if not rel:
            continue
        raw_path = str(item.get("path") or "").strip()
        mime = str(item.get("mime") or "").strip().lower()
        is_image = item.get("is_image") is True or mime.startswith("image/")
        if omit_images and is_image:
            continue
        if use_main_virtual and is_image:
            name = Path(rel).name or rel
            hint_path = f"{VIRTUAL_WORKSPACE_ROOT}/{WORKSPACE_UPLOADS_SUBDIR}/{name}"
        elif is_image and raw_path:
            try:
                if Path(raw_path).expanduser().is_file():
                    hint_path = str(Path(raw_path).expanduser().resolve())
                else:
                    hint_path = rel
            except OSError:
                hint_path = rel
        else:
            hint_path = rel
        if hint_path not in paths:
            paths.append(hint_path)
    if not paths:
        return ""
    return " ".join(attachment_at_token(path) for path in paths)


def trusted_hermes_file_roots() -> list[Path]:
    """Allowed absolute roots for authenticated chat attachment file serving."""
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in (
        os.getenv("HERMES_HOME", "").strip(),
    ):
        if not candidate:
            continue
        try:
            root = Path(candidate).expanduser().resolve()
        except OSError:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    try:
        from app.domain.profiles import get_active_hermes_home

        root = get_active_hermes_home().expanduser().resolve()
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    except Exception:
        pass
    try:
        from app.domain.config import STATE_DIR

        root = STATE_DIR.resolve()
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    except Exception:
        pass
    try:
        root = _attachment_root()
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    except Exception:
        pass
    return roots


def iter_session_upload_dirs(
    session_workspace: str | None,
    *,
    profile_home: Path | None = None,
) -> list[Path]:
    """Collect ``.uploads`` directories for chat attachment serving."""
    from app.domain.workspace import (
        nested_workspaces_enabled,
        profile_workspace_dir,
        resolve_main_user_workspace_root,
        resolve_trusted_workspace,
        _virtual_workspace_disk_root_for_mapping,
    )

    dirs: list[Path] = []
    seen: set[str] = set()

    def _add_uploads_dir(uploads_dir: Path) -> None:
        try:
            resolved = uploads_dir.resolve()
        except OSError:
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        dirs.append(resolved)

    token = str(session_workspace or "").strip()
    profile_home_path = profile_home
    if token:
        try:
            main_root = resolve_main_user_workspace_root(
                token,
                profile_home=profile_home_path,
            )
            _add_uploads_dir(_workspace_uploads_dir(main_root))
        except ValueError:
            pass
        if nested_workspaces_enabled():
            try:
                active = resolve_trusted_workspace(token)
                main_root = resolve_main_user_workspace_root(
                    token,
                    profile_home=profile_home_path,
                )
                if active.resolve() != main_root.resolve():
                    _add_uploads_dir(_workspace_uploads_dir(active))
            except ValueError:
                pass

    if profile_home_path is not None:
        try:
            _add_uploads_dir(_workspace_uploads_dir(profile_workspace_dir(profile_home_path)))
        except (OSError, ValueError):
            pass

    try:
        from app.domain.profiles import get_active_hermes_home

        active_profile_home = get_active_hermes_home()
        if profile_home_path is None or active_profile_home.resolve() != profile_home_path.resolve():
            main = _virtual_workspace_disk_root_for_mapping(active_profile_home)
            _add_uploads_dir(_workspace_uploads_dir(main))
    except Exception:
        pass

    return dirs


def path_allowed_for_native_multimodal_image(
    path: Path,
    session_workspace: str | None,
    *,
    profile_home: str | Path | None = None,
) -> bool:
    """Return True when *path* may be embedded as a native multimodal image part."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False

    workspace_roots: list[Path] = []
    seen: set[str] = set()

    def _add_root(candidate: Path | None) -> None:
        if candidate is None:
            return
        try:
            root = candidate.expanduser().resolve()
        except OSError:
            return
        key = str(root)
        if key in seen:
            return
        seen.add(key)
        workspace_roots.append(root)

    for candidate in trusted_hermes_file_roots():
        _add_root(candidate)

    token = str(session_workspace or "").strip()
    profile_home_path = Path(profile_home).expanduser() if profile_home else None
    if token:
        try:
            from app.domain.workspace import resolve_main_user_workspace_root

            _add_root(resolve_trusted_workspace(token))
            _add_root(resolve_main_user_workspace_root(
                token,
                profile_home=profile_home_path,
            ))
        except ValueError:
            pass
        try:
            _add_root(Path(token))
        except OSError:
            pass

    if not any(resolved.is_relative_to(root) for root in workspace_roots):
        return False

    for ws_root in workspace_roots:
        try:
            if resolved.is_relative_to(ws_root):
                return True
        except ValueError:
            continue

    for uploads_dir in iter_session_upload_dirs(session_workspace, profile_home=profile_home_path):
        try:
            if resolved.is_relative_to(uploads_dir):
                return True
        except ValueError:
            continue

    try:
        if resolved.is_relative_to(_attachment_root()):
            return True
    except ValueError:
        pass

    return False


def resolve_workspace_uploads_relative_path(
    rel: str,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: Path | None = None,
) -> Path | None:
    """Resolve ``.uploads/...`` paths or upload basenames to an on-disk file."""
    token = str(rel or "").strip()
    if not token:
        return None

    uploads_rel = token.lstrip("/")
    if uploads_rel.startswith(f"{WORKSPACE_UPLOADS_SUBDIR}/"):
        try:
            from app.domain.workspace import resolve_main_user_workspace_root

            main_root = resolve_main_user_workspace_root(
                session_workspace or None,
                profile_home=profile_home,
            )
            candidate = (main_root / uploads_rel).resolve()
            if candidate.is_file():
                return candidate
        except (ValueError, OSError):
            pass

    basename = Path(token).name
    if not basename:
        return None

    if session_id:
        inbox_hit = resolve_upload_basename_in_dir(
            _session_attachment_dir(session_id),
            basename,
        )
        if inbox_hit is not None:
            return inbox_hit

    for uploads_dir in iter_session_upload_dirs(session_workspace, profile_home=profile_home):
        uploads_hit = resolve_upload_basename_in_dir(uploads_dir, basename)
        if uploads_hit is not None:
            return uploads_hit

    return None


def _chat_attachment_profile_home(
    session_profile_home: str | Path | None = None,
) -> Path | None:
    """Prefer the signed-in account's profile home for upload resolution."""
    from app.domain.workspace import _profile_home_for_workspace_access

    request_home = _profile_home_for_workspace_access()
    if request_home is not None:
        return request_home
    if session_profile_home:
        try:
            return Path(session_profile_home).expanduser().resolve()
        except OSError:
            pass
    return None


def _session_upload_disk_path_with_fallback(
    token: str,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: Path | None = None,
) -> str:
    """Resolve an upload token, retrying without an explicit profile home."""
    session_hit = _session_upload_disk_path(
        token,
        session_workspace=session_workspace,
        session_id=session_id,
        profile_home=profile_home,
    )
    if session_hit or profile_home is None:
        return session_hit
    return _session_upload_disk_path(
        token,
        session_workspace=session_workspace,
        session_id=session_id,
        profile_home=None,
    )


def resolve_chat_attachment_disk_path(
    attachment: dict,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: str | Path | None = None,
) -> str:
    """Return an absolute on-disk path for a chat attachment payload when possible."""
    if not isinstance(attachment, dict):
        return ""
    raw_path = str(attachment.get("path") or "").strip()
    workspace_rel = str(attachment.get("workspace_rel") or "").strip()
    profile_home_path = _chat_attachment_profile_home(profile_home)

    if workspace_rel:
        session_hit = _session_upload_disk_path_with_fallback(
            workspace_rel,
            session_workspace=session_workspace,
            session_id=session_id,
            profile_home=profile_home_path,
        )
        if session_hit:
            return session_hit

    if raw_path:
        try:
            candidate = Path(raw_path).expanduser().resolve()
            if candidate.is_file():
                if path_allowed_for_native_multimodal_image(
                    candidate,
                    session_workspace,
                    profile_home=profile_home_path,
                ):
                    return str(candidate)
                uploads_rel = workspace_rel or attachment_workspace_rel_path(attachment)
                if uploads_rel:
                    session_hit = _session_upload_disk_path_with_fallback(
                        uploads_rel,
                        session_workspace=session_workspace,
                        session_id=session_id,
                        profile_home=profile_home_path,
                    )
                    if session_hit:
                        return session_hit
        except OSError:
            pass

    token = workspace_rel or raw_path
    if not token:
        return ""
    resolved = resolve_agent_attachment_path(
        token,
        session_workspace=session_workspace,
        session_id=session_id,
        profile_home=profile_home_path,
    )
    try:
        path = Path(resolved).expanduser().resolve()
    except OSError:
        return ""
    if not path.is_file():
        return ""
    if path_allowed_for_native_multimodal_image(
        path,
        session_workspace,
        profile_home=profile_home_path,
    ):
        return str(path)
    return ""


def normalize_chat_attachment_records(
    attachments,
    *,
    session_workspace: str | None = None,
    session_id: str | None = None,
    profile_home: str | Path | None = None,
) -> list:
    """Fill absolute ``path`` values for workspace-relative upload metadata."""
    normalized: list = []
    for item in attachments or []:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        next_item = dict(item)
        workspace_rel = str(next_item.get("workspace_rel") or "").strip()
        if workspace_rel:
            next_item["workspace_rel"] = workspace_rel
        disk_path = resolve_chat_attachment_disk_path(
            next_item,
            session_workspace=session_workspace,
            session_id=session_id,
            profile_home=profile_home,
        )
        if disk_path:
            next_item["path"] = disk_path
        elif workspace_rel:
            next_item["path"] = workspace_rel
        normalized.append(next_item)
    return normalized


def resolve_upload_basename_in_dir(directory: Path, basename: str) -> Path | None:
    """Find an uploaded file by display name inside a single directory."""
    name = str(basename or "").strip()
    if not name:
        return None
    try:
        root = directory.resolve()
    except OSError:
        return None
    if not root.is_dir():
        return None
    try:
        exact = safe_resolve_ws(root, name)
        if exact.exists() and exact.is_file():
            return exact
    except ValueError:
        pass
    try:
        for candidate in root.iterdir():
            if candidate.is_file() and candidate.name.lower() == name.lower():
                return candidate
        stem = Path(name).stem.lower()
        suffix = Path(name).suffix.lower()
        if stem and suffix:
            for candidate in root.iterdir():
                if (
                    candidate.is_file()
                    and candidate.suffix.lower() == suffix
                    and candidate.stem.lower().startswith(stem)
                ):
                    return candidate
    except OSError:
        return None
    return None


def _session_attachment_dir(session_id: str, *, root: Path | None = None) -> Path:
    root = (root or _attachment_root()).resolve()
    dest_dir = (root / _re.sub(r'[^\w.\-]', '_', str(session_id or 'session'))[:120]).resolve()
    if not dest_dir.is_relative_to(root):
        raise ValueError('Invalid attachment directory')
    return dest_dir


def process_upload(fields: dict, files: dict) -> tuple[dict, int]:
    """Core single-file upload logic; returns (payload, http_status)."""
    session_id = fields.get('session_id', '')
    if 'file' not in files:
        return {'error': 'No file field in request'}, 400
    filename, file_bytes = files['file']
    if not filename:
        return {'error': 'No filename in upload'}, 400
    try:
        get_session(session_id)
    except KeyError:
        return {'error': 'Session not found'}, 404
    safe_name = _sanitize_upload_name(filename)
    workspace_field = str(fields.get('workspace') or '').strip()
    workspace_root = _resolve_chat_upload_workspace(session_id, workspace_field)
    if workspace_root is not None:
        dest, rel = _workspace_upload_destination(workspace_root, safe_name)
        dest.write_bytes(file_bytes)
        return _upload_payload_for_path(dest, workspace_rel=rel), 200

    from app.domain.workspace import nested_workspaces_enabled

    if nested_workspaces_enabled():
        return {
            'error': (
                "Could not resolve this account's workspace for upload. "
                "Check workspace access or contact an administrator."
            ),
        }, 400

    dest = _upload_destination(session_id, safe_name)
    dest.write_bytes(file_bytes)
    return _upload_payload_for_path(dest), 200


def process_upload_extract(fields: dict, files: dict) -> tuple[dict, int]:
    """Core archive extraction upload logic; returns (payload, http_status)."""
    session_id = fields.get('session_id', '')
    if 'file' not in files:
        return {'error': 'No file field in request'}, 400
    filename, file_bytes = files['file']
    if not filename:
        return {'error': 'No filename in upload'}, 400
    try:
        get_session(session_id)
    except KeyError:
        return {'error': 'Session not found'}, 404
    session_dir = _session_attachment_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    result = extract_archive(file_bytes, filename, session_dir)
    return {'ok': True, **result}, 200


def process_multipart_upload(
    rfile,
    content_type: str,
    content_length: int,
    *,
    extract: bool = False,
) -> tuple[dict, int]:
    """Parse multipart body and run upload or extract logic."""
    if content_length > MAX_UPLOAD_BYTES:
        return (
            {'error': f'File too large (max {MAX_UPLOAD_BYTES//1024//1024}MB)'},
            413,
        )
    fields, files = parse_multipart(rfile, content_type, content_length)
    if extract:
        return process_upload_extract(fields, files)
    return process_upload(fields, files)


def handle_upload(handler):
    import traceback as _tb
    try:
        content_type = handler.headers.get('Content-Type', '')
        content_length = int(handler.headers.get('Content-Length', 0) or 0)
        payload, status = process_multipart_upload(
            handler.rfile,
            content_type,
            content_length,
        )
        return j(handler, payload, status=status)
    except ValueError as e:
        return j(handler, {'error': str(e)}, status=400)
    except Exception:
        print('[webui] upload error: ' + _tb.format_exc(), flush=True)
        return j(handler, {'error': 'Upload failed'}, status=500)


def extract_archive(file_bytes: bytes, filename: str, workspace: Path):
    """Extract a zip or tar archive into the workspace.

    Returns a dict with ``extracted`` (int), ``files`` (list[str]).
    Raises ValueError on zip-slip or unsupported format.
    """
    import zipfile, tarfile, io, os, shutil

    name = Path(filename).name
    stem = Path(filename).stem  # strip .zip / .tar.gz etc.

    if name.lower().endswith(('.zip',)):
        _mode = 'zip'
    elif name.lower().endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')):
        _mode = 'tar'
    else:
        raise ValueError(f'Unsupported archive format: {filename}')

    # Determine destination directory — use archive stem as folder name
    dest_dir = safe_resolve_ws(workspace, stem)
    # Avoid overwriting existing files by appending a suffix
    if dest_dir.exists():
        import string, random
        while dest_dir.exists():
            suffix = ''.join(random.choices(string.digits, k=3))
            dest_dir = dest_dir.with_name(stem + '_' + suffix)
    dest_dir.mkdir(parents=True, exist_ok=True)

    extracted_files = []
    total_extracted = 0

    try:
        if _mode == 'zip':
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                for member in zf.infolist():
                    # Skip directories
                    if member.is_dir():
                        continue
                    # Zip-slip protection
                    member_path = (dest_dir / member.filename).resolve()
                    if not member_path.is_relative_to(dest_dir.resolve()):
                        raise ValueError(f'Zip-slip blocked: {member.filename}')
                    # Zip-bomb protection: track actual extracted bytes (not declared file_size)
                    if total_extracted > _MAX_EXTRACTED_BYTES:
                        raise ValueError(
                            f'Extraction too large ({total_extracted // (1024*1024)} MB > '
                            f'{_MAX_EXTRACTED_BYTES // (1024*1024)} MB limit). '
                            f'Possible zip bomb.'
                        )
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(member_path, 'wb') as dst:
                        _chunk_size = 65536
                        while True:
                            chunk = src.read(_chunk_size)
                            if not chunk:
                                break
                            total_extracted += len(chunk)
                            if total_extracted > _MAX_EXTRACTED_BYTES:
                                raise ValueError(
                                    f'Extraction too large (> '
                                    f'{_MAX_EXTRACTED_BYTES // (1024*1024)} MB limit). '
                                    f'Possible zip bomb.'
                                )
                            dst.write(chunk)
                    extracted_files.append(str(member_path.relative_to(workspace.resolve())))

        elif _mode == 'tar':
            with tarfile.open(fileobj=io.BytesIO(file_bytes)) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    # Tar-slip protection
                    member_path = (dest_dir / member.name).resolve()
                    if not member_path.is_relative_to(dest_dir.resolve()):
                        raise ValueError(f'Tar-slip blocked: {member.name}')
                    # Tar-bomb protection: track actual extracted bytes (not declared size)
                    if total_extracted > _MAX_EXTRACTED_BYTES:
                        raise ValueError(
                            f'Extraction too large ({total_extracted // (1024*1024)} MB > '
                            f'{_MAX_EXTRACTED_BYTES // (1024*1024)} MB limit). '
                            f'Possible zip bomb.'
                        )
                    member_path.parent.mkdir(parents=True, exist_ok=True)
                    src_obj = tf.extractfile(member)
                    if src_obj:
                        with src_obj as src, open(member_path, 'wb') as dst:
                            _chunk_size = 65536
                            while True:
                                chunk = src.read(_chunk_size)
                                if not chunk:
                                    break
                                total_extracted += len(chunk)
                                if total_extracted > _MAX_EXTRACTED_BYTES:
                                    raise ValueError(
                                        f'Extraction too large (> '
                                        f'{_MAX_EXTRACTED_BYTES // (1024*1024)} MB limit). '
                                        f'Possible zip bomb.'
                                    )
                                dst.write(chunk)
                    extracted_files.append(str(member_path.relative_to(workspace.resolve())))
    except Exception:
        # Clean up partially-extracted directory to avoid orphaned folders
        try:
            shutil.rmtree(dest_dir, ignore_errors=True)
        except Exception:
            pass
        raise

    return {'extracted': len(extracted_files), 'files': extracted_files, 'dest': str(dest_dir)}


def handle_upload_extract(handler):
    """Handle archive upload and extraction."""
    import traceback as _tb
    try:
        content_type = handler.headers.get('Content-Type', '')
        content_length = int(handler.headers.get('Content-Length', 0) or 0)
        payload, status = process_multipart_upload(
            handler.rfile,
            content_type,
            content_length,
            extract=True,
        )
        return j(handler, payload, status=status)
    except ValueError as e:
        return j(handler, {'error': str(e)}, status=400)
    except Exception:
        print('[webui] upload extract error: ' + _tb.format_exc(), flush=True)
        return j(handler, {'error': 'Archive extraction failed'}, status=500)


def handle_transcribe(handler):
    import traceback as _tb
    temp_path = None
    try:
        content_type = handler.headers.get('Content-Type', '')
        content_length = int(handler.headers.get('Content-Length', 0) or 0)
        if content_length > MAX_UPLOAD_BYTES:
            return j(handler, {'error': f'File too large (max {MAX_UPLOAD_BYTES//1024//1024}MB)'}, status=413)
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if 'file' not in files:
            return j(handler, {'error': 'No file field in request'}, status=400)
        filename, file_bytes = files['file']
        if not filename:
            return j(handler, {'error': 'No filename in upload'}, status=400)
        safe_name = _sanitize_upload_name(filename)
        suffix = Path(safe_name).suffix or '.webm'
        with tempfile.NamedTemporaryFile(prefix='webui-stt-', suffix=suffix, delete=False) as tmp:
            temp_path = tmp.name
            tmp.write(file_bytes)
        try:
            from tools.transcription_tools import transcribe_audio
        except ImportError:
            return j(handler, {'error': 'Speech-to-text is unavailable on this server'}, status=503)
        result = transcribe_audio(temp_path)
        if not result.get('success'):
            msg = str(result.get('error') or 'Transcription failed')
            status = 503 if 'unavailable' in msg.lower() or 'not configured' in msg.lower() else 400
            return j(handler, {'error': msg}, status=status)
        transcript = str(result.get('transcript') or '').strip()
        return j(handler, {'ok': True, 'transcript': transcript})
    except ValueError as e:
        return j(handler, {'error': str(e)}, status=400)
    except Exception:
        print('[webui] transcribe error: ' + _tb.format_exc(), flush=True)
        return j(handler, {'error': 'Transcription failed'}, status=500)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
