Model: LM Studio local (Qwen3.8 Flash Next)
Date: 2026-11-02
Prompt version: v1 (prompts/p1-contract.md)
---

```python
"""Contract tests for Tomatto Manager API + Tomatto Sync API.

Source of truth: docs/openapi.yaml (OpenAPI 3.1). Every documented success
response is validated against its declared schema; every documented error is
checked for status code and body shape; undocumented status codes are treated
as contract violations.

Run against a live pair of services:

    MANAGER_BASE_URL=http://127.0.0.1:8000 SYNC_BASE_URL=http://127.0.0.1:8001 \
        pytest test_tomatto_contract.py

Spec location override: TOMATTO_OPENAPI_SPEC (defaults to ../docs/openapi.yaml).
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest
import requests
import yaml
from jsonschema import Draft202012Validator

MANAGER_BASE_URL = os.environ.get("MANAGER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SYNC_BASE_URL = os.environ.get("SYNC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
SPEC_PATH = Path(
    os.environ.get(
        "TOMATTO_OPENAPI_SPEC",
        str(Path(__file__).resolve().parent.parent / "docs" / "openapi.yaml"),
    )
)
TIMEOUT = 5


# --------------------------------------------------------------------------
# Spec loading and schema helpers
# --------------------------------------------------------------------------

def _lookup(root: dict, ref: str):
    node = root
    for part in ref.lstrip("#").lstrip("/").split("/"):
        node = node[part]
    return node


def _resolve(node, root):
    """Inline all local $refs so jsonschema can validate OpenAPI 3.1 schemas."""
    if isinstance(node, dict):
        if set(node) == {"$ref"}:
            return _resolve(_lookup(root, node["$ref"]), root)
        return {k: _resolve(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root) for v in node]
    return node


SPEC = yaml.safe_load(SPEC_PATH.read_text())


def request_schema(path: str, method: str):
    body = SPEC["paths"][path][method].get("requestBody", {})
    schema = (body.get("content") or {}).get("application/json", {}).get("schema")
    return _resolve(schema, SPEC) if schema else None


def response_schema(path: str, method: str, code: int):
    resp = SPEC["paths"][path][method]["responses"].get(str(code))
    assert resp is not None, f"{method.upper()} {path} declares no {code} response"
    schema = (resp.get("content") or {}).get("application/json", {}).get("schema")
    return _resolve(schema, SPEC) if schema is not None else None


def validate(instance, schema):
    Draft202012Validator(schema).validate(instance)


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

class Client:
    def __init__(self, base_url: str):
        self.base = base_url
        self.http = requests.Session()

    def req(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self.http.request(method, self.base + path, timeout=TIMEOUT, **kwargs)
        except requests.ConnectionError as exc:
            pytest.fail(f"{self.base}{path}: service unreachable — {exc}")


def assert_response(r: requests.Response, path: str, method: str, code: int):
    """Assert documented status code, JSON content type, and schema conformance."""
    assert r.status_code == code, (
        f"{method.upper()} {path} -> {r.status_code}, expected {code}. Body: {r.text[:300]}"
    )
    assert "application/json" in r.headers.get("content-type", ""), (
        f"{method.upper()} {path} {code}: content-type is "
        f"{r.headers.get('content-type')!r}, expected application/json"
    )
    body = r.json()
    schema = response_schema(path, method, code)
    if schema:  # `{}` (empty schema) accepts any JSON document
        validate(body, schema)
    return body


def assert_422(r: requests.Response, path: str, method: str, *loc_parts: str):
    """Assert the documented HTTPValidationError shape and error locations."""
    assert r.status_code == 422, (
        f"{method.upper()} {path} -> {r.status_code}, expected 422. Body: {r.text[:300]}"
    )
    body = assert_response(r, path, method, 422)
    detail = body.get("detail")
    assert isinstance(detail, list) and detail, "422 must carry a non-empty `detail` array"
    for entry in detail:  # redundant with schema, kept for clearer failures
        validate(entry, _resolve(SPEC["components"]["schemas"]["ValidationError"], SPEC))
    locs = [[str(x) for x in entry["loc"]] for entry in detail]
    for part in loc_parts:
        assert any(part in loc for loc in locs), (
            f"expected an error located at ...{part!r}, got locations: {locs}"
        )


def unique_domain() -> str:
    return f"ct-{uuid.uuid4().hex[:12]}.test"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def manager():
    return Client(MANAGER_BASE_URL)


@pytest.fixture(scope="session")
def sync():
    return Client(SYNC_BASE_URL)


@pytest.fixture
def new_rule(manager):
    """Factory creating rules; deletes them and re-syncs on teardown."""
    created_ids: list[str] = []

    def _make(domain: str | None = None, **fields):
        payload = {"domain": domain or unique_domain()}
        payload.update(fields)
        r = manager.req("POST", "/rules", json=payload)
        body = assert_response(r, "/rules", "post", 201)
        created_ids.append(body["id"])
        return body

    yield _make

    for rule_id in created_ids:
        manager.req("DELETE", f"/rules/{rule_id}")
    manager.req("POST", "/sync/retry")  # best-effort resync after cleanup


def fresh_version() -> int:
    # Millisecond timestamp: stays above any small counter-based snapshot
    # version so pushes under test are never treated as stale.
    return int(time.time() * 1000)


# ==========================================================================
# Manager API
# ==========================================================================

class TestManagerHealth:
    def test_health_returns_json_object(self, manager):
        body = assert_response(manager.req("GET", "/health"), "/health", "get", 200)
        assert isinstance(body, dict), "Response Health Health Get must be a JSON object"


class TestManagerRules:
    def test_list_rules_matches_ruleout_schema(self, manager):
        body = assert_response(manager.req("GET", "/rules"), "/rules", "get", 200)
        assert isinstance(body, list), "GET /rules must return a JSON array"

    def test_create_rule_returns_201_with_valid_ruleout(self, new_rule):
        rule = new_rule(domain="https://news.example.com/story", include_subdomains=False)
        assert isinstance(rule["id"], str) and rule["id"]
        assert rule["include_subdomains"] is False

    def test_create_rule_defaults_include_subdomains_to_true(self, manager):
        r = manager.req("POST", "/rules", json={"domain": unique_domain()})
        body = assert_response(r, "/rules", "post", 201)
        try:
            assert body["include_subdomains"] is True, (
                "RuleCreate.include_subdomains defaults to true per the contract"
            )
        finally:
            manager.req("DELETE", f"/rules/{body['id']}")

    def test_create_rule_strips_scheme_credentials_port_and_path(self, new_rule):
        # RuleCreate.domain description: "schemes, paths, ports and credentials are stripped".
        rule = new_rule(domain="https://user:pw@news.example.com:8080/story?x=1")
        assert rule["domain"] == "news.example.com"

    def test_created_at_is_iso8601(self, new_rule):
        # NOTE: the spec types created_at as a bare string; this asserts the
        # intended ISO-8601 contract and flags the missing `format` in the schema.
        rule = new_rule()
        datetime.fromisoformat(rule["created_at"].replace("Z", "+00:00"))

    def test_create_rule_rejects_missing_domain(self, manager):
        assert_422(manager.req("POST", "/rules", json={}), "/rules", "post", 422, "domain")

    def test_create_rule_rejects_wrong_type_for_domain(self, manager):
        r = manager.req("POST", "/rules", json={"domain": ["not", "a", "string"]})
        assert_422(r, "/rules", "post", 422, "domain")

    def test_create_rule_rejects_non_json_body(self, manager):
        # requestBody is required with application/json content; a non-JSON body
        # must not be accepted as valid.
        r = manager.req("POST", "/rules", data="hello", headers={"Content-Type": "text/plain"})
        assert r.status_code != 201, "non-JSON body must not create a rule"

    def test_delete_rule_returns_204_and_removes_it(self, manager):
        r = manager.req("POST", "/rules", json={"domain": unique_domain()})
        rule_id = assert_response(r, "/rules", "post", 201)["id"]

        r = manager.req("DELETE", f"/rules/{rule_id}")
        assert r.status_code == 204, f"expected 204, got {r.status_code}: {r.text[:200]}"
        assert r.content == b"", "204 must have an empty body"

        listing = assert_response(manager.req("GET", "/rules"), "/rules", "get", 200)
        assert rule_id not in [item["id"] for item in listing]

    def test_delete_unknown_rule_stays_within_documented_codes(self, manager):
        # The spec declares only 204 and 422 for DELETE /rules/{rule_id} — no 404.
        r = manager.req("DELETE", f"/rules/does-not-exist-{uuid.uuid4().hex}")
        assert r.status_code in (204, 422), (
            f"got {r.status_code}; the contract documents only 204/422 "
            "(a 404 here means the spec is incomplete)"
        )
        if r.status_code == 422:
            assert_response(r, "/rules/{rule_id}", "delete", 422)


class TestManagerSyncRetry:
    def test_sync_retry_returns_valid_result(self, manager):
        body = assert_response(
            manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200
        )
        assert isinstance(body["pushed"], bool)
        assert isinstance(body["version"], int) and not isinstance(body["version"], bool)

    def test_sync_retry_version_is_monotonic(self, manager):
        v1 = assert_response(manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200)["version"]
        v2 = assert_response(manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200)["version"]
        # info.description: snapshot versions are monotonic.
        assert v2 >= v1, f"snapshot version went backwards: {v1} -> {v2}"


# ==========================================================================
# Sync API
# ==========================================================================

class TestSyncHealth:
    def test_health_returns_json_object(self, sync):
        body = assert_response(sync.req("GET", "/health"), "/health", "get", 200)
        assert isinstance(body, dict), "Response Health Health Get must be a JSON object"


class TestSyncBlocked:
    def test_blocked_returns_json_with_weak_etag(self, sync):
        # info.description: extensions poll /blocked with weak-ETag/304.
        r = sync.req("GET", "/blocked")
        body = assert_response(r, "/blocked", "get", 200)
        etag = r.headers.get("etag")
        assert etag, "GET /blocked must send an ETag for extension polling"
        assert etag.startswith(("W/", 'w/')), f"expected a weak ETag (W/ prefix), got {etag!r}"
        return body

    def test_blocked_honors_if_none_match_with_304(self, sync):
        first = sync.req("GET", "/blocked")
        assert first.status_code == 200
        etag = first.headers["etag"]

        second = sync.req("GET", "/blocked", headers={"If-None-Match": etag})
        assert second.status_code == 304, (
            f"If-None-Match with a fresh ETag must yield 304, got {second.status_code}"
        )
        assert second.content == b"", "304 must have an empty body"


class TestSyncPush:
    def test_push_valid_snapshot_acks_stored_version(self, sync):
        version = fresh_version()
        payload = {"version": version, "sites": [{"domain": unique_domain(), "include_subdomains": True}]}
        # Request body must conform to SyncPayload as declared.
        validate(payload, request_schema("/internal/sync", "post"))

        body = assert_response(
            sync.req("POST", "/internal/sync", json=payload), "/internal/sync", "post", 200
        )
        assert body["stored_version"] == version, (
            f"SyncAck.stored_version must echo the accepted snapshot version "
            f"(sent {version}, acked {body['stored_version']})"
        )

    def test_push_accepts_empty_sites_list(self, sync):
        payload = {"version": fresh_version(), "sites": []}
        assert_response(sync.req("POST", "/internal/sync", json=payload), "/internal/sync", "post", 200)

    def test_push_rejects_missing_required_fields(self, sync):
        r = sync.req("POST", "/internal/sync", json={})
        assert_422(r, "/internal/sync", "post", 422, "version", "sites")

    def test_push_rejects_negative_version(self, sync):
        # SyncPayload.version has minimum: 0.
        r = sync.req("POST", "/internal/sync", json={"version": -1, "sites": []})
        assert_422(r, "/internal/sync", "post", 422, "version")

    def test_push_rejects_wrong_types(self, sync):
        r = sync.req("POST", "/internal/sync", json={"version": "v1", "sites": "nope"})
        assert_422(r, "/internal/sync", "post", 422, "version", "sites")

    def test_push_rejects_site_missing_domain(self, sync):
        r = sync.req(
            "POST", "/internal/sync",
            json={"version": fresh_version(), "sites": [{"include_subdomains": True}]},
        )
        assert_422(r, "/internal/sync", "post", 422, "domain")

    def test_push_rejects_non_object_site_item(self, sync):
        r = sync.req(
            "POST", "/internal/sync",
            json={"version": fresh_version(), "sites": ["news.example.com"]},
        )
        assert_422(r, "/internal/sync", "post", 422)


class TestSyncState:
    def test_state_returns_json_object(self, sync):
        body = assert_response(sync.req("GET", "/internal/state"), "/internal/state", "get", 200)
        assert isinstance(body, dict), "debug state endpoint should return a JSON object"

    def test_state_reflects_last_pushed_snapshot(self, sync):
        marker = unique_domain()
        version = fresh_version()
        r = sync.req("POST", "/internal/sync", json={"version": version, "sites": [{"domain": marker}]})
        assert_response(r, "/internal/sync", "post", 200)

        state = assert_response(sync.req("GET", "/internal/state"), "/internal/state", "get", 200)
        # Schema is `{}` (free-form), so check the documented purpose: what the
        # Sync service currently holds.
        dump = yaml.dump(state)
        assert marker in dump, f"pushed domain {marker!r} not found in /internal/state"
        assert str(version) in dump, f"snapshot version {version} not found in /internal/state"


# ==========================================================================
# Cross-service contract (Manager -> Sync pipeline from info.description)
# ==========================================================================

class TestPipeline:
    def test_created_rule_reaches_blocked_after_retry(self, manager, sync, new_rule):
        rule = new_rule()
        retry = assert_response(manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200)
        if not retry["pushed"]:
            pytest.skip("Manager could not reach the Sync API; pipeline not exercised")

        blocked = sync.req("GET", "/blocked")
        assert blocked.status_code == 200
        assert rule["domain"] in yaml.dump(blocked.json()), (
            f"rule {rule['id']} ({rule['domain']}) missing from GET /blocked after a "
            "successful snapshot push"
        )

    def test_rules_report_synced_after_successful_push(self, manager, new_rule):
        rule = new_rule()
        retry = assert_response(manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200)
        if not retry["pushed"]:
            pytest.skip("Sync API did not acknowledge; sync_status transition not exercised")

        listing = assert_response(manager.req("GET", "/rules"), "/rules", "get", 200)
        mine = next(item for item in listing if item["id"] == rule["id"])
        # RuleOut.sync_status: "'synced' once the Sync API acknowledged the snapshot."
        assert mine["sync_status"] == "synced", (
            f"expected sync_status 'synced' after ack, got {mine['sync_status']!r}"
        )

    def test_etag_changes_after_new_snapshot(self, manager, sync, new_rule):
        before = sync.req("GET", "/blocked")
        assert before.status_code == 200
        old_etag = before.headers.get("etag")

        new_rule()
        retry = assert_response(manager.req("POST", "/sync/retry"), "/sync/retry", "post", 200)
        if not retry["pushed"]:
            pytest.skip("Manager could not reach the Sync API; pipeline not exercised")

        after = sync.req("GET", "/blocked")
        assert after.status_code == 200, "content changed: /blocked must return 200, not 304"
        assert after.headers.get("etag") != old_etag, (
            "ETag must change once the snapshot content changes; stale ETag breaks "
            "extension polling caches"
        )
```
