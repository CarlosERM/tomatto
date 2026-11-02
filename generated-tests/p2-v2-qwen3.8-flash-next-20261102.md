Model: LM Studio local (Qwen3.8 Flash Next)
Date: 2026-11-02
Prompt version: v2 (prompts/p2-scenarios.md)
---

S1 — Add propagates via write-through push
Given the Manager and Sync APIs are running with an empty rule set
When a POST /rules adds "example.com" and the client then GETs /blocked on the Sync API
Then the response contains {version: 1, sites: ["example.com"]} with ETag W/"1", returned in the same request that created the rule (no polling delay)
Integration seam tested: Manager→Sync synchronous write-through push (snapshot handoff on mutation).

S2 — Delete propagates and removes from consumer view
Given "example.com" and "ads.net" exist as rules and their snapshot was pushed to Sync
When DELETE /rules/{id} removes "example.com" and the client GETs /blocked
Then sites contains only "ads.net" at a strictly higher version than before, and the deleted site is absent
Integration seam tested: Manager→Sync push on delete + full-snapshot replacement semantics in Sync's store.

S3 — Extension polling loop across unchanged and changed intervals
Given the extension has polled GET /blocked and cached snapshot version N with ETag W/"N"
When it polls again one minute later with If-None-Match: W/"N" and no mutation occurred, then a rule is added and it polls again with the same header
Then the first poll returns 304 with an empty body (cache reused), and the second returns 200 with ETag W/"N+1" and the new full snapshot
Integration seam tested: Sync↔consumer ETag/If-None-Match cache-validation handshake.

S4 — Multi-rule snapshot consistency
Given both services are running with zero rules
When three POST /rules calls add "a.com", "b.com", "c.com" sequentially, then GET /blocked is called
Then the snapshot contains all three sites atomically at version 3 (one monotonic bump per mutation), and no intermediate response ever shows a partial or duplicated site list
Integration seam tested: Manager version numbering→Sync full-snapshot atomicity (no torn reads across successive pushes).

S5 — Manager restart with surviving database
Given rules exist at version N, their snapshot is in Sync, and the Manager process is then killed and restarted against the same SQLite file
When GET /rules on the fresh Manager instance lists the rules and a new rule is added, followed by GET /blocked
Then all pre-restart rules are present with sync_status confirmed, the new mutation receives version N+1 (monotonicity survives restart), and Sync serves the complete N+1 snapshot
Integration seam tested: SQLite persistence→Manager in-memory version state→Sync push continuity across process lifecycle.

S6 — Push failure during outage, recovery via retry
Given the Sync API is unreachable (simulated outage) when POST /rules adds "tracker.io"
When the Manager responds to the create, then the Sync API comes back and POST /sync/retry is invoked, followed by GET /blocked
Then the rule was still created with sync_status="pending", the retry succeeds, sync_status clears, and GET /blocked now includes "tracker.io" at the pending version
Integration seam tested: Manager failure handling→Sync re-push path (outage queue + POST /sync/retry contract).

S7 — Consumer behavior during staleness window
Given a rule was deleted in the Manager while Sync was down, so Sync still holds stale snapshot version M < current Manager version
When the extension polls GET /blocked with its cached ETag W/"M" before any retry occurs
Then it receives 304 and continues enforcing the stale list without error or empty-list fallback; after POST /sync/retry succeeds, the next poll returns 200 with the corrected snapshot at the current version
Integration seam tested: Sync↔consumer staleness tolerance (ETag handshake over an un-updated store) + Manager→Sync convergence on retry.
