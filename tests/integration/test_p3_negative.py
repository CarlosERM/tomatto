"""P3 — Negative / adversarial tests.

Curated from the LLM output of prompts/p3-negative.md ("act as an adversarial
QA engineer"). The interesting failures here are cross-service, not just
HTTP-level: outages mid-write, retry recovery, eventual consistency after
several mutations while Sync is down, and malformed payloads at the internal
integration seam.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_sync_down_marks_rule_pending_and_retry_recovers(manager, sync, toggle_transport):
    # Given the Sync API is unreachable
    toggle_transport.enabled = False

    created = await manager.post("/rules", json={"domain": "down.example.com"})
    assert created.status_code == 201  # write still succeeds locally...
    assert created.json()["sync_status"] == "pending"  # ...but is flagged unsynced

    blocked = (await sync.get("/blocked")).json()
    assert blocked["sites"] == []  # consumer does NOT see the half-integrated rule

    # When Sync comes back and a retry is requested
    toggle_transport.enabled = True
    retry = await manager.post("/sync/retry")
    assert retry.json()["pushed"] is True

    rules = (await manager.get("/rules")).json()
    assert all(r["sync_status"] == "synced" for r in rules)
    blocked = (await sync.get("/blocked")).json()
    assert [s["domain"] for s in blocked["sites"]] == ["down.example.com"]


async def test_eventual_consistency_after_mutations_during_outage(manager, sync, toggle_transport):
    # Given several writes while the Sync API is down, including a delete
    toggle_transport.enabled = False
    ids = {}
    for d in ("keep.example.com", "drop.example.com", "other.example.com"):
        resp = await manager.post("/rules", json={"domain": d})
        assert resp.status_code == 201
        ids[d] = resp.json()["id"]
    assert (await manager.delete(f"/rules/{ids['drop.example.com']}")).status_code == 204

    # When connectivity is restored and the snapshot is re-pushed
    toggle_transport.enabled = True
    assert (await manager.post("/sync/retry")).json()["pushed"] is True

    # Then both services agree on exactly the surviving set (no ghost of the
    # deleted rule, no missing pending ones) and on the same version.
    blocked = (await sync.get("/blocked")).json()
    assert sorted(s["domain"] for s in blocked["sites"]) == ["keep.example.com", "other.example.com"]

    manager_version = (await manager.post("/sync/retry")).json()["version"]
    assert blocked["version"] == manager_version


async def test_delete_during_outage_still_removes_from_consumer_on_retry(manager, sync, toggle_transport):
    # Given a synced rule...
    created = await manager.post("/rules", json={"domain": "bye.example.com"})
    assert (await sync.get("/blocked")).json()["sites"] != []

    # ...deleted while Sync is down...
    toggle_transport.enabled = False
    await manager.delete(f"/rules/{created.json()['id']}")

    # ...the consumer keeps seeing it until the retry lands (documented staleness)
    stale = (await sync.get("/blocked")).json()
    assert [s["domain"] for s in stale["sites"]] == ["bye.example.com"]

    toggle_transport.enabled = True
    await manager.post("/sync/retry")
    assert (await sync.get("/blocked")).json()["sites"] == []


async def test_internal_sync_rejects_invalid_domain_in_payload(sync):
    resp = await sync.post(
        "/internal/sync", json={"version": 1, "sites": [{"domain": "bad_domain.com"}]}
    )
    assert resp.status_code == 422


async def test_create_rule_with_missing_body_returns_422(manager):
    resp = await manager.post("/rules", content="this is not json",
                              headers={"content-type": "application/json"})
    assert resp.status_code == 422


async def test_same_version_repush_is_idempotent(sync):
    payload = {"version": 7, "sites": [{"domain": "idem.example.com"}]}
    first = await sync.post("/internal/sync", json=payload)
    second = await sync.post("/internal/sync", json=payload)
    assert first.status_code == second.status_code == 200

    blocked = (await sync.get("/blocked")).json()
    assert [s["domain"] for s in blocked["sites"]] == ["idem.example.com"]
    assert blocked["version"] == 7


async def test_empty_snapshot_is_legal_and_clears_consumer_list(manager, sync):
    await manager.post("/rules", json={"domain": "temp.example.com"})
    assert (await sync.get("/blocked")).json()["sites"] != []

    # Deleting the last rule must propagate an explicit empty list, not a no-op.
    rules = (await manager.get("/rules")).json()
    for r in rules:
        await manager.delete(f"/rules/{r['id']}")
    assert (await sync.get("/blocked")).json()["sites"] == []
