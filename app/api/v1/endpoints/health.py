"""Native FastAPI health endpoint (parity with legacy /health)."""

from __future__ import annotations

import time
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.domain.config import SESSIONS
from app.domain.routes import (
    SERVER_START_TIME,
    _deep_health_checks,
    _run_lifecycle_health,
    _streams_lock_health,
)

router = APIRouter(tags=["health"])


def _accept_loop_from_request(request: Request) -> dict:
    state = request.app.state
    return {
        "requests_total": int(getattr(state, "accept_loop_requests_total", 0) or 0),
        "last_request_at": round(
            float(getattr(state, "accept_loop_last_request_at", 0.0) or 0.0),
            3,
        ),
    }


@router.get("/health", response_model=None)
def health(request: Request):
    """Process health probe with optional deep checks via ?deep=1."""
    parsed_qs = parse_qs(request.url.query or "")
    deep = (parsed_qs.get("deep") or [""])[0].lower() in {"1", "true", "yes", "on"}
    stream_check = _streams_lock_health()
    run_check = _run_lifecycle_health()
    payload: dict = {
        "status": "ok" if stream_check.get("status") == "ok" else "degraded",
        "sessions": len(SESSIONS),
        "active_streams": int(stream_check.get("active_streams") or 0),
        "active_runs": int(run_check.get("active_runs") or 0),
        "runs": run_check.get("runs", []),
        "last_run_finished_at": run_check.get("last_run_finished_at"),
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
        "accept_loop": _accept_loop_from_request(request),
    }
    if "oldest_run_age_seconds" in run_check:
        payload["oldest_run_age_seconds"] = run_check["oldest_run_age_seconds"]
    if "idle_seconds_since_last_run" in run_check:
        payload["idle_seconds_since_last_run"] = run_check["idle_seconds_since_last_run"]
    if deep:
        if stream_check.get("status") != "ok":
            payload["checks"] = {"streams_lock": stream_check}
            return JSONResponse(payload, status_code=503)
        checks, healthy = _deep_health_checks(stream_check=stream_check)
        payload["checks"] = checks
        if not healthy:
            payload["status"] = "degraded"
            return JSONResponse(payload, status_code=503)
    if payload["status"] != "ok":
        return JSONResponse(payload, status_code=503)
    return payload
