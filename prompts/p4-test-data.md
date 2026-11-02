# P4 — Prompt de Dados de Teste (Test-data prompt)

**Intenção (PT-BR):** gerar um dataset realista e adversarial de domínios para popular os testes
parametrizados — IDN/punycode, URLs completas, credenciais embutidas, portas, rótulos inválidos.
Alimenta `tests/integration/data/blocklist_dataset.json` e `test_p4_test_data.py`.

---

## v1 (original)

```text
Generate a list of 20 realistic website domains I can use as test data for testing a website-blocking API.
```

**Observed result (Qwen3.8 Flash Next, [`generated-tests/p4-v1-qwen3.8-flash-next-20261102.md`](../generated-tests/p4-v1-qwen3.8-flash-next-20261102.md)):** exactly as feared — `facebook.com`, `youtube.com`, `twitter.com`… 20 real brand names, zero edge value. Not one row exercises normalization (no scheme, no port, no uppercase, no IDN, no credentials), so nothing in it could ever catch a parser bug; and half of them are only interesting as *brands*, not as inputs.

## v2 (refined — use this one)

**What changed and why:** switched from "domains" to *inputs users actually paste* (URLs with credentials, ports, trailing dots), demanded machine-readable JSON with the expected normalized form per row (this is what makes the output directly executable as a parametrized test), and enumerated the exact edge families so diversity is guaranteed rather than hoped for.

```text
You are a test-data engineer for a domain-blocking API. Input format accepted by the API: any string a user might paste — bare domains, full URLs (with scheme/path/query/fragment), uppercase text, hosts with ports or trailing dots, internationalized domains, and hostile inputs like embedded credentials ("http://user:pass@evil.example.com/x").

Rules of the system under test: it normalizes input to a lowercase multi-label ASCII hostname (unicode → punycode), strips scheme/path/query/fragment/port/credentials/trailing-dot, and REJECTS with 422: empty strings, single labels ("localhost"), underscores in labels, internal whitespace, leading-hyphen labels, empty labels ("a..com"), IPv6 literals, labels over 63 chars.

Produce ONLY a JSON object (no prose):
{
  "accept": [ {"input": "...", "normalized": "<exact expected ASCII hostname>", "note": "<why this is interesting>"} ],
  "reject": [ {"input": "...", "note": "<which rule it violates>"} ]
}

Requirements:
1. Exactly 12 accept rows and 8 reject rows.
2. Accept rows MUST collectively include: uppercase normalization, full URL with query+fragment, embedded credentials (open-redirect style), trailing dot, port suffix, deep subdomain, Latin-script IDN (e.g., accented .com.br), CJK IDN, already-punycode input, IP literal, and two inputs that normalize to the SAME domain as another row (to test duplicate handling).
3. Compute "normalized" precisely — punycode must be correct, not approximate.
4. Reject rows: one per rejection rule listed above.
```

**Observed result (v2, Qwen3.8 Flash Next, [`generated-tests/p4-v2-qwen3.8-flash-next-20261102.md`](../generated-tests/p4-v2-qwen3.8-flash-next-20261102.md)):** exactly 12 accept + 8 reject rows, all required families present, and the punycode is **correct** — verified against Python's `idna`: `café.com.br → xn--caf-dma.com.br`, `中国.com → xn--fiqs8s.com`, `xn--mnchen-3ya.de` passed through unchanged. The duplicate pair arrived as intended (`EXAMPLE.COM` and `example.com.` both normalize to `example.com`). One judgement call it made on its own: it accepts the IPv4 literal `192.0.2.1`, reasoning that only IPv6 is rejected — technically right per our rules, but a 4-label numeric "domain" deserves an explicit test rather than an inference.

**Transcript:** saved as [`generated-tests/p4-v2-qwen3.8-flash-next-20261102.md`](../generated-tests/p4-v2-qwen3.8-flash-next-20261102.md). Note: the two same-normalization inputs are intentional — the suite asserts the second is a legitimate 409 (normalization equivalence).
