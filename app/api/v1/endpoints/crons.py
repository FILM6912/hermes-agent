"""Native FastAPI cron endpoints (CronsService)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.services.crons import CronsService

router = APIRouter(tags=["crons"])
_service = CronsService()


async def _parse_json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


@router.get("/crons")
def list_crons() -> dict[str, Any]:
    return _service.list_crons()


@router.get("/crons/output")
def cron_output(request: Request) -> Response:
    return _service.cron_output(
        dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/crons/history")
def cron_history(request: Request) -> Response:
    return _service.cron_history(
        dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/crons/run")
def cron_run_detail(request: Request) -> Response:
    return _service.cron_run_detail(
        dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/crons/recent")
def cron_recent(request: Request) -> Response:
    return _service.cron_recent(
        dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/crons/status")
def cron_status(request: Request) -> Response:
    return _service.cron_status(
        dict(request.query_params),
        headers=dict(request.headers),
    )


@router.get("/crons/delivery-options")
def cron_delivery_options(request: Request) -> Response:
    return _service.cron_delivery_options(headers=dict(request.headers))


@router.post("/crons/create")
async def cron_create(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_create(body, headers=dict(request.headers))


@router.post("/crons/update")
async def cron_update(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_update(body, headers=dict(request.headers))


@router.post("/crons/delete")
async def cron_delete(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_delete(body, headers=dict(request.headers))


@router.post("/crons/run")
async def cron_run(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_run(body, headers=dict(request.headers))


@router.post("/crons/pause")
async def cron_pause(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_pause(body, headers=dict(request.headers))


@router.post("/crons/resume")
async def cron_resume(request: Request) -> Response:
    body = await _parse_json_body(request)
    return _service.cron_resume(body, headers=dict(request.headers))
