"""Native FastAPI settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from app.domain.auth import COOKIE_NAME, set_auth_cookie
from app.services.settings import SettingsService

router = APIRouter(tags=["settings"])
_service = SettingsService()


class SettingsSaveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return _service.get_public_settings(request=request)


@router.post("/settings")
def save_settings(
    body: SettingsSaveRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    cookie = request.cookies.get(COOKIE_NAME)
    payload, new_cookie, error_status = _service.save_settings(
        body.model_dump(exclude_unset=True),
        current_cookie=cookie,
    )
    if error_status is not None:
        raise HTTPException(status_code=error_status, detail=payload.get("detail", "Conflict"))
    if new_cookie:

        class _CookieHandler:
            def __init__(self, req: Request) -> None:
                self.request = req
                self.headers = req.headers

            def send_header(self, key: str, value: str) -> None:
                if key.lower() == "set-cookie":
                    response.headers.append("set-cookie", value)

        set_auth_cookie(_CookieHandler(request), new_cookie)
    return payload
