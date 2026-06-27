#!/usr/bin/env python3
"""Run parallel chat/start probes as separate WebUI users."""

from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from concurrent_chat_probe import Client, load_env


def admin_request(
    client: Client,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    return client.request(method, path, payload)


def delete_user_if_exists(admin: Client, email: str) -> None:
    encoded = urllib.parse.quote(email, safe="")
    req = urllib.request.Request(
        f"{admin.base}/api/v1/admin/users/{encoded}",
        method="DELETE",
    )
    with admin._lock:
        try:
            admin.opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise


def create_probe_user(admin: Client, email: str, password: str) -> None:
    admin_request(
        admin,
        "POST",
        "/api/v1/admin/users",
        {
            "email": email,
            "password": password,
            "role": "user",
            "display_name": email.split("@", 1)[0],
        },
    )


def run_user_probe(
    *,
    base: str,
    label: str,
    email: str,
    password: str,
    model: str,
    model_provider: str,
    message: str,
) -> dict[str, Any]:
    started = time.time()
    client = Client(base)
    client.login(email, password)
    session_id = client.new_session()
    stream_id = client.chat_start(
        session_id=session_id,
        message=message,
        model=model,
        model_provider=model_provider,
    )
    chat_start_s = round(time.time() - started, 2)

    # Verify persisted reply (more reliable than SSE done in this harness).
    with client._lock:
        req = urllib.request.Request(
            f"{client.base}/api/v1/session?session_id={urllib.parse.quote(session_id)}",
            method="GET",
        )
        deadline = time.time() + 180
        assistant = ""
        owner = ""
        while time.time() < deadline:
            with client.opener.open(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            session = data.get("session") or {}
            owner = str(session.get("owner_user_id") or email)
            msgs = session.get("messages") or []
            for msg in reversed(msgs):
                if msg.get("role") == "assistant" and str(msg.get("content") or "").strip():
                    assistant = str(msg.get("content") or "").strip()
                    break
            if assistant:
                break
            time.sleep(0.5)

    total_s = round(time.time() - started, 2)
    return {
        "label": label,
        "email": email,
        "session_id": session_id,
        "stream_id": stream_id,
        "owner_user_id": owner,
        "chat_start_s": chat_start_s,
        "total_s": total_s,
        "reply": assistant,
        "ok": bool(assistant),
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    env = load_env(repo / ".env")
    base = f"http://127.0.0.1:{env.get('HERMES_WEBUI_PORT', '8787')}"
    admin_email = env.get("HERMES_WEBUI_ADMIN_USER", "")
    admin_password = env.get("HERMES_WEBUI_ADMIN_PASSWORD", "")
    if not admin_email or not admin_password:
        print("missing admin credentials in .env", file=sys.stderr)
        return 2

    model = "rp/unsloth/Qwen3.6-35B-A3B-MTP-GGUF:BF16"
    model_provider = "custom:a.i.tech"
    probe_password = secrets.token_urlsafe(18)
    probe_users = [
        ("user-a", "concurrent-probe-a@aitech.co.th"),
        ("user-b", "concurrent-probe-b@aitech.co.th"),
        ("user-c", "concurrent-probe-c@aitech.co.th"),
    ]

    admin = Client(base)
    admin.login(admin_email, admin_password)

    print("preparing 3 probe users…", flush=True)
    for _, email in probe_users:
        delete_user_if_exists(admin, email)
        create_probe_user(admin, email, probe_password)

    print(
        f"firing 3 parallel chats as different users | model={model}",
        flush=True,
    )
    started_all = time.time()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                run_user_probe,
                base=base,
                label=label,
                email=email,
                password=probe_password,
                model=model,
                model_provider=model_provider,
                message=(
                    f"{label} multi-user probe: reply with one short sentence "
                    f"containing the token {label}."
                ),
            ): label
            for label, email in probe_users
        }
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: r["label"])
    print(f"all workers finished in {round(time.time() - started_all, 2)}s\n", flush=True)

    print("=== results ===")
    for row in results:
        status = "OK" if row["ok"] else "FAIL"
        print(
            f"{row['label']} ({row['email']}): {status} "
            f"chat_start={row['chat_start_s']}s total={row['total_s']}s "
            f"owner={row['owner_user_id']}"
        )
        if row["reply"]:
            print(f"  reply: {row['reply'][:160]}")

    print("\ncleaning up probe users…", flush=True)
    for _, email in probe_users:
        delete_user_if_exists(admin, email)

    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} users completed successfully")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
