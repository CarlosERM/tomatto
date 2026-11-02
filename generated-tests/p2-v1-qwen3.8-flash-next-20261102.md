Model: LM Studio local (Qwen3.8 Flash Next)
Date: 2026-11-02
Prompt version: v1 (prompts/p2-scenarios.md)
---

## Integration Test Scenarios: Website-Blocking System

### 1. Core Data Flow (API1 → API2)

**1.1 Add domain propagates to poll endpoint**
- POST `blocked-domain.com` to the management API (API1).
- GET the block list from the polling API (API2).
- **Expect:** `blocked-domain.com` appears in the response within one polling cycle.

**1.2 Remove domain propagates to poll endpoint**
- Seed a blocked domain, confirm it appears via API2, DELETE it via API1.
- Poll API2 again.
- **Expect:** domain no longer present; no tombstone/stale entry remains.

**1.3 Multiple domains added in sequence**
- POST 50 domains one by one via API1, polling API2 after each.
- **Expect:** final poll returns exactly the 50 domains, no duplicates, no losses.

**1.4 End-to-end latency bound**
- Measure time between successful POST on API1 and domain appearing in API2's response.
- **Expect:** within the documented sync/polling interval (e.g., ≤ N seconds).

---

### 2. CRUD Operations on the Management API

**2.1 Create with valid payload** → 201, persisted, visible via API2.

**2.2 Duplicate domain rejected/idempotent**
- POST `example.com` twice.
- **Expect:** second call returns 409 (or idempotent 200/204) and the block list contains exactly one entry for it.

**2.3 Invalid inputs rejected**
- Empty string, whitespace-only, URLs with scheme (`https://x.com`), malformed hosts (`not a domain`, `exa mple.com`), oversized strings (>253 chars).
- **Expect:** 4xx with error body; API2 list unchanged (no partial writes).

**2.4 Case-insensitivity and normalization**
- Add `Example.COM`; poll for `example.com`.
- **Expect:** stored/returned in normalized lowercase form; extension matching works regardless of case.

**2.5 Wildcard/subdomain semantics**
- Add `ads.example.com` — verify `sub.ads.example.com` behavior matches spec (blocked only if wildcard rules apply).
- Add `*.example.com` or bare domain per spec — verify subdomain coverage is consistent between what API1 stores and what API2 serves.

**2.6 Update/patch a domain entry** (e.g., change from block-all to block-on-schedule, if supported) → new state reflected in next poll.

**2.7 Delete non-existent domain** → 404; list via API2 unaffected.

---

### 3. Polling API Behavior (API2 ↔ Extension Contract)

**3.1 Response schema stability**
- Poll with an empty blocklist and a populated one.
- **Expect:** valid JSON matching the contract (`{ "domains": [...], "version"/"etag": ... }`), never `null`, never malformed; empty list is `[]`.

**3.2 Conditional requests / caching headers**
- Poll twice without changes, sending back the ETag/`If-None-Match` (or version param).
- **Expect:** second poll returns 304 (or equivalent "no change" signal) so the extension skips reprocessing; after a POST to API1, next poll returns 200 with updated list and new ETag.

**3.3 Polling at documented interval under idle conditions**
- Simulate an extension polling every N seconds for M minutes with no changes.
- **Expect:** consistent responses, no drift in version numbers, no memory/DB growth from poll requests themselves.

**3.4 Incremental/delta updates (if supported)**
- Add 2 domains and remove 1 between polls.
- **Expect:** delta response contains exactly `+2 / -1`; applying the deltas to the extension's local cache converges to the full list returned by a fresh poll.

---

### 4. Concurrency and Consistency

**4.1 Concurrent adds from multiple clients**
- Fire 20 parallel POSTs (distinct domains) at API1, then poll API2.
- **Expect:** all 20 present; no race-lost writes.

**4.2 Concurrent add + delete of the same domain**
- POST and DELETE `race-test.com` simultaneously.
- **Expect:** final state is deterministic per spec (e.g., last-write-wins), API1 and API2 agree, no orphaned record.

**4.3 Poll during a write**
- Poll API2 continuously while API1 processes writes.
- **Expect:** every poll returns a valid snapshot — never a partially applied list, never 5xx caused by locking.

**4.4 Eventual consistency guarantee**
- After all API1 writes return success, poll API2 until stable (with timeout).
- **Expect:** converges to exactly the set stored in API1's datastore; document and assert the maximum staleness window.

---

### 5. Authentication and Authorization Across Both APIs

**5.1 Unauthenticated write to API1** → 401/403, no state change visible via API2.
**5.2 Authenticated poll of API2 with extension credentials** → 200; wrong/expired token → 401 and the extension keeps its last-known list (verify client-side fallback contract).
**5.3 Read-only credential cannot write** — POST with a poll-scoped token to API1 → 403.
**5.4 Credential rotation mid-session** — rotate API2's key; old polls fail, new-token polls succeed without the extension receiving a corrupted/empty list.

---

### 6. Error Handling and Resilience

**6.1 API1 down while polling continues** → API2 keeps serving last synced list (or documented degraded behavior), never an empty list that would silently unblock everything.
**6.2 API2 restart / cold start** → first poll after boot returns the full current list from the datastore, not a stale cache or 503 loop.
**6.3 Sync job failure and retry** — simulate DB/sync failure between APIs; verify retry recovers and no duplicate entries appear after recovery.
**6.4 Malformed write bypassing validation (direct DB insert)** → API2 either sanitizes on serve or surfaces a documented error; extension must not receive invalid host strings that break its matcher.

---

### 7. Scale and Performance (Integration-Level)

**7.1 Large list delivery** — seed 10,000 domains via API1; poll API2.
- **Expect:** response completes within timeout, payload size acceptable for the extension, pagination or compression applied per spec.

**7.2 Many extensions polling simultaneously** — 500 concurrent pollers with occasional writes to API1.
- **Expect:** p95 poll latency within budget; no dropped updates; API1 writes still succeed.

---

### 8. Lifecycle / State Transition Scenarios

**8.1 Full lifecycle in one flow:** add → poll (present) → pause/disable entry via API1 → poll (absent or flagged inactive per spec) → re-enable → poll (present) → delete → poll (absent).
**8.2 Scheduled/temporary blocks** — domain with an expiry timestamp: present before expiry, absent after; verify the transition happens without any API1 call in between.
**8.3 Reset/clear-all operation on API1** → next poll returns `[]`; a subsequent single add returns exactly one entry (no resurrection of cleared domains from cache).

---

### Suggested Test Matrix Summary

| Area | Key assertion |
|---|---|
| Sync correctness | What API1 stores == what API2 serves (after staleness window) |
| Contract stability | Schema, ETags, empty-state shape never break the extension |
| Concurrency | No lost writes, no torn reads, deterministic conflicts |
| Failure modes | Degradation never silently unblocks sites |
| Scale | Latency and payload stay within budget at target load |
