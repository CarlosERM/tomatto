"""P2 — Scenario tests.

Curated from the LLM output of prompts/p2-scenarios.md: end-to-end Given/When/
Then flows across Manager API -> Sync API, including how a browser extension
is expected to poll (ETag handshake) and persistence across a service restart.
"""

from __future__ import annotations

import contextlib

import httpx
import pytest

from services.manager_api.main import create_app as create_manager_app

pytestmark = pytest.mark.integration


@contextlib.asynccontextmanager
async def _client(app, base_url):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as c:
        yield c


async def test_full_lifecycle_rule_appears_and_disappears_in_blocked(manager, sync):
    # Given an empty block list
    assert (await sync.get("/blocked")).json()["sites"] == []

    # When a domain is added through the Manager API
    created = await manager.post("/rules", json={"domain": "social.example.net"})
    assert created.status_code == 201

    # Then the Sync API serves it to consumers immediately (write-through)
    blocked = (await sync.get("/blocked")).json()
    assert [s["domain"] for s in blocked["sites"]] == ["social.example.net"]

    # And when the rule is deleted, it disappears from the Sync side too
    gone = await manager.delete(f"/rules/{created.json()['id']}")
    assert gone.status_code == 204
    assert (await sync.get("/blocked")).json()["sites"] == []


async def test_extension_polling_loop_only_refetches_when_list_changed(manager, sync):
    # Given an extension that has fetched the list once and stored its ETag
    first = await sync.get("/blocked")
    etag = first.headers["etag"]

    # When nothing changed between polls -> cheap 304
    idle_poll = await sync.get("/blocked", headers={"If-None-Match": etag})
    assert idle_poll.status_code == 304

    # When a new rule is added upstream -> the next poll must return fresh data
    await manager.post("/rules", json={"domain": "games.example.io"})
    changed = await sync.get("/blocked", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert "games.example.io" in [s["domain"] for s in changed.json()["sites"]]

    # And the new ETag becomes the baseline for subsequent polls
    again = await sync.get("/blocked", headers={"If-None-Match": changed.headers["etag"]})
    assert again.status_code == 304


async def test_multiple_rules_propagate_as_one_consistent_snapshot(manager, sync):
    domains = ["a.example.com", "b.example.com", "c.example.com"]

    for d in domains:
        assert (await manager.post("/rules", json={"domain": d})).status_code == 201

    blocked = (await sync.get("/blocked")).json()
    assert sorted(s["domain"] for s in blocked["sites"]) == sorted(domains)
    # One snapshot per mutation, monotonic versions: the Sync copy can never be
    # a half-applied mixture.
    assert blocked["version"] >= len(domains)


async def test_manager_restart_replays_current_state(tmp_path, sync_app, toggle_transport):
    """Persistence integration: rules live in SQLite, not in process memory."""
    db = str(tmp_path / "manager.db")

    # Given a Manager whose pushes fail (Sync down)
    toggle_transport.enabled = False
    first_instance = create_manager_app(db, "http://sync", transport=toggle_transport)
    async with _client(first_instance, "http://manager") as manager:
        created = await manager.post("/rules", json={"domain": "persist.example.org"})
        assert created.status_code == 201
        assert created.json()["sync_status"] == "pending"

    # When the Manager restarts (new process, same SQLite file) and Sync is back
    toggle_transport.enabled = True
    second_instance = create_manager_app(db, "http://sync", transport=toggle_transport)
    async with _client(second_instance, "http://manager") as manager:
        rules = (await manager.get("/rules")).json()
        assert [r["domain"] for r in rules] == ["persist.example.org"]

        retry = await manager.post("/sync/retry")
        assert retry.json()["pushed"] is True

    # Then the Sync API ends up with exactly the persisted rule set
    async with _client(sync_app, "http://sync") as sync:
        blocked = (await sync.get("/blocked")).json()
        assert [s["domain"] for s in blocked["sites"]] == ["persist.example.org"]
