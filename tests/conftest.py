"""Shared fixtures for the Tomatto integration suite.

Both services run in-process via httpx.ASGITransport (fast, deterministic);
the Manager's write-through push to Sync goes through a ToggleTransport that
tests can disable to simulate "Sync API is down" — the real uvicorn-subprocess
path is covered separately in test_smoke_real_servers.py.
"""

from __future__ import annotations

import httpx
import pytest

from services.manager_api.main import create_app as create_manager_app
from services.sync_api.main import create_app as create_sync_app


class ToggleTransport(httpx.AsyncBaseTransport):
    """Wraps the Sync ASGI transport so tests can simulate outages."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.enabled = True

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.enabled:
            raise httpx.ConnectError("Simulated outage: Sync API unreachable", request=request)
        return await self.inner.handle_async_request(request)


@pytest.fixture()
def sync_app(tmp_path):
    return create_sync_app(str(tmp_path / "sync.db"))


@pytest.fixture()
def toggle_transport(sync_app) -> ToggleTransport:
    return ToggleTransport(httpx.ASGITransport(app=sync_app))


@pytest.fixture()
def manager_app(tmp_path, toggle_transport):
    return create_manager_app(
        db_path=str(tmp_path / "manager.db"),
        sync_base_url="http://sync",
        transport=toggle_transport,
    )


@pytest.fixture()
async def manager(manager_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=manager_app), base_url="http://manager"
    ) as client:
        yield client


@pytest.fixture()
async def sync(sync_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sync_app), base_url="http://sync"
    ) as client:
        yield client


def etag_version(etag: str | None) -> int:
    """Extract the integer version from a weak ETag like W/"3"."""
    assert etag is not None, "response must carry an ETag header"
    return int(etag.removeprefix("W/").strip('"'))
