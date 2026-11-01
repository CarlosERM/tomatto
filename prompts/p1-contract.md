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

**Observed result:** produced generic per-endpoint happy-path checks ("returns 200", "body is JSON"). It ignored the *relationship* between the two services (version propagation, ETag semantics) and invented endpoints that don't exist in some runs.

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

**Transcript:** save your raw LLM response as `generated-tests/p1-v2-<model>-<date>.md` (see generated-tests/README.md).
