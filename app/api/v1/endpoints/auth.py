"""Native FastAPI auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import CurrentUserDep

from app.domain.auth import (
    COOKIE_NAME,
    clear_auth_cookie,
    resolve_session_credential_from_request,
    set_auth_cookie,
)
from app.schemas.auth import (
    AccountProfileResponse,
    AccountUpdateRequest,
    AuthLoginRequest,
    AuthMeResponse,
    AuthStatusResponse,
    McpApiKeyResponse,
    PasskeyDeleteRequest,
    PasskeyRequest,
)
from app.services.auth import AuthService
from app.services.users import UserService

router = APIRouter(tags=["auth"])
_service = AuthService()
_users = UserService()


def _request_headers(request: Request) -> dict[str, str]:
    return {key: value for key, value in request.headers.items()}


def _set_auth_cookie_on_response(
    request: Request,
    response: Response,
    cookie_value: str,
) -> None:
    req = request

    class _CookieHandler:
        headers = req.headers
        request = req

        def send_header(self, key: str, value: str) -> None:
            if key.lower() == "set-cookie":
                response.headers.append("set-cookie", value)

    set_auth_cookie(_CookieHandler(), cookie_value)


def _clear_auth_cookie_on_response(response: Response) -> None:
    class _CookieHandler:
        def send_header(self, key: str, value: str) -> None:
            if key.lower() == "set-cookie":
                response.headers.append("set-cookie", value)

    clear_auth_cookie(_CookieHandler())


@router.get("/auth/status", response_model=AuthStatusResponse)
def auth_status(request: Request) -> AuthStatusResponse:
    session_cred = resolve_session_credential_from_request(request)
    return AuthStatusResponse(**_service.get_status(session_cred))


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(user: CurrentUserDep) -> AuthMeResponse:
    from app.domain.users import UserNotFoundError

    try:
        return AuthMeResponse(**_users.get_auth_me(user.user_id, role=user.role))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc


@router.patch("/auth/me", response_model=AuthMeResponse)
def auth_me_update(
    body: AccountUpdateRequest,
    user: CurrentUserDep,
) -> AuthMeResponse:
    from app.domain.users import UserError, UserNotFoundError

    patch = body.model_dump(exclude_unset=True)
    if not patch or "display_name" not in patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        _users.update_account_profile(
            user.user_id,
            display_name=patch["display_name"],
        )
        return AuthMeResponse(**_users.get_auth_me(user.user_id, role=user.role))
    except UserNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/me/mcp-key", response_model=McpApiKeyResponse)
def auth_me_mcp_key(user: CurrentUserDep) -> McpApiKeyResponse:
    from app.domain.mcp_keys import generate_user_mcp_api_key
    from app.domain.users import UserError, UserNotFoundError

    try:
        plain = generate_user_mcp_api_key(user.user_id, actor=user.user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return McpApiKeyResponse(mcp_api_key=plain)


@router.delete("/auth/me/mcp-key", status_code=204)
def auth_me_mcp_key_revoke(user: CurrentUserDep) -> None:
    from app.domain.mcp_keys import revoke_user_mcp_api_key
    from app.domain.users import UserNotFoundError

    try:
        revoke_user_mcp_api_key(user.user_id, actor=user.user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/auth/account", response_model=AccountProfileResponse)
def auth_account(user: CurrentUserDep) -> AccountProfileResponse:
    return AccountProfileResponse(**_users.get_account_profile(user.user_id))


@router.patch("/auth/account", response_model=AccountProfileResponse)
def auth_account_update(
    body: AccountUpdateRequest,
    user: CurrentUserDep,
) -> AccountProfileResponse:
    from app.domain.users import UserError

    patch = body.model_dump(exclude_unset=True)
    if not patch or "display_name" not in patch:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        return AccountProfileResponse(
            **_users.update_account_profile(
                user.user_id,
                display_name=patch["display_name"],
            )
        )
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login")
def auth_login(
    body: AuthLoginRequest,
    request: Request,
    response: Response,
) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    payload, status_code, cookie_val = _service.login(
        body.password,
        client_ip=client_ip,
        email=body.email,
    )
    json_response = JSONResponse(content=payload, status_code=status_code)
    if cookie_val:
        _set_auth_cookie_on_response(request, json_response, cookie_val)
    return json_response


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response) -> JSONResponse:
    session_cred = resolve_session_credential_from_request(request)
    payload = _service.logout(session_cred)
    _clear_auth_cookie_on_response(response)
    return JSONResponse(content=payload)


@router.post("/auth/passkey/options")
def auth_passkey_options(request: Request) -> JSONResponse:
    payload, status_code = _service.passkey_authentication_options(_request_headers(request))
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/auth/passkey/login")
def auth_passkey_login(
    body: PasskeyRequest,
    request: Request,
    response: Response,
) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    payload, status_code, cookie_val = _service.passkey_login(
        body.model_dump(exclude_unset=False),
        client_ip=client_ip,
        headers=_request_headers(request),
    )
    json_response = JSONResponse(content=payload, status_code=status_code)
    if cookie_val:
        _set_auth_cookie_on_response(request, json_response, cookie_val)
    return json_response


@router.post("/auth/passkey/register/options")
def auth_passkey_register_options(request: Request) -> JSONResponse:
    payload, status_code = _service.passkey_registration_options(_request_headers(request))
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/auth/passkey/register")
def auth_passkey_register(body: PasskeyRequest, request: Request) -> JSONResponse:
    payload, status_code = _service.passkey_register(
        body.model_dump(exclude_unset=False),
        _request_headers(request),
    )
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/auth/passkey/delete")
def auth_passkey_delete(body: PasskeyDeleteRequest) -> JSONResponse:
    payload, status_code = _service.passkey_delete(body.model_dump(exclude_unset=False))
    return JSONResponse(content=payload, status_code=status_code)


@router.post("/auth/passkeys")
def auth_passkeys() -> JSONResponse:
    return JSONResponse(content=_service.list_passkeys())
