# P2 — Prompt de Cenários de Integração (Scenario prompt)

**Intenção (PT-BR):** descrever o fluxo ponta a ponta em linguagem natural e pedir cenários de teste de
integração no formato Given/When/Then, cobrindo o caminho completo Manager → Sync → extensão.
Alimenta `tests/integration/test_p2_scenarios.py`.

---

## v1 (original)

```text
Generate integration test scenarios for a website-blocking system composed of a REST API that stores blocked domains and another REST API polled by a browser extension to get the block list.
```

**Observed result:** shallow happy-path only ("add domain, appears in list"). No polling semantics, no persistence, nothing about *how* the two services stay consistent — exactly the part where integration bugs live.

## v2 (refined — use this one)

**What changed and why:** added the architectural mechanism (write-through push + monotonic version + ETag polling), demanded a minimum count of scenarios spanning specific integration dimensions, and required each scenario to name both services in Given/When/Then so single-service tests couldn't be passed off as integration tests.

```text
You are a senior test architect specializing in distributed-system testing.

SYSTEM: "Tomatto", a simplified website blocker with two REST services plus a browser extension:
- Manager API (:3001): POST /rules, GET /rules, DELETE /rules/{id}, POST /sync/retry. Persists rules in SQLite and assigns every mutation a monotonic version number. After each mutation it SYNCHRONOUSLY pushes a full snapshot {version, sites[]} to the Sync API (write-through). If the push fails, rules are marked sync_status="pending" until POST /sync/retry succeeds.
- Sync API (:3002): stores only the latest received snapshot; GET /blocked returns {version, sites[]} with weak ETag W/"<version>"; honors If-None-Match with 304. A Chrome extension polls GET /blocked once per minute using this ETag handshake.

Write integration test SCENARIOS (not code) in Given/When/Then format. Requirements:
1. At least 6 scenarios; each must involve BOTH services in the same flow — a scenario that only touches one service is invalid.
2. Cover these integration dimensions explicitly: full lifecycle propagation (add → visible, delete → gone); the extension's polling loop across an unchanged interval and a changed one; consistency of multi-rule snapshots; persistence when the Manager process restarts but the database survives; retry-after-outage recovery; behavior of the consumer during staleness.
3. For each scenario add a final line: "Integration seam tested:" naming which components communicate (e.g., Manager→Sync push, Sync↔consumer cache validation).
4. Number them S1..Sn and keep each under 6 lines.
```

**Transcript:** save your raw LLM response as `generated-tests/p2-v2-<model>-<date>.md`.
