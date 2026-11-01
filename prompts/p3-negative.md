# P3 — Prompt de Casos de Erro e Ataque (Negative-case prompt)

**Intenção (PT-BR):** pedir à LLM que atue como QA adversarial e gere casos de erro/edge da integração —
indisponibilidade entre serviços, payloads malformados, inconsistência eventual. Alimenta
`tests/integration/test_p3_negative.py`.

---

## v1 (original)

```text
Act as an adversarial QA engineer. Generate error test cases for a REST API that manages a list of blocked websites and syncs them to another API consumed by a browser extension.
```

**Observed result:** produced only HTTP-level noise — bad JSON, missing fields, 404s on one service at a time. The *cross-service* failure modes (outage mid-write, stale consumer state, retry semantics) never appeared until the prompt named them as required dimensions.

## v2 (refined — use this one)

**What changed and why:** forced thinking across the integration seam by enumerating failure classes that involve BOTH services, demanded a severity + "worst user-visible symptom" column (this is what turns a list of 400s into real risk analysis), and banned single-service-only cases from counting toward the minimum.

```text
Act as an adversarial QA engineer whose specialty is breaking INTEGRATIONS between REST services, not individual endpoints.

SYSTEM: two services — Manager API (:3001) owns blocked-domain rules in SQLite with a monotonic version; on every mutation it pushes a full snapshot to Sync API's POST /internal/sync (:3002). If the push fails the rule stays sync_status="pending"; POST /sync/retry re-pushes. The Sync API serves GET /blocked (weak ETag W/"<version>", 304 on If-None-Match, 409 for stale versions) to a Chrome extension that polls every minute.

Generate adversarial INTEGRATION test cases as a Markdown table:
| # | Attack/failure class | Steps (which service receives what, in which order, including outages) | Expected resilient behavior | Worst user-visible symptom if the system gets it wrong | Severity (low/med/high) |

Hard requirements:
1. Minimum 8 rows; every row must involve BOTH services or the consumer's view of consistency — single-service input validation does NOT count.
2. You MUST cover at least: Sync API down during writes then recovery; multiple mutations (add+delete) during an outage then one retry; delete propagating correctly after an outage (consumer must eventually stop seeing the domain); stale/old-version snapshot injection into /internal/sync; replay of the same version (idempotency); malformed payloads at the internal sync seam; empty-list propagation; consumer behavior while data is stale.
3. Think like an attacker for at least 2 rows (e.g., forging snapshots, injecting domains with credentials/unicode tricks in the payload).
4. No generic advice — only concrete executable steps.
```

**Transcript:** save your raw LLM response as `generated-tests/p3-v2-<model>-<date>.md`.
