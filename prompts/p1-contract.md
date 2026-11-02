# P1 — Prompt de Contrato de API (Contract prompt)

**Intenção (PT-BR):** fornecer à LLM a especificação OpenAPI dos dois serviços e pedir que ela derive,
linha a linha, os testes de contrato entre Manager API e Sync API — status codes, formatos de payload e
a semântica do handshake ETag/304. Alimenta `tests/integration/test_p1_contract.py`.

---

## v1 (original)

```text
You are a QA engineer. Here is the OpenAPI spec of two REST services (Tomatto Manager API and Tomatto Sync API). Generate contract tests for these APIs.

<PASTE docs/openapi.yaml HERE>
```

**Observed result (Qwen3.8 Flash Next, [`generated-tests/p1-v1-qwen3.8-flash-next-20261102.md`](../generated-tests/p1-v1-qwen3.8-flash-next-20261102.md)):** far better than expected — it emitted *executable* pytest code that loads the spec, resolves `$ref`s and validates every documented response with `jsonschema`, covered all 7 endpoints without inventing any, and even derived cross-service pipeline tests from the spec's `info.description`. Two real gaps: nothing about stale-version rejection (the spec never documents a 409, so an unanchored prompt never asks for it), and when Sync was unreachable the generated code called `pytest.skip` — turning a broken integration into a silently green suite.

## v2 (refined — use this one)

**What changed and why:** anchored the model to the spec as the single source of truth ("one check per line"), forced a table output format to prevent hallucinated prose, and explicitly named the cross-service contract elements (monotonic version, weak ETag/304, stale-snapshot 409) so it couldn't skip them.

```text
You are an API contract-testing specialist. Below is the OpenAPI 3.1 spec of two independent services that integrate over HTTP:

- Manager API (:3001): owns a block list; on every mutation it pushes a full snapshot {version, sites[]} to Sync's POST /internal/sync. Version is monotonic (increments per mutation).
- Sync API (:3002): stores the latest snapshot and serves GET /blocked with a weak ETag W/"<version>"; If-None-Match matching the current version MUST return 304 with empty body; snapshots older than the stored version MUST be rejected with 409.

Using ONLY endpoints, fields and status codes present in the spec below, produce a contract-test checklist as a Markdown table with columns:
| # | Service | Endpoint | Given (request) | Then (status + exact response shape/header assertion) | Contract promise violated if it fails |

Rules:
1. One row per distinct contract promise (status code, required field, header semantics). No prose outside the table.
2. Cover every endpoint in the spec at least once.
3. Include rows for the cross-service promises described above (version monotonicity, ETag/304 handshake, stale-snapshot rejection, idempotent same-version push).
4. Do not invent endpoints, fields or status codes that are absent from the spec.

<SPEC>
<PASTE docs/openapi.yaml HERE>
</SPEC>
```

**Observed result (v2, Qwen3.8 Flash Next, [`generated-tests/p1-v2-qwen3.8-flash-next-20261102.md`](../generated-tests/p1-v2-qwen3.8-flash-next-20261102.md)):** 19 rows, one per promise, every endpoint covered, and the four cross-service rows landed (version `v2 = v1 + 1`, `304` with empty body, stale push → `409` leaving state unchanged, same-version replay idempotent). It also surfaced a flaw **in my prompt**: rule 4 forbids status codes absent from the spec, while rule 3 demands a stale-snapshot rejection row — and `docs/openapi.yaml` documents no `409` at all (FastAPI can't infer it). The model resolved the contradiction silently in favour of rule 3, producing a test for behaviour the API implements but never declares. Two lessons: conflicting constraints are resolved without asking, and the real bug is spec drift — `/internal/sync` should declare `409`.

**Transcript:** saved as [`generated-tests/p1-v2-qwen3.8-flash-next-20261102.md`](../generated-tests/p1-v2-qwen3.8-flash-next-20261102.md).
