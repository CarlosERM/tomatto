"""Tomatto Manager API (port 3001).

Owns the authoritative block list. On every mutation it persists to SQLite,
bumps a monotonic version and pushes a full-list snapshot to the Sync API
(write-through integration). If the push fails the rules stay ``pending`` and
can be re-pushed via POST /sync/retry — eventual consistency between the two
services is what tests/integration/ exercises.

Run: uvicorn services.manager_api.main:manager_app --port 3001
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from services.shared.store import DuplicateDomainError, ManagerStore
from services.shared.validation import normalize_domain


class RuleCreate(BaseModel):
    domain: str = Field(
        ...,
        description="Domain or URL to block (schemes, paths, ports and credentials are stripped).",
        examples=["https://news.example.com/story"],
    )
    include_subdomains: bool = True

    @field_validator("domain")
    @classmethod
    def _normalize(cls, v: str) -> str:
        try:
            return normalize_domain(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class RuleOut(BaseModel):
    id: str
    domain: str
    include_subdomains: bool
    created_at: str
    sync_status: str = Field(description="'synced' once the Sync API acknowledged the snapshot.")


class SyncRetryResult(BaseModel):
    pushed: bool
    version: int


def create_app(
    db_path: str = "data/manager.db",
    sync_base_url: str = "http://127.0.0.1:3002",
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Factory so tests can inject a temp DB and an in-process transport to Sync."""
    app = FastAPI(
        title="Tomatto Manager API",
        version="1.0.0",
        description="Manages the block list and pushes full snapshots to the Tomatto Sync API.",
    )
    store = ManagerStore(db_path)
    # Client kept on the module-level app is acceptable for this coursework
    # service; a production build would manage it via lifespan.
    client = httpx.AsyncClient(base_url=sync_base_url, transport=transport, timeout=3.0)

    async def push_snapshot() -> bool:
        try:
            resp = await client.post("/internal/sync", json=store.snapshot())
        except httpx.HTTPError:
            return False
        return resp.status_code < 400

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "manager"}

    @app.post("/rules", response_model=RuleOut, status_code=201)
    async def create_rule(payload: RuleCreate):
        try:
            rule = store.add_rule(payload.domain, payload.include_subdomains)
        except DuplicateDomainError:
            raise HTTPException(status_code=409, detail=f"domain already blocked: {payload.domain}")
        if await push_snapshot():
            store.mark_all_synced()
            rule["sync_status"] = "synced"
        return rule

    @app.get("/rules", response_model=list[RuleOut])
    async def list_rules():
        return store.list_rules()

    @app.delete("/rules/{rule_id}", status_code=204)
    async def delete_rule(rule_id: str):
        if not store.delete_rule(rule_id):
            raise HTTPException(status_code=404, detail=f"no rule with id {rule_id!r}")
        await push_snapshot()

    @app.post("/sync/retry", response_model=SyncRetryResult)
    async def sync_retry():
        pushed = await push_snapshot()
        if pushed:
            store.mark_all_synced()
        return SyncRetryResult(pushed=pushed, version=store.get_version())

    return app


manager_app = create_app(
    db_path=os.environ.get("TOMATTO_MANAGER_DB", "data/manager.db"),
    sync_base_url=os.environ.get("TOMATTO_SYNC_URL", "http://127.0.0.1:3002"),
)
