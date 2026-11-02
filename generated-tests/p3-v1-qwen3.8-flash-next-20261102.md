Model: LM Studio local (Qwen3.8 Flash Next)
Date: 2026-11-02
Prompt version: v1 (prompts/p3-negative.md)
---

## Error Test Cases — Blocked-Websites API + Sync Pipeline

### 1. Input Validation — URL/Domain Fields

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| V-01 | POST with empty body `{}` | `400` with field-level error; no record created |
| V-02 | POST with `url: ""`, `" "`, or whitespace-only | `400`; not persisted, not synced |
| V-03 | URL without scheme (`example.com`) vs. with (`https://example.com`) — verify canonicalization rules are enforced consistently | Either normalized identically or rejected per spec; never stored twice as distinct entries |
| V-04 | IDN/punycode homoglyph domain: `аpple.com` (Cyrillic 'a'), `gо0gle.com` mixed scripts | Rejected or normalized to punycode consistently with the extension's matcher |
| V-05 | URL with embedded credentials: `https://admin:p@ss@evil.com/` | Credentials stripped or entry rejected; never stored raw |
| V-06 | URL where the real host hides after redirect-looking path: `http://legit.com@google.com`, `http://google.com\@evil.com` | Host parsed as the true authority (`evil.com`); parser must match browser URL parsing, not regex |
| V-07 | Overlong/encoded host: `http://example.com%2e/`, trailing dot `example.com.`, uppercase `HTTP://EXAMPLE.COM` | Normalized to one canonical form; duplicate detection still works |
| V-08 | Port and non-http schemes: `ftp://x.com`, `file:///etc/passwd`, `javascript:alert(1)`, `data:text/html,...` | Non-blockable schemes rejected with explicit error, not silently accepted |
| V-09 | Wildcard/pattern injection in domain field: `*.com`, `*`, `.`, `..`, `example.*`, `||evil.com^` (AdBlock syntax) | Rejected unless pattern syntax is contractual; `*.` or bare `*` must never match-all the extension |
| V-10 | Regex metacharacters and ReDoS payload: `(a+)+$`, nested quantifiers in domain field | Stored as literal string, never compiled as regex by API or sync consumer |
| V-11 | Oversized input: 64 KB URL, 10k query params, 1M-char domain label, >253-char hostname (RFC limit) | `414`/`400`; no OOM, no DB truncation that silently changes semantics (`evil.co` truncated from long string) |
| V-12 | Unicode edge cases: RTL override `‮gpj.moc`, zero-width joiners inside domain, combining marks, NFD vs NFC forms of the same domain | Normalization (UTS #46 / casefold) applied; NFD and NFC inputs dedupe to one entry |
| V-13 | XSS/stored-script payload in note/tag fields: `<script>alert(1)</script>`, `"><img onerror=...>` | Stored escaped or rejected; rendered safely by any admin UI; never reflected raw in sync response |
| V-14 | SQL/NoSQL injection in filter and search params: `' OR 1=1--`, `{"$gt":""}`, `%00` null bytes | Parameterized handling confirmed; null byte → `400`, not silent truncation |
| V-15 | Wrong types: `url: 12345`, `url: ["a","b"]`, `enabled: "yes"`, extra unknown fields, arrays where objects expected | Strict schema validation → `400`/`422`; no type coercion creating valid-looking records |
| V-16 | Duplicate insert — same domain submitted twice concurrently (parallel POSTs) | Exactly one row survives (unique constraint); second gets `409`, not a duplicate that syncs twice |

### 2. Authentication & Authorization

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| A-01 | All endpoints with no token, expired token, malformed JWT (`alg:none`, tampered signature, `exp` in past) | `401`; never `500`; `alg:none` explicitly rejected |
| A-02 | Valid token for user B accessing/deleting user A's blocklist entries (IDOR: guess sequential IDs `/blocked/1337`) | `403` or `404` — must not leak existence via different status codes if spec says so; never `200` |
| A-03 | Extension-scoped read-only token attempting POST/PUT/DELETE/sync-trigger | `403`; scope enforcement verified server-side, not just UI-hidden |
| A-04 | Token with downgraded role replayed after role change (permission revoked mid-session) | Next request fails; no cached-permission window beyond stated TTL |
| A-05 | Sync endpoint called directly by the extension using another user's API key captured from a shared machine | Cross-user data never returned; per-installation secret rotation works |
| A-06 | Brute force: 10k auth attempts, and 10k sequential ID probes | Rate-limited/locked out with `429` + `Retry-After`; no timing oracle on token comparison (constant-time compare) |

### 3. CRUD & State Errors

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| C-01 | GET/PUT/DELETE nonexistent ID, negative ID, `0`, non-numeric ID (`abc`, UUID with dashes stripped), `NaN`, `null` as string | `404`/`400` consistently; never `500`, never empty `200` |
| C-02 | PUT partial body omitting required fields vs. PATCH semantics confusion | Partial update rejected or applied per documented semantics — no silent field wipe to null |
| C-03 | DELETE already-deleted entry (soft-delete), then re-add same domain, then sync | Re-add wins; tombstone doesn't resurrect the block in the extension; state machine has no illegal transition |
| C-04 | Update an entry while a sync of it is in flight | Final synced state equals final stored state — no lost update, no stale overwrite |
| C-05 | Mass insert: POST 10k entries in one payload and 10k individual concurrent POSTs | Payload size limit enforced (`413`); under load, list stays consistent; sync doesn't time out mid-page and emit a partial list |

### 4. Sync Pipeline (the highest-risk surface)

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| S-01 | Upstream sync API returns `500`, `502`, `503`, `429`, malformed JSON, truncated JSON body, valid JSON of unexpected shape (`[]` instead of `{}`) | Sync marked failed and retried per policy; local state untouched; no partial/corrupt push; error surfaced in status endpoint |
| S-02 | Upstream responds 30s+ (timeout), hangs without closing connection, or sends headers then stalls body | Client timeout fires; sync fails cleanly; no zombie "in-progress" flag that blocks all future syncs forever |
| S-03 | Two syncs triggered concurrently (manual + cron) | One runs or both are idempotent; upstream never receives interleaved/duplicated pages; no double-applied deletes |
| S-04 | Sync succeeds locally but upstream response is lost (network cut after upstream committed) — retry the same sync | Idempotency key/version token makes retry safe; extension doesn't get duplicate entries or a re-blocked deleted site |
| S-05 | Delete-last-entry scenario: blocklist becomes empty, then syncs | Upstream receives explicit "empty list" signal, not a skipped request that leaves stale blocks in the extension (fail-open vs fail-closed must match spec) |
| S-06 | Version/etag mismatch: client pushes based on stale revision after server changed | `409` conflict; no last-write-wins silently resurrecting a deleted block |
| S-07 | Sync cursor/page token tampering: negative page, huge `limit=1e9`, expired cursor, another tenant's cursor | `400`/`403`; no cross-tenant list leakage through cursor reuse |
| S-08 | Upstream returns success envelope with per-item errors (`207`-style partial failure) | Partial failures recorded and retried; overall sync not reported as fully successful |
| S-09 | Clock skew: signed sync requests generated 10 min in future/past | Rejected or accepted within documented skew window only — no `500` |
| S-10 | Extension polls with stale `If-None-Match`; server list changed and reverted between polls | Etag reflects content hash, not timestamp alone; extension doesn't miss a change that occurred and reverted (or spec explicitly allows it) |

### 5. Concurrency & Consistency

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| X-01 | Parallel add + delete of the same domain from two clients | Deterministic final state; sync payload matches DB, verified by diffing both |
| X-02 | 100 concurrent writes then immediate sync read-replica fetch | Sync reads primary or a consistent snapshot — never pushes a list missing committed entries |
| X-03 | Kill the API process mid-sync (SIGKILL during push) | On restart, sync resumes/retries from durable state; no permanently stuck queue, no half-pushed upstream state reported as clean |

### 6. Abuse & Resource Exhaustion

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| R-01 | Unauthenticated flood of sync-trigger endpoint (it's expensive) | `429` early; trigger requires auth and per-user rate limit |
| R-02 | Payload bomb: 50 MB JSON body, deeply nested arrays (`[[[[...]]]]`, depth 10k), gzip bomb (`1 KB → 1 GB`) | Body-size cap before parse; parser depth limit; decompression ratio cap — no OOM/`503` for other tenants |
| R-03 | Slowloris-style slow-drip request bodies; `Content-Length` mismatch with actual bytes sent | Timeouts fire; mismatched length → `400`, not hang or truncated-record write |
| R-04 | Header abuse: oversized custom headers, duplicate `Authorization` headers, CRLF injection in header values (`\r\nSet-Cookie:...`) | Rejected at edge; no header splitting into responses or upstream requests (SSRF via injected upstream URL header if sync target is configurable) |

### 7. Protocol & Edge Behavior

| # | Test Case | Expected Result |
|---|-----------|-----------------|
| P-01 | Wrong `Content-Type` (`text/plain`, missing, `application/x-www-form-urlencoded` with JSON body); invalid UTF-8 bytes in body; BOM prefix | `415`/`400`; no mojibake domain stored that silently fails to match in the extension |
| P-02 | Methods: `HEAD` on POST-only route, `TRACE`, arbitrary verb, `OPTIONS` preflight from a hostile origin (`evil.com`) | Correct `405` + `Allow`; CORS never `Access-Control-Allow-Origin: *` with credentials |
| P-03 | HTTP/1.0 request, chunked body without terminator, `Expect: 100-continue` abuse | Handled by server or rejected cleanly — no `500`s in logs treated as acceptable noise |
| P-04 | Response-injection check: does a stored malicious domain echo unsanitized into the sync JSON consumed by the extension (which may build match rules from it)? | Extension receives data-only JSON; verify end-to-end that a crafted entry cannot break out of the matcher config (e.g., newline in domain field splitting a hosts-style file) |

**Priority note:** S-01/S-04/S-05 (partial-failure and empty-list semantics) and V-06/V-09 (host-parsing divergence between API and extension matcher) are the classes where "both sides pass their own tests but the block silently doesn't apply" — treat every one of these as an end-to-end test against a real extension build, not just an API-level assertion.
