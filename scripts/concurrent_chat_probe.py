#!/usr/bin/env python3
"""Fire N parallel Hermes WebUI chat/start + SSE streams for soak testing."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self._lock = threading.Lock()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 120,
        raw: bool = False,
    ) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        with self._lock:
            with self.opener.open(req, timeout=timeout) as resp:
                data = resp.read()
        if raw:
            return data
        if not data:
            return {}
        return json.loads(data.decode())

    def login(self, email: str, password: str) -> None:
        out = self.request("POST", "/api/v1/auth/login", {"email": email, "password": password})
        if not out.get("ok"):
            raise RuntimeError(f"login failed: {out}")

    def new_session(self) -> str:
        out = self.request("POST", "/api/v1/session/new", {})
        sid = out.get("session_id") or out.get("id")
        if not sid and isinstance(out.get("session"), dict):
            sid = out["session"].get("session_id") or out["session"].get("id")
        if not sid:
            raise RuntimeError(f"session/new unexpected payload: {out}")
        return str(sid)

    def chat_start(
        self,
        *,
        session_id: str,
        message: str,
        model: str,
        model_provider: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "model": model,
        }
        if model_provider:
            payload["model_provider"] = model_provider
        out = self.request("POST", "/api/v1/chat/start", payload, timeout=180)
        stream_id = out.get("stream_id")
        if not stream_id:
            raise RuntimeError(f"chat/start failed: {out}")
        return str(stream_id)

    def consume_stream(
        self,
        stream_id: str,
        *,
        timeout_s: float,
        label: str,
    ) -> dict[str, Any]:
        url = f"{self.base}/api/v1/chat/stream?stream_id={urllib.request.quote(stream_id)}"
        started = time.time()
        first_token_at: float | None = None
        done_at: float | None = None
        error: str | None = None
        token_chars = 0
        events = 0

        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "text/event-stream")
        try:
            with self.opener.open(req, timeout=timeout_s) as resp:
                buffer = ""
                while True:
                    if time.time() - started > timeout_s:
                        error = "stream timeout"
                        break
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buffer += chunk.decode(errors="replace")
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                    event_name: str | None = None
                    for line in block.splitlines():
                        if line.startswith("event:"):
                            event_name = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        events += 1
                        try:
                            evt = json.loads(raw)
                        except json.JSONDecodeError:
                            evt = {}
                        etype = event_name or evt.get("type") or evt.get("event")
                        if etype == "token":
                            text = evt.get("text") or evt.get("content") or ""
                            if text and first_token_at is None:
                                first_token_at = time.time()
                            token_chars += len(str(text))
                        elif etype in {"done", "error", "apperror", "cancel"}:
                            done_at = time.time()
                            if etype in {"error", "apperror"}:
                                error = str(evt.get("message") or evt.get("error") or evt)
                            return {
                                "label": label,
                                "stream_id": stream_id,
                                "started_at": started,
                                "first_token_s": None
                                if first_token_at is None
                                else round(first_token_at - started, 2),
                                "total_s": round((done_at or time.time()) - started, 2),
                                "token_chars": token_chars,
                                "events": events,
                                "error": error,
                                "ok": error is None and etype == "done",
                            }
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:300]
            error = f"HTTP {exc.code}: {body}"
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        return {
            "label": label,
            "stream_id": stream_id,
            "started_at": started,
            "first_token_s": None if first_token_at is None else round(first_token_at - started, 2),
            "total_s": round(time.time() - started, 2),
            "token_chars": token_chars,
            "events": events,
            "error": error or "stream ended without done",
            "ok": False,
        }


def run_probe(
    *,
    base: str,
    email: str,
    password: str,
    model: str,
    model_provider: str | None,
    count: int,
    timeout_s: float,
) -> list[dict[str, Any]]:
    client = Client(base)
    client.login(email, password)

    sessions = [client.new_session() for _ in range(count)]
    print(f"created {len(sessions)} sessions", flush=True)

    started_all = time.time()
    stream_jobs: list[tuple[str, str, str]] = []
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = {
            pool.submit(
                client.chat_start,
                session_id=sessions[i],
                message=f"Concurrency probe #{i + 1}: reply with exactly one short sentence containing the number {i + 1}.",
                model=model,
                model_provider=model_provider,
            ): i
            for i in range(count)
        }
        for fut in as_completed(futures):
            i = futures[fut]
            stream_id = fut.result()
            label = f"req-{i + 1}"
            stream_jobs.append((label, stream_id, sessions[i]))
            print(f"{label} chat/start -> stream_id={stream_id[:12]}… session={sessions[i][:12]}…", flush=True)

    print(f"all {count} chat/start returned in {round(time.time() - started_all, 2)}s — consuming SSE…", flush=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [
            pool.submit(client.consume_stream, stream_id, timeout_s=timeout_s, label=label)
            for label, stream_id, _ in stream_jobs
        ]
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r["label"])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--model", default="rp/unsloth/Qwen3.6-35B-A3B-MTP-GGUF:BF16")
    parser.add_argument("--model-provider", default="custom:a.i.tech")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--base", default="")
    args = parser.parse_args()

    env = load_env(Path(__file__).resolve().parents[1] / ".env")
    base = args.base or f"http://127.0.0.1:{env.get('HERMES_WEBUI_PORT', '8787')}"
    email = env.get("HERMES_WEBUI_ADMIN_USER", "")
    password = env.get("HERMES_WEBUI_ADMIN_PASSWORD", "")
    if not email or not password:
        print("missing HERMES_WEBUI_ADMIN_USER/PASSWORD in .env", file=sys.stderr)
        return 2

    print(f"base={base} model={args.model} provider={args.model_provider} count={args.count}", flush=True)
    results = run_probe(
        base=base,
        email=email,
        password=password,
        model=args.model,
        model_provider=args.model_provider or None,
        count=args.count,
        timeout_s=args.timeout,
    )

    ok = sum(1 for r in results if r["ok"])
    print("\n=== results ===")
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        print(
            f"{r['label']}: {status} first_token={r['first_token_s']}s total={r['total_s']}s "
            f"chars={r['token_chars']} events={r['events']}"
            + (f" error={r['error']}" if r.get("error") and not r["ok"] else "")
        )
    print(f"\n{ok}/{len(results)} streams completed successfully")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
