"""Tomatto Sync API (port 3002).

Read-mostly service the browser extension polls. It stores only the latest
full snapshot pushed by the Manager API and serves it with a weak ETag so
polling is cheap: ``If-None-Match`` matching the current version returns
``304 Not Modified`` with an empty body. Stale snapshots (older version) are
rejected with 409 — retries of the same version are idempotent.

Run: uvicorn services.sync_api.main:sync_app --port 3002
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from services.shared.store import SyncStore
from services.shared.validation import normalize_domain


class Site(BaseModel):
    domain: str
    include_subdomains: bool = True

    @field_validator("domain")
    @classmethod
    def _normalize(cls, v: str) -> str:
        try:
            return normalize_domain(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class SyncPayload(BaseModel):
    version: int = Field(..., ge=0, description="Monotonic snapshot version assigned by the Manager API.")
    sites: list[Site]


class SyncAck(BaseModel):
    stored_version: int


def _etag(version: int) -> str:
    return f'W/"{version}"'


def _weak_match(header_value: str, etag: str) -> bool:
    """RFC 7232 weak comparison: strip W/ prefixes, accept comma lists and '*'."""
    if header_value.strip() == "*":
        return True
    wanted = etag.removeprefix("W/")
    return any(candidate.strip().removeprefix("W/") == wanted for candidate in header_value.split(","))


def create_app(db_path: str = "data/sync.db") -> FastAPI:
    app = FastAPI(
        title="Tomatto Sync API",
        version="1.0.0",
        description="Serves the blocked-site snapshot to browser extensions with ETag/304 polling.",
    )
    store = SyncStore(db_path)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "sync"}

    @app.get("/blocked")
    async def blocked(request: Request):
        version, sites = store.get()
        etag = _etag(version)
        inm = request.headers.get("if-none-match")
        if inm and _weak_match(inm, etag):
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse({"version": version, "sites": sites}, headers={"ETag": etag})

    @app.post("/internal/sync", response_model=SyncAck)
    async def push(payload: SyncPayload):
        sites = [s.model_dump() for s in payload.sites]
        if not store.put_snapshot(payload.version, sites):
            current, _ = store.get()
            raise HTTPException(
                status_code=409,
                detail=f"stale snapshot: stored version {current} is newer than {payload.version}",
            )
        return SyncAck(stored_version=payload.version)

    @app.get("/internal/state")
    async def state():
        """Debug helper: what the Sync service currently holds."""
        version, sites = store.get()
        return {"version": version, "count": len(sites)}

    return app


sync_app = create_app(db_path=os.environ.get("TOMATTO_SYNC_DB", "data/sync.db"))
