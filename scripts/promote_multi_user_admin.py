#!/usr/bin/env python3
"""Promote a legacy Hermes WebUI install to multi-user mode with an admin account.

Usage:
  HERMES_WEBUI_ADMIN_USER=admin \\
  HERMES_WEBUI_ADMIN_PASSWORD='change-me' \\
  python3 scripts/promote_multi_user_admin.py

When legacy password auth is enabled, pass the current WebUI password:
  python3 scripts/promote_multi_user_admin.py --current-password 'old-secret'

Never prints the new admin password.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_repo_dotenv() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    _load_repo_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-user",
        default=os.getenv("HERMES_WEBUI_ADMIN_USER", "admin"),
        help="First admin username (default: admin or HERMES_WEBUI_ADMIN_USER)",
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv("HERMES_WEBUI_ADMIN_PASSWORD", ""),
        help="Admin password (default: HERMES_WEBUI_ADMIN_PASSWORD env)",
    )
    parser.add_argument(
        "--current-password",
        default="",
        help="Existing WebUI password when legacy auth is enabled",
    )
    args = parser.parse_args()

    from app.domain.users import promote_install_to_multi_user

    result = promote_install_to_multi_user(
        admin_username=args.admin_user,
        admin_password=args.admin_password or None,
        current_password=args.current_password or None,
    )
    status = result.get("status")
    user = result.get("user") if isinstance(result.get("user"), dict) else {}
    username = user.get("username") or result.get("username") or args.admin_user
    if status == "created":
        print(f"[ok] Multi-user promoted; admin user {username!r} created.")
        return 0
    if status == "skipped":
        print(f"[skip] {result.get('reason') or result.get('message', 'skipped')}")
        return 0
    print(
        f"[error] {result.get('error') or result.get('message', 'unknown error')}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
