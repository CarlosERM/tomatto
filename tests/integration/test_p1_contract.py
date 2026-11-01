"""P1 — Contract tests.

Curated from the LLM output of prompts/p1-contract.md: request/response checks
derived directly from docs/openapi.yaml (status codes, payload shapes, ETag
semantics). One test per contract line so a failure names the broken promise.
"""

from __future__ import annotations

import pytest

from tests.conftest import etag_version

pytestmark = pytest.mark.integration


async def test_health_endpoints_report_ok(manager, sync):
    for client, service in ((manager, "manager"), (sync, "sync")):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": service}


async def test_create_rule_returns_201_with_contract_fields(manager):
    resp = await manager.post("/rules", json={"domain": "example.com"})
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "domain", "include_subdomains", "created_at", "sync_status"}
    assert body["domain"] == "example.com"
    assert body["sync_status"] in ("pending", "synced")


async def test_duplicate_domain_returns_409(manager):
    first = await manager.post("/rules", json={"domain": "dup.example.com"})
    second = await manager.post("/rules", json={"domain": "dup.example.com"})
    assert first.status_code == 201
    assert second.status_code == 409


async def test_invalid_domain_returns_422(manager):
    resp = await manager.post("/rules", json={"domain": "not a domain!!"})
    assert resp.status_code == 422


async def test_delete_unknown_rule_returns_404(manager):
    resp = await manager.delete("/rules/does-not-exist")
    assert resp.status_code == 404


async def test_blocked_response_shape_and_content_type(sync):
    resp = await sync.get("/blocked")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert set(body) == {"version", "sites"}
    assert isinstance(body["version"], int) and body["version"] >= 0
    assert isinstance(body["sites"], list)


async def test_blocked_advertises_weak_etag(sync):
    etag = (await sync.get("/blocked")).headers.get("etag")
    assert etag is not None
    assert etag.startswith('W/"') and etag.endswith('"')


async def test_if_none_match_returns_304_with_empty_body(manager, sync):
    first = await sync.get("/blocked")
    etag = first.headers["etag"]

    second = await sync.get("/blocked", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""


async def test_version_increases_monotonically_after_mutations(manager, sync):
    v0 = etag_version((await sync.get("/blocked")).headers.get("etag"))

    created = await manager.post("/rules", json={"domain": "mono.example.com"})
    v1 = etag_version((await sync.get("/blocked")).headers.get("etag"))
    assert v1 > v0

    await manager.delete(f"/rules/{created.json()['id']}")
    v2 = etag_version((await sync.get("/blocked")).headers.get("etag"))
    assert v2 > v1


async def test_internal_sync_rejects_stale_snapshot(sync):
    ok = await sync.post("/internal/sync", json={"version": 5, "sites": []})
    assert ok.status_code == 200

    stale = await sync.post("/internal/sync", json={"version": 4, "sites": []})
    assert stale.status_code == 409


async def test_internal_sync_rejects_negative_version(sync):
    resp = await sync.post("/internal/sync", json={"version": -1, "sites": []})
    assert resp.status_code == 422
