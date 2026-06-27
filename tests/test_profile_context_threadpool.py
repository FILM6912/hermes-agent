"""Regression coverage for profile-context propagation into sync endpoints.

Bug: ``ProfileContextMiddleware`` is async and runs on the event-loop thread,
but sync FastAPI route handlers (``def``, not ``async def``) execute on a
*different* anyio threadpool worker thread (``run_in_threadpool`` /
``anyio.to_thread.run_sync``).  The per-request profile used to live in a
``threading.local``, which is empty on that worker thread, so profile-scoped
sync endpoints (workspace list, sessions, settings, ...) silently fell back to
the process-global ``default`` profile instead of the request's profile (e.g.
``user1``).

Fix: the per-request profile now lives in a ``contextvars.ContextVar`` which
anyio copies into the threadpool worker, so sync handlers observe the correct
per-request profile.  These tests pin that behaviour, including concurrency.
"""
from __future__ import annotations

import concurrent.futures as cf

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.domain.profiles as profiles
from app.middleware.security import ProfileContextMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ProfileContextMiddleware)

    @app.get("/sync-probe")
    def sync_probe() -> dict:  # sync def -> runs in anyio threadpool worker
        return {
            "profile": profiles.get_active_profile_name(),
            "home": str(profiles.get_active_hermes_home()),
        }

    @app.get("/async-probe")
    async def async_probe() -> dict:  # async def -> runs on event loop thread
        return {"profile": profiles.get_active_profile_name()}

    return app


def _profile_headers(profile: str | None) -> dict:
    """Build a request Cookie header carrying the active-profile selector.

    The Cookie header is set per request (not on the client instance) so each
    request in a sequence/concurrency test can carry a different profile.
    """
    return {"Cookie": f"hermes_profile={profile}"} if profile else {}


@pytest.fixture
def client():
    # Defensive: ensure no leaked request profile from a prior test in this
    # process context bleeds into these assertions.
    profiles.clear_request_profile()
    with TestClient(_build_app()) as c:
        yield c
    profiles.clear_request_profile()


def test_sync_endpoint_sees_request_profile_not_default(client):
    """A sync (def) handler must observe the cookie's profile, not 'default'."""
    resp = client.get("/sync-probe", headers=_profile_headers("user1"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] == "user1", (
        "sync endpoint fell back to the process-global profile instead of the "
        "request's profile — profile context did not propagate into the "
        f"threadpool worker (got {body['profile']!r})"
    )
    # Home must resolve under the selected profile's directory, not default.
    assert body["home"].replace("\\", "/").rstrip("/").endswith("profiles/user1"), (
        f"active hermes home not scoped to user1: {body['home']!r}"
    )


def test_async_endpoint_also_sees_request_profile(client):
    resp = client.get("/async-probe", headers=_profile_headers("user1"))
    assert resp.status_code == 200
    assert resp.json()["profile"] == "user1"


def test_no_cookie_falls_back_to_process_default(client):
    """Outside an explicit profile cookie the helper must fall back to default."""
    resp = client.get("/sync-probe")
    assert resp.status_code == 200
    assert resp.json()["profile"] == profiles._active_profile == "default"


def test_sequential_requests_do_not_leak(client):
    """A profiled request must not leak its profile into a later bare request."""
    assert client.get(
        "/sync-probe", headers=_profile_headers("user1")
    ).json()["profile"] == "user1"
    assert client.get("/sync-probe").json()["profile"] == "default"
    assert client.get(
        "/sync-probe", headers=_profile_headers("userb")
    ).json()["profile"] == "userb"
    assert client.get("/sync-probe").json()["profile"] == "default"


def test_concurrent_requests_do_not_bleed(client):
    """Concurrent requests with different profiles must stay isolated.

    This is the multi-thread safety guarantee: two requests with different
    profiles hitting sync endpoints at the same time must each see their own
    profile, never each other's.
    """
    sent = (["user1", "userb", "userc", None] * 15)

    def call(profile):
        got = client.get(
            "/sync-probe", headers=_profile_headers(profile)
        ).json()["profile"]
        return (profile or "default"), got

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(call, sent))

    bleed = [(want, got) for want, got in results if want != got]
    assert not bleed, f"profile context bled across concurrent requests: {bleed[:10]}"


def test_threading_local_would_not_propagate_documents_root_cause():
    """Pin the root cause: a threading.local set on the calling thread is NOT
    visible inside a threadpool worker, whereas the contextvar IS.

    This is exactly the asymmetry that made the old threading.local-based
    implementation fail for sync route handlers.
    """
    import threading

    import anyio
    from anyio.from_thread import start_blocking_portal

    tls = threading.local()

    def read_in_worker():
        return {
            "tls": getattr(tls, "value", None),
            "ctx": profiles.get_active_profile_name(),
        }

    async def scenario():
        tls.value = "user1"  # set on the event-loop thread
        profiles.set_request_profile("user1")
        try:
            return await anyio.to_thread.run_sync(read_in_worker)
        finally:
            profiles.clear_request_profile()

    with start_blocking_portal() as portal:
        result = portal.call(scenario)

    assert result["tls"] is None, "threading.local unexpectedly propagated"
    assert result["ctx"] == "user1", "contextvar failed to propagate to worker"
